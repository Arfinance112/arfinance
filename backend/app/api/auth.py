"""Autenticación con Supabase Auth.

El frontend inicia sesión con supabase-js y manda el access token en `Authorization: Bearer <jwt>`.
El backend valida la firma y toma el usuario del claim `sub`. Supabase firma de dos maneras:

  * Claves de firma asimétricas (ES256/RS256), las de los proyectos nuevos: la clave pública se baja de
    SUPABASE_URL/auth/v1/.well-known/jwks.json (se cachea; si Supabase rota la clave, se vuelve a bajar).
  * Secreto compartido HS256 (legacy): SUPABASE_JWT_SECRET (Settings → API → JWT Secret).

Se acepta lo que esté configurado; el algoritmo lo dice el encabezado del token y nunca se acepta "none".
Si no hay ni SUPABASE_URL ni SUPABASE_JWT_SECRET, la API corre en modo desarrollo con un usuario fijo
(nunca usar así en producción: con ENTORNO=produccion no arranca).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

USUARIO_DESARROLLO = "00000000-0000-4000-8000-000000000001"
ALGORITMOS_ASIMETRICOS = ("ES256", "RS256")


@dataclass
class Usuario:
    id: str
    email: str


@lru_cache(maxsize=4)
def _cliente_jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=10)


def _clave_publica(token: str) -> object:
    """Clave pública del proyecto para el `kid` del token (separado para poder reemplazarlo en tests)."""
    return _cliente_jwks(os.environ["SUPABASE_URL"]).get_signing_key_from_jwt(token).key


def _no_autorizado(mensaje: str) -> HTTPException:
    return HTTPException(401, mensaje, headers={"WWW-Authenticate": "Bearer"})


def modo_desarrollo() -> bool:
    return not os.environ.get("SUPABASE_JWT_SECRET") and not os.environ.get("SUPABASE_URL")


def usuario_actual(authorization: str | None = Header(default=None)) -> Usuario:
    if modo_desarrollo():
        return Usuario(USUARIO_DESARROLLO, "desarrollo@local")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _no_autorizado("Falta el token de sesión")
    token = authorization.split(" ", 1)[1].strip()
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg in ALGORITMOS_ASIMETRICOS and os.environ.get("SUPABASE_URL"):
            clave, algoritmos = _clave_publica(token), list(ALGORITMOS_ASIMETRICOS)
        elif alg == "HS256" and os.environ.get("SUPABASE_JWT_SECRET"):
            clave, algoritmos = os.environ["SUPABASE_JWT_SECRET"], ["HS256"]
        else:
            raise _no_autorizado("Token firmado de una forma que este servidor no acepta")
        claims = jwt.decode(token, clave, algorithms=algoritmos, audience="authenticated",
                            options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise _no_autorizado("La sesión expiró: volvé a ingresar")
    except jwt.PyJWKClientError:
        raise HTTPException(503, "No se pudo validar la sesión con Supabase: intentá de nuevo en un momento")
    except jwt.InvalidTokenError:
        raise _no_autorizado("Token inválido")
    if not claims.get("sub"):
        raise _no_autorizado("Token sin usuario")
    return Usuario(claims["sub"], claims.get("email", ""))


def es_admin_plataforma(u: Usuario) -> bool:
    """Quien opera la plataforma (no un estudio): puede cambiar datos globales como índices y tipos de cambio.
    ADMINS_PLATAFORMA = emails o ids separados por coma. En modo desarrollo, el usuario fijo lo es."""
    if modo_desarrollo():
        return True
    admins = {x.strip().lower() for x in os.environ.get("ADMINS_PLATAFORMA", "").split(",") if x.strip()}
    return u.id.lower() in admins or (bool(u.email) and u.email.lower() in admins)


def verificar_configuracion() -> list[str]:
    """Con ENTORNO=produccion la API no arranca con configuración insegura; en otro entorno, solo avisa."""
    problemas = []
    if modo_desarrollo():
        problemas.append("Ni SUPABASE_URL ni SUPABASE_JWT_SECRET: modo desarrollo, cualquiera entra como el mismo usuario")
    if "*" in os.environ.get("CORS_ORIGENES", ""):
        problemas.append("CORS_ORIGENES con '*': cualquier sitio puede llamar a la API")
    if not os.environ.get("METRICAS_TOKEN"):
        problemas.append("METRICAS_TOKEN no definido: /metricas es público")
    if not os.environ.get("DATABASE_URL"):
        problemas.append("DATABASE_URL no definido: los datos están en memoria y se pierden al reiniciar")
    if os.environ.get("ENTORNO") == "produccion" and problemas:
        raise RuntimeError("Configuración insegura para producción: " + "; ".join(problemas))
    return problemas
