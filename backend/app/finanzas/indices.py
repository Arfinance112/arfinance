"""Índices y tipos de cambio mensuales (hoja Indices de la planilla)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

UNO = Decimal(1)


@dataclass
class FilaIndice:
    mes: date
    ipc: Decimal | None = None          # variación mensual (0.021 = 2,1 %)
    cct: Decimal | None = None
    tarifa: Decimal | None = None
    tc: dict[str, Decimal] = field(default_factory=dict)   # {"USD_OFICIAL": 1685, "USD_MEP": 1736, ...}


class TablaIndices:
    def __init__(self, filas: list[FilaIndice]):
        self.filas = sorted(filas, key=lambda f: f.mes)
        if not self.filas:
            raise ValueError("La tabla de índices está vacía")
        self.inicio = self.filas[0].mes

    def tc(self, mes: date, cotizacion: str | None) -> Decimal | None:
        """Tipo de cambio del mes. Si el mes no tiene dato, se arrastra el último cargado
        (misma regla que la planilla). ARS o vacío → 1. Sin ningún dato previo → None."""
        if not cotizacion or cotizacion == "ARS":
            return UNO
        valor = None
        for f in self.filas:
            if f.mes > mes:
                break
            valor = f.tc.get(cotizacion) or valor
        return valor

    def factor(self, indice: str, mes: date) -> Decimal:
        """Precio del mes relativo al mes de inicio (= 1). IPC / CCT / TARIFA acumulan la variación
        mensual; USD sigue al dólar MEP; FIJO no ajusta."""
        if indice == "FIJO" or mes <= self.inicio:
            return UNO
        if indice == "USD":
            base, actual = self.tc(self.inicio, "USD_MEP"), self.tc(mes, "USD_MEP")
            return actual / base if base and actual else UNO
        atributo = {"IPC": "ipc", "CCT": "cct", "TARIFA": "tarifa"}[indice]
        f_acum = UNO
        for f in self.filas[1:]:
            if f.mes > mes:
                break
            f_acum *= UNO + (getattr(f, atributo) or 0)
        return f_acum

    def coeficiente_axi(self, mes_origen: date, mes_cierre: date, indice: str = "IPC") -> Decimal:
        """Coeficiente de ajuste por inflación al cierre: Índice(cierre) / Índice(mes de origen)."""
        return self.factor(indice, mes_cierre) / self.factor(indice, mes_origen)
