"""Alta de usuarios por email con Supabase Auth (API de administración, con la service key del backend).

Supabase crea el usuario y le manda un mail con un enlace de un solo uso; al abrirlo, la app le pide elegir
contraseña (pantalla ElegirClave). Si el email ya tiene cuenta, no se manda nada: se devuelve su id para sumarlo
a la organización. En modo desarrollo (sin Supabase) se inventa un id: sirve para los tests y la demo local.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import httpx


class InvitacionFallida(Exception):
    pass


@dataclass
class Invitado:
    usuario_id: str
    email: str
    mail_enviado: bool


def _cabeceras() -> tuple[str, dict[str, str]]:
    url, clave = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not clave:
        raise InvitacionFallida("Falta configurar Supabase en el servidor para invitar usuarios.")
    return url.rstrip("/"), {"apikey": clave, "Authorization": f"Bearer {clave}"}


def _buscar(email: str) -> str | None:
    url, h = _cabeceras()
    for pagina in range(1, 21):          # hasta 2.000 usuarios: alcanza de sobra para un estudio
        r = httpx.get(f"{url}/auth/v1/admin/users", headers=h, params={"page": pagina, "per_page": 100}, timeout=20)
        r.raise_for_status()
        usuarios = r.json().get("users", [])
        for u in usuarios:
            if (u.get("email") or "").lower() == email:
                return u["id"]
        if len(usuarios) < 100:
            return None
    return None


def invitar(email: str) -> Invitado:
    email = email.strip().lower()
    if not os.environ.get("SUPABASE_URL"):
        return Invitado(str(uuid.uuid5(uuid.NAMESPACE_URL, f"mailto:{email}")), email, False)
    url, h = _cabeceras()
    destino = os.environ.get("URL_APP") or os.environ.get("CORS_ORIGENES", "").split(",")[0]
    try:
        r = httpx.post(f"{url}/auth/v1/invite", headers=h, json={"email": email}, timeout=30,
                       params={"redirect_to": destino} if destino else None)
    except httpx.HTTPError as e:
        raise InvitacionFallida(f"Supabase no responde ({type(e).__name__}): intentá de nuevo en un momento.")
    if r.status_code in (200, 201):
        return Invitado(r.json()["id"], email, True)
    texto = r.text.lower()
    if r.status_code in (400, 422) and ("already" in texto or "registered" in texto or "exists" in texto):
        existente = _buscar(email)
        if existente:
            return Invitado(existente, email, False)
    if r.status_code == 429 or "rate limit" in texto:
        raise InvitacionFallida("Supabase alcanzó el límite de mails por hora del plan gratuito: probá más tarde "
                                "o configurá un SMTP propio en Authentication → Emails.")
    raise InvitacionFallida(f"Supabase rechazó la invitación ({r.status_code}).")
