"""Migraciones y carga de maestros.

    python -m app.db.migrar               # aplica migraciones pendientes + seeds globales
    python -m app.db.migrar --recrear     # (solo desarrollo) borra la base indicada y la crea de cero

Usa DATABASE_URL. Cada archivo db/migraciones/NNNN_*.sql se aplica una sola vez, en orden, dentro de una
transacción, y queda registrado en schema_migraciones. En Supabase, el stub de auth no se crea: ya existe.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

RAIZ = Path(__file__).resolve().parents[3]
MIGRACIONES = RAIZ / "db" / "migraciones"
SEEDS = RAIZ / "db" / "seeds"

STUB_AUTH = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
"""


def _json(nombre: str):
    return json.loads((SEEDS / f"{nombre}.json").read_text(encoding="utf-8"))


def aplicar_migraciones(conn: psycopg.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migraciones (version text PRIMARY KEY, aplicada_en timestamptz NOT NULL DEFAULT now())")
    hechas = {r[0] for r in conn.execute("SELECT version FROM schema_migraciones")}
    if not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'auth'").fetchone():
        conn.execute(STUB_AUTH)          # PostgreSQL sin Supabase
    aplicadas = []
    for archivo in sorted(MIGRACIONES.glob("*.sql")):
        version = archivo.stem
        if version in hechas:
            continue
        with conn.transaction():
            conn.execute(archivo.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migraciones (version) VALUES (%s)", (version,))
        aplicadas.append(version)
    return aplicadas


def cargar_seeds(conn: psycopg.Connection) -> dict[str, int]:
    """Maestros globales (cliente_id NULL). Idempotente: reemplaza los globales, no toca los de clientes."""
    with conn.transaction():
        conn.execute("DELETE FROM reglas_clasificacion WHERE cliente_id IS NULL")
        conn.execute("DELETE FROM rubros WHERE cliente_id IS NULL")
        # los perfiles los referencian los lotes ya importados: se actualizan en el lugar y solo se borran
        # los globales que salieron del seed y nadie usa
        codigos = [p["codigo"] for p in _json("perfiles")]
        conn.execute("""DELETE FROM perfiles_importacion p WHERE cliente_id IS NULL AND NOT (codigo = ANY(%s))
                        AND NOT EXISTS (SELECT 1 FROM lotes_importacion l WHERE l.perfil_id = p.id)""", (codigos,))
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO rubros (codigo, nombre, linea_pl, linea_cf, comportamiento, signo, indice_ajuste,
                   tolerancia, sin_factura, grupo_prime, uso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(r["codigo"], r["nombre"], r["linea_pl"], r["linea_cf"], r["comportamiento"], r["signo"],
                  r["indice_ajuste"] or "IPC", r["tolerancia"], r["sin_factura"], r["grupo_prime"], r["uso"])
                 for r in _json("rubros")])
            cur.executemany(
                """INSERT INTO perfiles_importacion (codigo, nombre, tipo_origen, config) VALUES (%s,%s,%s,%s)
                   ON CONFLICT (cliente_id, codigo) DO UPDATE
                   SET nombre = EXCLUDED.nombre, tipo_origen = EXCLUDED.tipo_origen, config = EXCLUDED.config""",
                [(p["codigo"], p["nombre"], p["tipo_origen"], Jsonb(p)) for p in _json("perfiles")])
            cur.executemany(
                """INSERT INTO reglas_clasificacion (prioridad, texto, tipo, rubro_codigo, medio_pago, comentario)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                [(g["prioridad"], g["texto"], g["tipo"], g["rubro"], g["medio_pago"], g["comentario"])
                 for g in _json("reglas")])
            cur.executemany("INSERT INTO entidades_financieras (nombre, tipo) VALUES (%s,%s) ON CONFLICT (nombre) DO NOTHING",
                            [(e["nombre"], e["tipo"]) for e in _json("entidades")])
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("rubros", "perfiles_importacion", "reglas_clasificacion", "entidades_financieras")}


def recrear_base(url: str) -> None:
    base, nombre = url.rsplit("/", 1)
    with psycopg.connect(f"{base}/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')


def main() -> None:
    from app.core.entorno import cargar_env
    cargar_env()
    url = os.environ["DATABASE_URL"]
    if "PEGAR_ACA" in url:
        sys.exit("Falta la contraseña de la base en .env (línea DATABASE_URL).")
    if "--recrear" in sys.argv:
        # borra la base entera: solo para bases locales de desarrollo, nunca Supabase ni otro servidor
        host = url.split("@")[-1].split("/")[0].split(":")[0]
        if host not in ("127.0.0.1", "localhost", "::1"):
            sys.exit(f"--recrear solo se permite con una base local (esta es {host}).")
        recrear_base(url)
    with psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=15) as conn:
        print("migraciones aplicadas:", aplicar_migraciones(conn) or "ninguna (al día)")
        print("maestros globales:", cargar_seeds(conn))


if __name__ == "__main__":
    main()
