"""Almacenamiento de los archivos subidos. La base guarda solo la ruta y la huella; el binario va acá.

    SUPABASE_URL + SUPABASE_SERVICE_KEY definidas → Supabase Storage (bucket privado, por defecto "documentos")
    si no → disco local en STORAGE_DIR (por defecto backend/.storage)

La service key es del backend: nunca se manda al navegador.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import httpx


class Almacenamiento(Protocol):
    def guardar(self, ruta: str, contenido: bytes, tipo: str) -> str: ...
    def leer(self, ruta: str) -> bytes: ...
    def borrar(self, ruta: str) -> None: ...


class AlmacenamientoLocal:
    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def _archivo(self, ruta: str) -> Path:
        destino = (self.raiz / ruta).resolve()
        if self.raiz.resolve() not in destino.parents:
            raise ValueError("Ruta fuera del almacenamiento")
        return destino

    def guardar(self, ruta: str, contenido: bytes, tipo: str) -> str:
        destino = self._archivo(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        return ruta

    def leer(self, ruta: str) -> bytes:
        return self._archivo(ruta).read_bytes()

    def borrar(self, ruta: str) -> None:
        self._archivo(ruta).unlink(missing_ok=True)


class AlmacenamientoSupabase:
    def __init__(self, url: str, service_key: str, bucket: str = "documentos"):
        self.base = f"{url.rstrip('/')}/storage/v1/object/{bucket}"
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def guardar(self, ruta: str, contenido: bytes, tipo: str) -> str:
        r = httpx.post(f"{self.base}/{ruta}", content=contenido, timeout=60,
                       # upsert: la ruta lleva el sha256 del contenido, así que reescribir la misma ruta es reescribir
                       # el mismo archivo (y el chequeo /salud escribe siempre su archivo de prueba)
                       headers={**self.headers, "Content-Type": tipo or "application/octet-stream", "x-upsert": "true"})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Supabase Storage respondió {r.status_code}: {r.text[:200]}")
        return ruta

    def leer(self, ruta: str) -> bytes:
        r = httpx.get(f"{self.base}/{ruta}", headers=self.headers, timeout=60)
        r.raise_for_status()
        return r.content

    def borrar(self, ruta: str) -> None:
        r = httpx.delete(f"{self.base}/{ruta}", headers=self.headers, timeout=60)
        if r.status_code not in (200, 204, 404):
            raise RuntimeError(f"Supabase Storage respondió {r.status_code} al borrar: {r.text[:200]}")


def crear_almacenamiento() -> Almacenamiento:
    url, clave = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if url and clave:
        return AlmacenamientoSupabase(url, clave, os.environ.get("SUPABASE_BUCKET", "documentos"))
    return AlmacenamientoLocal(os.environ.get("STORAGE_DIR", Path(__file__).resolve().parents[1] / ".storage"))
