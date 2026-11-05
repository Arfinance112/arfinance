"""Chequeo de la conexión con Supabase, punto por punto y con la solución de cada problema.

    python -m app.db.verificar_supabase          # lee las variables de entorno y frontend/.env.local

Nunca muestra valores secretos: solo si están, de qué tipo son y si funcionan. Sale con código 1 si algo falla.
"""
from __future__ import annotations

import json
import os
import re
import sys
from base64 import urlsafe_b64decode
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.db.migrar import MIGRACIONES, RAIZ

OK, AVISO, ERROR = "✔", "⚠", "✘"


class Informe:
    def __init__(self) -> None:
        self.lineas: list[tuple[str, str, str]] = []

    def __call__(self, estado: str, que: str, como: str = "") -> None:
        self.lineas.append((estado, que, como))

    @property
    def errores(self) -> int:
        return sum(1 for e, _, _ in self.lineas if e == ERROR)

    def texto(self) -> str:
        sal = []
        for e, q, c in self.lineas:
            sal.append(f"{e} {q}")
            if c and e != OK:
                sal.append(f"    → {c}")
        total = self.errores
        sal.append("")
        sal.append("Todo listo para usar Supabase." if not total else f"{total} problema(s) para resolver antes de conectar.")
        return "\n".join(sal)


def tipo_de_clave(clave: str) -> str:
    """publica | secreta | desconocida. Claves nuevas (sb_publishable_/sb_secret_) o legacy (JWT con claim role)."""
    if clave.startswith("sb_publishable_"):
        return "publica"
    if clave.startswith("sb_secret_"):
        return "secreta"
    partes = clave.split(".")
    if len(partes) == 3:
        try:
            datos = json.loads(urlsafe_b64decode(partes[1] + "=" * (-len(partes[1]) % 4)))
            return {"anon": "publica", "service_role": "secreta"}.get(datos.get("role"), "desconocida")
        except ValueError:
            pass
    return "desconocida"


