"""Detección de duplicados contra lo ya cargado en Tesorería.

Mejora sobre la planilla (que marcaba por cuenta + fecha + importe + tipo con un simple CONTAR.SI):
  1. Si el movimiento trae referencia y ya existe esa referencia en la cuenta con el mismo importe
     → DUPLICADO_EXACTO (se omite siempre).
  2. Si no, se compara por cuenta + fecha + tipo + importe como MULTICONJUNTO: dos comisiones
     iguales el mismo día son dos movimientos legítimos; si Tesorería ya tiene una, solo una
     de las nuevas se marca como POSIBLE_DUPLICADO.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from decimal import Decimal

from app.ingesta.modelos import Alerta, MovimientoPropuesto, MovimientoTesoreria


def _clave(cuenta: str, fecha, tipo: str, importe: Decimal) -> tuple:
    return (cuenta, fecha, tipo, round(importe, 2))


def marcar_duplicados(nuevos: list[MovimientoPropuesto], existentes: Iterable[MovimientoTesoreria]) -> None:
    existentes = list(existentes)
    refs = {(e.cuenta, e.referencia, round(e.importe, 2)) for e in existentes if e.referencia}
    disponibles = Counter(_clave(e.cuenta, e.fecha, e.tipo, e.importe) for e in existentes)
    for mov in nuevos:
        mov.alertas = [a for a in mov.alertas if a not in (Alerta.DUPLICADO_EXACTO, Alerta.POSIBLE_DUPLICADO)]
        if mov.referencia and (mov.cuenta, mov.referencia, round(mov.importe, 2)) in refs:
            mov.alertas.append(Alerta.DUPLICADO_EXACTO)
            continue
        clave = _clave(mov.cuenta, mov.fecha, mov.tipo, mov.importe)
        if disponibles[clave] > 0:
            disponibles[clave] -= 1
            mov.alertas.append(Alerta.POSIBLE_DUPLICADO)
