"""Motor de reglas de clasificación por palabra clave.

Misma semántica que M_Reglas de la planilla (gana la primera regla que coincide, con filtros
opcionales por cuenta y por tipo), con dos mejoras:
  * no distingue mayúsculas NI acentos ('DEVOLUCIÓN' = 'devolucion');
  * las reglas propias del cliente se evalúan antes que las globales del sistema.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.ingesta.modelos import Alerta, MovimientoPropuesto, Pata, Regla


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos.upper()).strip()


PALABRA_CORTA = 4    # hasta este largo, la clave tiene que ser palabra completa


def coincide(clave: str, descripcion: str) -> bool:
    """`clave` y `descripcion` ya normalizadas. Las claves cortas (ART, IVA, ABL, OSDE…) tienen que aparecer
    como palabra completa: si no, "ART" coincide dentro de MARTINEZ o BARTOLOME y clasifica una transferencia
    a una persona como pago de ART. Las largas siguen siendo "contiene" (como en la planilla)."""
    if not clave:
        return False
    if len(clave) <= PALABRA_CORTA and clave.isalnum():
        return re.search(rf"(?<![A-Z0-9]){re.escape(clave)}(?![A-Z0-9])", descripcion) is not None
    return clave in descripcion


class MotorReglas:
    def __init__(self, reglas: Iterable[Regla]):
        # cliente primero, después prioridad ascendente; se precalcula el texto normalizado
        self._reglas = sorted(reglas, key=lambda r: (r.cliente_id is None, r.prioridad))
        self._claves = [normalizar(r.texto) for r in self._reglas]

    def buscar(self, descripcion: str, tipo: str, cuenta: str) -> Regla | None:
        desc = normalizar(descripcion)
        for regla, clave in zip(self._reglas, self._claves):
            if not coincide(clave, desc):
                continue
            if regla.tipo and regla.tipo != tipo:
                continue
            if regla.cuenta and regla.cuenta != cuenta:
                continue
            return regla
        return None

    def clasificar(self, mov: MovimientoPropuesto, rubros_validos: set[str]) -> MovimientoPropuesto:
        """Asigna rubro, tercero, UN y medio a la pata principal, y recalcula sus alertas de clasificación.
        Las patas de comisión e impuestos ya traen el rubro del perfil."""
        if mov.pata is Pata.PRINCIPAL and not mov.regla_id and not mov.rubro:
            regla = self.buscar(mov.descripcion, mov.tipo, mov.cuenta)
            if regla:
                mov.rubro = regla.rubro
                mov.tercero = mov.tercero or regla.tercero
                mov.unidad_negocio = mov.unidad_negocio or regla.unidad_negocio
                mov.medio_pago = regla.medio_pago or mov.medio_pago
                mov.regla_id = regla.id
                mov.regla_texto = f'contiene "{regla.texto}"'
        mov.alertas = [a for a in mov.alertas if a not in (Alerta.SIN_REGLA, Alerta.RUBRO_INEXISTENTE)]
        if not mov.rubro:
            mov.alertas.append(Alerta.SIN_REGLA)
        elif mov.rubro not in rubros_validos:
            mov.alertas.append(Alerta.RUBRO_INEXISTENTE)
        return mov