def _env_frontend() -> dict[str, str]:
    archivo = RAIZ / "frontend" / ".env.local"
    if not archivo.exists():
        return {}
    pares = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", linea)
        if m and not linea.lstrip().startswith("#"):
            pares[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return pares


def verificar(env: dict[str, str] | None = None, frontend: dict[str, str] | None = None) -> Informe:
    env = dict(os.environ) if env is None else env
    frontend = _env_frontend() if frontend is None else frontend
    inf = Informe()
    url, servicio, db = env.get("SUPABASE_URL", ""), env.get("SUPABASE_SERVICE_KEY", ""), env.get("DATABASE_URL", "")

    # ------------------------------------------------------------ variables y claves
    ref = ""
    if not url:
        inf(ERROR, "SUPABASE_URL no está definida", "Supabase → Project Settings → API → Project URL (https://<ref>.supabase.co)")
    elif not re.match(r"^https://[a-z0-9]+\.supabase\.co/?$", url):
        inf(AVISO, f"SUPABASE_URL no tiene la forma habitual: {url}", "Debería ser https://<ref>.supabase.co, sin /rest/v1 al final")
    else:
        ref = urlparse(url).hostname.split(".")[0]
        inf(OK, f"SUPABASE_URL del proyecto {ref}")

    if not servicio:
        inf(ERROR, "SUPABASE_SERVICE_KEY no está definida", "Project Settings → API Keys → secret key (o service_role en Legacy API Keys)")
    elif tipo_de_clave(servicio) == "publica":
        inf(ERROR, "SUPABASE_SERVICE_KEY es la clave PÚBLICA (anon/publishable)", "El backend necesita la clave secreta: sb_secret_… o service_role")
    else:
        inf(OK, "SUPABASE_SERVICE_KEY es una clave secreta")

    clave_front = frontend.get("VITE_SUPABASE_ANON_KEY", "")
    if not frontend.get("VITE_SUPABASE_URL") or not clave_front:
        inf(ERROR, "frontend/.env.local sin VITE_SUPABASE_URL o VITE_SUPABASE_ANON_KEY",
            "Copiá frontend/.env.example a frontend/.env.local y completá URL y clave publishable (o anon)")
    elif tipo_de_clave(clave_front) == "secreta":
        inf(ERROR, "¡VITE_SUPABASE_ANON_KEY es la clave SECRETA! Quedaría publicada en el navegador con acceso total",
            "Usá la publishable/anon. Si ya la publicaste, rotá la secreta en Project Settings → API Keys")
    elif frontend.get("VITE_SUPABASE_URL", "").rstrip("/") != url.rstrip("/"):
        inf(ERROR, "El frontend y el backend apuntan a proyectos de Supabase distintos", "VITE_SUPABASE_URL tiene que ser igual a SUPABASE_URL")
    else:
        inf(OK, "Frontend configurado con la clave pública del mismo proyecto")

    # ------------------------------------------------------------ claves de firma de la sesión
    if url:
        try:
            jwks = httpx.get(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json", timeout=10).json().get("keys", [])
        except (httpx.HTTPError, ValueError):
            jwks = None
        if jwks is None:
            inf(ERROR, "No se pudo leer el JWKS del proyecto", "Revisá SUPABASE_URL y la conexión a internet")
        elif jwks:
            algs = sorted({k.get("alg", "?") for k in jwks})
            inf(OK, f"Sesiones firmadas con claves asimétricas ({', '.join(algs)}): no hace falta SUPABASE_JWT_SECRET")
        elif env.get("SUPABASE_JWT_SECRET"):
            inf(OK, "Sesiones firmadas con el secreto HS256 (SUPABASE_JWT_SECRET definido)")
        else:
            inf(ERROR, "El proyecto firma con secreto HS256 y SUPABASE_JWT_SECRET no está definido",
                "Project Settings → JWT Keys → Legacy JWT Secret, o migrá a claves de firma asimétricas")

    # ------------------------------------------------------------ base de datos
    if not db:
        inf(ERROR, "DATABASE_URL no está definida", "Project Settings → Database → Connection string → Session pooler")
    else:
        host = urlparse(db.replace("postgresql+psycopg", "postgresql")).hostname or ""
        if host.startswith("db.") and host.endswith(".supabase.co"):
            inf(AVISO, "DATABASE_URL usa la conexión directa (solo IPv6: muchas redes de Argentina no llegan)",
                "Usá la del Session pooler: …pooler.supabase.com:5432 (usuario postgres.<ref>)")
        if ref and ref not in db:
            inf(ERROR, "DATABASE_URL no es del mismo proyecto que SUPABASE_URL", f"Tiene que contener «{ref}»")
        _verificar_base(inf, db)

    # ------------------------------------------------------------ storage (ida y vuelta real)
    if url and servicio and tipo_de_clave(servicio) != "publica":
        base = f"{url.rstrip('/')}/storage/v1/object/{env.get('SUPABASE_BUCKET', 'documentos')}/_verificacion/ping.txt"
        h = {"Authorization": f"Bearer {servicio}", "apikey": servicio}
        try:
            subida = httpx.post(base, content=b"ok", headers={**h, "Content-Type": "text/plain", "x-upsert": "true"}, timeout=20)
            bajada = httpx.get(base, headers=h, timeout=20)
            httpx.delete(base, headers=h, timeout=20)
            publico = httpx.get(base.replace("/object/", "/object/public/"), timeout=20)
            if subida.status_code in (200, 201) and bajada.content == b"ok":
                inf(OK, "Storage: se pudo guardar, leer y borrar un archivo de prueba")
            else:
                inf(ERROR, f"Storage respondió {subida.status_code}/{bajada.status_code}",
                    "¿Está creado el bucket «documentos»? Corré python -m app.db.migrar (lo crea la migración 0007)")
            if publico.status_code == 200:
                inf(ERROR, "El bucket es PÚBLICO: cualquiera con el enlace ve los extractos", "Storage → bucket documentos → hacelo privado")
        except httpx.HTTPError as e:
            inf(ERROR, f"Storage no responde ({type(e).__name__})", "Revisá SUPABASE_URL")
    return inf


def _verificar_base(inf: Informe, db: str) -> None:
    import psycopg
    try:
        con = psycopg.connect(db, connect_timeout=10, prepare_threshold=None)
    except psycopg.OperationalError as e:
        msg = str(e).lower()
        if "password" in msg:
            inf(ERROR, "La base rechazó la contraseña", "Project Settings → Database → Reset database password, y actualizá DATABASE_URL")
        elif "tenant or user not found" in msg:
            inf(ERROR, "El pooler no reconoce el usuario", "En el pooler el usuario es postgres.<ref>, no solo postgres")
        else:
            inf(ERROR, "No se pudo conectar a la base", "Revisá host, puerto y que el proyecto no esté pausado (los gratuitos se pausan tras 7 días sin uso)")
        return
    with con:
        version = con.execute("SHOW server_version").fetchone()[0]
        inf(OK, f"Conexión a PostgreSQL {version}")
        if not con.execute("SELECT 1 FROM pg_tables WHERE schemaname = 'auth' AND tablename = 'users'").fetchone():
            inf(AVISO, "La base no tiene auth.users: no parece un proyecto de Supabase")
        hechas = set()
        if con.execute("SELECT 1 FROM pg_tables WHERE tablename = 'schema_migraciones'").fetchone():
            hechas = {r[0] for r in con.execute("SELECT version FROM schema_migraciones")}
        faltan = [a.stem for a in sorted(MIGRACIONES.glob("*.sql")) if a.stem not in hechas]
        if faltan:
            inf(ERROR, f"Faltan {len(faltan)} migraciones ({faltan[0]}…)", "Corré: python -m app.db.migrar")
        else:
            inf(OK, "Esquema al día (todas las migraciones aplicadas)")
            sin_rls = [r[0] for r in con.execute(
                """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity ORDER BY 1""")]
            if sin_rls:
                inf(ERROR, f"Tablas sin RLS: {', '.join(sin_rls[:6])}{'…' if len(sin_rls) > 6 else ''}",
                    "Supabase las publica por su API REST y la clave pública está en el navegador: activá RLS "
                    "(ALTER TABLE … ENABLE ROW LEVEL SECURITY) en una migración nueva")
            else:
                inf(OK, "RLS activo en todas las tablas (la API REST de Supabase no expone datos ajenos)")
        bucket = con.execute("SELECT public FROM storage.buckets WHERE id = 'documentos'").fetchone() \
            if con.execute("SELECT 1 FROM pg_tables WHERE schemaname = 'storage' AND tablename = 'buckets'").fetchone() else None
        if bucket is None:
            inf(ERROR, "No existe el bucket «documentos»", "Corré python -m app.db.migrar (migración 0007)")
        elif bucket[0]:
            inf(ERROR, "El bucket «documentos» es público", "Hacelo privado en Storage")
        else:
            inf(OK, "Bucket «documentos» privado")


def main() -> int:
    from app.core.entorno import cargar_env
    cargar_env()
    if "PEGAR_ACA" in os.environ.get("SUPABASE_SERVICE_KEY", "") + os.environ.get("DATABASE_URL", ""):
        print(f"{ERROR} Faltan datos en .env: reemplazá las líneas PEGAR_ACA_… por la clave secreta y la contraseña de la base")
        return 1
    inf = verificar()
    print(inf.texto())
    return 1 if inf.errores else 0


if __name__ == "__main__":
    sys.exit(main())
