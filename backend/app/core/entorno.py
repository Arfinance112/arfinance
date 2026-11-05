"""Carga el .env de la raíz del proyecto en los comandos de consola (migrar, verificar, respaldo, worker).

La API no lo carga sola (se arranca con `uvicorn --env-file ../.env`): así importar la app en los tests nunca
apunta a la base real. Lo que ya esté definido en el entorno tiene prioridad sobre el archivo.
"""
from __future__ import annotations

import os
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parents[3] / ".env"


def cargar_env(archivo: Path = ARCHIVO) -> list[str]:
    if not archivo.exists():
        return []
    cargadas = []
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = (p.strip() for p in linea.split("=", 1))
        if clave and clave not in os.environ:
            os.environ[clave] = valor.strip('"').strip("'")
            cargadas.append(clave)
    return cargadas
