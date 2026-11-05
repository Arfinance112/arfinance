"""Worker de la cola de trabajos.

    python -m app.worker            # producción: proceso aparte, uno o varios (toman con SKIP LOCKED)
    WORKER_EMBEBIDO=1               # desarrollo: un hilo dentro de la API

Errores del archivo (HTTPException: formato, cuenta faltante) → el trabajo queda en "error" con el mensaje,
sin reintentos. Errores inesperados (base caída, almacenamiento) → se reintenta hasta 3 veces.
"""
from __future__ import annotations

import os
import socket
import threading
import time

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.api.repositorio import Repositorio
from app.core.observabilidad import log, metricas
from app.storage import Almacenamiento

NOMBRE = f"{socket.gethostname()}-{os.getpid()}"


def ejecutar_uno(r: Repositorio, alm: Almacenamiento, worker: str = NOMBRE) -> bool:
    """Toma y ejecuta un trabajo. Devuelve False si la cola estaba vacía."""
    from app.api.main import procesar_documento

    t = r.tomar_trabajo(worker)
    if not t:
        return False
    inicio = time.perf_counter()
    try:
        if t.tipo != "procesar_documento":
            raise HTTPException(422, f"Tipo de trabajo desconocido: {t.tipo}")
        p = t.parametros
        contenido = alm.leer(p["ruta"])
        res = procesar_documento(r, t.cliente_id, p["nombre"], contenido, p["sha256"], p["ruta"], p.get("cuenta"),
                                 p.get("perfil"), permitir_ocr=True)
        r.terminar_trabajo(t.id, jsonable_encoder(res), None)
        metricas.contar("trabajo_hecho")
        log.info("trabajo_hecho", extra={"trabajo_id": t.id, "tipo": t.tipo, "ms": round((time.perf_counter() - inicio) * 1000)})
    except HTTPException as e:
        r.terminar_trabajo(t.id, None, str(e.detail))
        metricas.contar("trabajo_rechazado")
        log.warning("trabajo_rechazado", extra={"trabajo_id": t.id, "motivo": str(e.detail)})
    except Exception as e:  # noqa: BLE001 — cualquier otra falla se reintenta
        r.terminar_trabajo(t.id, None, f"Error interno: {type(e).__name__}", reintentar=True)
        metricas.contar("trabajo_fallido")
        log.exception("trabajo_fallido", extra={"trabajo_id": t.id, "intento": t.intentos})
    return True


def bucle(r: Repositorio, alm: Almacenamiento, pausa: float = 1.0, detener: threading.Event | None = None) -> None:
    detener = detener or threading.Event()
    log.info("worker_iniciado", extra={"worker": NOMBRE})
    while not detener.is_set():
        try:
            if not ejecutar_uno(r, alm):
                detener.wait(pausa)
        except Exception:  # noqa: BLE001 — base caída: esperar y seguir
            log.exception("worker_sin_base")
            detener.wait(5)


def iniciar_en_hilo(r: Repositorio, alm: Almacenamiento) -> threading.Event:
    detener = threading.Event()
    threading.Thread(target=bucle, args=(r, alm, 0.5, detener), daemon=True, name="worker").start()
    return detener


if __name__ == "__main__":
    from app.api.main import _almacen, _repo
    bucle(_repo, _almacen)
