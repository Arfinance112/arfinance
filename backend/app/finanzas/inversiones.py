"""Inversiones del cliente (FCI, plazos fijos, cauciones, títulos): aportes, rescates y valuaciones.

Resultado de una posición = última valuación + lo rescatado − lo aportado. Sin valuación cargada no se calcula
(se informa lo aportado y rescatado). Cada moneda se calcula por separado, sin convertir.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

INSTRUMENTOS = ("FCI", "Plazo fijo", "Caución", "Acciones", "Bonos", "Cedears", "Otro")
TIPOS = ("aporte", "rescate", "valuacion")
MONEDAS = ("ARS", "USD")
CERO = Decimal(0)


@dataclass
class MovInversion:
    fecha: date
    instrumento: str
    nombre: str
    tipo: str
    importe: Decimal
    moneda: str = "ARS"
    id: str = ""


def posiciones(movs: Iterable[MovInversion]) -> list[dict]:
    pos: dict[tuple, dict] = {}
    for m in sorted(movs, key=lambda m: m.fecha):
        p = pos.setdefault((m.instrumento, m.nombre.strip().upper(), m.moneda), {
            "instrumento": m.instrumento, "nombre": m.nombre.strip(), "moneda": m.moneda, "aportado": CERO,
            "rescatado": CERO, "valuacion": None, "fecha_valuacion": None})
        if m.tipo == "aporte":
            p["aportado"] += m.importe
        elif m.tipo == "rescate":
            p["rescatado"] += m.importe
        else:
            p["valuacion"], p["fecha_valuacion"] = m.importe, m.fecha
    sal = []
    for p in pos.values():
        p["neto_invertido"] = p["aportado"] - p["rescatado"]
        if p["valuacion"] is None:
            p["resultado"] = p["rendimiento"] = None
        else:
            p["resultado"] = p["valuacion"] + p["rescatado"] - p["aportado"]
            p["rendimiento"] = (p["resultado"] / p["aportado"]).quantize(Decimal("0.0001")) if p["aportado"] else None
        sal.append(p)
    return sorted(sal, key=lambda p: (p["moneda"], p["instrumento"], p["nombre"]))
