"""Respaldo y restauración de la base, con verificación.

    python -m app.db.respaldo respaldar  --destino respaldos/          # pg_dump -Fc + manifiesto con conteos
    python -m app.db.respaldo restaurar  --archivo X.dump --url URL    # base NUEVA; compara conteos con el manifiesto
    python -m app.db.respaldo verificar  --destino respaldos/          # respalda, restaura en <base>_verificacion,
                                                                       # compara y borra la copia (para correr cada día)
La base de origen sale de DATABASE_URL. Se respalda el esquema public (auth lo administra Supabase).
Se conservan los últimos RESPALDOS_A_CONSERVAR (14 por defecto). Los binarios se buscan en PG_BIN, el PATH o .pgenv.
Un respaldo que no se restauró nunca no es un respaldo: por eso `verificar` es el que se programa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from app.db.migrar import RAIZ, STUB_AUTH, recrear_base


def _binario(nombre: str) -> str:
    candidatos = [Path(os.environ["PG_BIN"]) / f"{nombre}.exe" if os.environ.get("PG_BIN") else None,
                  shutil.which(nombre),
                  RAIZ / ".pgenv" / "Lib" / "site-packages" / "pgserver" / "pginstall" / "bin" / f"{nombre}.exe"]
    for c in candidatos:
        if c and Path(c).exists():
            return str(c)
    raise SystemExit(f"No encuentro {nombre}: instalá el cliente de PostgreSQL o definí PG_BIN.")


def _sin_parametros(url: str) -> str:
    return url.split("?", 1)[0]


def conteos(url: str) -> dict[str, int]:
    with psycopg.connect(url) as con:
        tablas = [f[0] for f in con.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
        return {t: con.execute(f'SELECT count(*) FROM public."{t}"').fetchone()[0] for t in tablas}


def respaldar(url: str, destino: Path, conservar: int = 14) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"gestion_{datetime.now():%Y%m%d_%H%M%S}.dump"
    subprocess.run([_binario("pg_dump"), "--format=custom", "--schema=public", "--no-owner", "--no-privileges",
                    f"--file={archivo}", f"--dbname={url}"], check=True)
    sha = hashlib.sha256(archivo.read_bytes()).hexdigest()
    manifiesto = {"archivo": archivo.name, "sha256": sha, "creado": datetime.now().isoformat(timespec="seconds"),
                  "bytes": archivo.stat().st_size, "conteos": conteos(url)}
    archivo.with_suffix(".json").write_text(json.dumps(manifiesto, indent=2), encoding="utf-8")
    for viejo in sorted(destino.glob("gestion_*.dump"))[:-conservar]:
        viejo.unlink()
        viejo.with_suffix(".json").unlink(missing_ok=True)
    return archivo


def restaurar(archivo: Path, url_destino: str) -> dict[str, tuple[int, int]]:
    """Restaura en una base que se crea de cero. Devuelve las tablas cuyo conteo difiere (vacío = OK)."""
    manifiesto = json.loads(archivo.with_suffix(".json").read_text(encoding="utf-8"))
    if hashlib.sha256(archivo.read_bytes()).hexdigest() != manifiesto["sha256"]:
        raise SystemExit(f"{archivo.name}: el hash no coincide con el manifiesto (archivo dañado o alterado).")
    recrear_base(_sin_parametros(url_destino))
    with psycopg.connect(url_destino, autocommit=True) as con:
        if not con.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'auth'").fetchone():
            con.execute(STUB_AUTH)
        con.execute("DROP SCHEMA IF EXISTS public CASCADE")   # pg_restore la recrea tal cual estaba
    subprocess.run([_binario("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error",
                    f"--dbname={url_destino}", str(archivo)], check=True)
    reales = conteos(url_destino)
    esperados = manifiesto["conteos"]
    return {t: (esperados.get(t, -1), reales.get(t, -1)) for t in set(esperados) | set(reales)
            if esperados.get(t) != reales.get(t)}


def verificar(url: str, destino: Path) -> int:
    archivo = respaldar(url, destino)
    base, nombre = _sin_parametros(url).rsplit("/", 1)
    copia = f"{base}/{nombre}_verificacion"
    try:
        diferencias = restaurar(archivo, copia)
    finally:
        with psycopg.connect(f"{base}/postgres", autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{nombre}_verificacion" WITH (FORCE)')
    if diferencias:
        print(f"FALLÓ la verificación de {archivo.name}: {diferencias}")
        return 1
    m = json.loads(archivo.with_suffix(".json").read_text(encoding="utf-8"))
    print(f"OK {archivo.name}: {m['bytes']:,} bytes, {len(m['conteos'])} tablas, {sum(m['conteos'].values()):,} filas restauradas idénticas")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=["respaldar", "restaurar", "verificar"])
    p.add_argument("--destino", type=Path, default=RAIZ / "respaldos")
    p.add_argument("--archivo", type=Path)
    p.add_argument("--url", help="base destino de la restauración (se BORRA y se crea de cero)")
    a = p.parse_args()
    origen = os.environ.get("DATABASE_URL", "")
    if a.accion == "respaldar":
        print(respaldar(origen, a.destino, int(os.environ.get("RESPALDOS_A_CONSERVAR", "14"))))
        return 0
    if a.accion == "verificar":
        return verificar(origen, a.destino)
    if not a.archivo or not a.url:
        p.error("restaurar necesita --archivo y --url")
    if _sin_parametros(a.url) == _sin_parametros(origen):
        p.error("La base destino es la misma que DATABASE_URL: restaurá en otra y después cambiá la conexión.")
    dif = restaurar(a.archivo, a.url)
    print("Restauración OK" if not dif else f"Conteos distintos: {dif}")
    return 1 if dif else 0


if __name__ == "__main__":
    sys.exit(main())
