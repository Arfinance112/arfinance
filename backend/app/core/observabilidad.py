"""Logs estructurados (una línea JSON por evento) y métricas en formato Prometheus.

Cada pedido HTTP queda registrado con id, método, ruta (con plantilla, sin ids), estado y duración; el id vuelve
al cliente en el header X-Request-Id para poder buscar un error que reporta un usuario.
No se loguean cuerpos ni nombres de archivo completos fuera de los rechazos (datos del cliente).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")
_CAMPOS_ESTANDAR = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class FormatoJSON(logging.Formatter):
    def format(self, rec: logging.LogRecord) -> str:
        datos = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(rec.created)) + f".{int(rec.msecs):03d}Z",
                 "nivel": rec.levelname.lower(), "evento": rec.getMessage(), "request_id": request_id.get()}
        datos |= {k: v for k, v in vars(rec).items() if k not in _CAMPOS_ESTANDAR}
        if rec.exc_info:
            datos["error"] = self.formatException(rec.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


log = logging.getLogger("gestion")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(FormatoJSON())
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


class Metricas:
    """Contadores e histogramas mínimos, sin dependencias."""
    LIMITES = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pedidos: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duracion: dict[str, list[int]] = defaultdict(lambda: [0] * (len(self.LIMITES) + 1))
        self.suma: dict[str, float] = defaultdict(float)
        self.eventos: dict[str, int] = defaultdict(int)

    def pedido(self, metodo: str, ruta: str, estado: int, segundos: float) -> None:
        with self._lock:
            self.pedidos[(metodo, ruta, estado)] += 1
            cubetas = self.duracion[ruta]
            for i, lim in enumerate(self.LIMITES):
                if segundos <= lim:
                    cubetas[i] += 1
            cubetas[-1] += 1
            self.suma[ruta] += segundos

    def contar(self, evento: str) -> None:
        with self._lock:
            self.eventos[evento] += 1

    def texto(self, cola: dict[str, int]) -> str:
        l = ["# TYPE gestion_pedidos_total counter"]
        l += [f'gestion_pedidos_total{{metodo="{m}",ruta="{r}",estado="{e}"}} {n}' for (m, r, e), n in sorted(self.pedidos.items())]
        l.append("# TYPE gestion_pedido_segundos histogram")
        for ruta, cub in sorted(self.duracion.items()):
            for lim, n in zip(self.LIMITES, cub):
                l.append(f'gestion_pedido_segundos_bucket{{ruta="{ruta}",le="{lim}"}} {n}')
            l.append(f'gestion_pedido_segundos_bucket{{ruta="{ruta}",le="+Inf"}} {cub[-1]}')
            l.append(f'gestion_pedido_segundos_sum{{ruta="{ruta}"}} {self.suma[ruta]:.4f}')
            l.append(f'gestion_pedido_segundos_count{{ruta="{ruta}"}} {cub[-1]}')
        l.append("# TYPE gestion_eventos_total counter")
        l += [f'gestion_eventos_total{{evento="{e}"}} {n}' for e, n in sorted(self.eventos.items())]
        l.append("# TYPE gestion_trabajos gauge")
        l += [f'gestion_trabajos{{estado="{e}"}} {n}' for e, n in sorted(cola.items())]
        return "\n".join(l) + "\n"


metricas = Metricas()


def instalar(app) -> None:
    @app.middleware("http")
    async def registrar(request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        inicio = time.perf_counter()
        estado = 500
        try:
            respuesta = await call_next(request)
            estado = respuesta.status_code
            respuesta.headers["X-Request-Id"] = rid
            return respuesta
        except Exception:
            log.exception("error_no_controlado", extra={"metodo": request.method, "ruta": request.url.path})
            raise
        finally:
            ruta = getattr(request.scope.get("route"), "path", "sin_ruta")
            segundos = time.perf_counter() - inicio
            metricas.pedido(request.method, ruta, estado, segundos)
            if ruta not in ("/salud", "/metricas"):
                log.info("pedido", extra={"metodo": request.method, "ruta": ruta, "estado": estado, "ms": round(segundos * 1000, 1)})
            request_id.reset(token)
