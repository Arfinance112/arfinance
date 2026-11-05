"""Capa de normalización: de los registros de origen a ASIENTOS DE GESTIÓN en ARS (devengado).

Fuentes y reglas:
  * Comprobantes emitidos (Mis Comprobantes)  → ingresos, por su neto × tipo de cambio de ARCA.
  * Comprobantes recibidos con rubro          → costos del rubro. Sin rubro no entran: se avisa.
  * F.931                                     → costo laboral devengado (remuneraciones + cargas patronales).
  * Tesorería, rubros que son P&L             → gastos e ingresos "directos" (comisiones, impuestos, etc.),
                                                convertidos con el tipo de cambio del mes de la cuenta.

Regla anti doble conteo: en un mes, si un rubro ya tiene comprobantes recibidos (o F.931 para el personal),
lo que salió por Tesorería con ese mismo rubro NO se suma: es el pago de lo ya devengado. Si no hay
comprobantes, Tesorería es la única fuente y se usa. Así el resultado sirve aunque el cliente todavía no
cargue sus facturas, y no se duplica cuando sí las carga.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.finanzas.indices import TablaIndices
from app.finanzas.kpis import AsientoGestion
from app.ingesta.modelos import MovimientoTesoreria

CERO = Decimal(0)


@dataclass
class ComprobanteRegistrado:
    id: str
    sentido: str                  # emitido | recibido
    fecha: date
    comprobante: str
    cuit: str
    contraparte: str
    neto_ars: Decimal             # con signo: notas de crédito en negativo
    rubro: str | None = None
    total_ars: Decimal = CERO     # con IVA: para deudores, proveedores y días de cobro/pago


@dataclass
class CostoLaboral:
    periodo: date                 # 1° de mes
    remuneraciones: Decimal
    cargas_patronales: Decimal
    empleados: int | None = None


@dataclass
class Avisos:
    compras_sin_rubro: int = 0
    importe_sin_rubro: Decimal = CERO
    meses_sin_ventas: list[date] = field(default_factory=list)
    movimientos_sin_tc: int = 0
    tesoreria_omitida_por_comprobantes: int = 0
    extra: list[str] = field(default_factory=list)

    def lista(self) -> list[str]:
        sal = list(self.extra)
        if self.compras_sin_rubro:
            sal.append(f"{self.compras_sin_rubro} comprobantes recibidos sin rubro (ARS {self.importe_sin_rubro:,.2f}) no entran al resultado: asignales rubro.")
        if self.meses_sin_ventas:
            sal.append("Meses sin comprobantes emitidos cargados: " + ", ".join(m.strftime("%m/%Y") for m in self.meses_sin_ventas) + ". Subí Mis Comprobantes emitidos.")
        if self.movimientos_sin_tc:
            sal.append(f"{self.movimientos_sin_tc} movimientos en moneda extranjera sin tipo de cambio del mes: cargalo en Índices.")
        return sal


def construir_asientos(*, comprobantes: Iterable[ComprobanteRegistrado], tesoreria: Iterable[MovimientoTesoreria],
                       costos_laborales: Iterable[CostoLaboral], rubros: dict[str, dict],
                       cotizacion_por_cuenta: dict[str, str], indices: TablaIndices | None,
                       rubro_ventas: str = "ING01", rubro_personal: str = "PER01") -> tuple[list[AsientoGestion], Avisos]:
    avisos = Avisos()
    asientos: list[AsientoGestion] = []
    cubiertos: set[tuple[date, str]] = set()
    meses_con_ventas: set[date] = set()

    def agregar(mes: date, rubro: str, importe: Decimal, origen: str) -> None:
        r = rubros.get(rubro)
        if not r or r["linea_pl"] == "NO P&L":
            return
        asientos.append(AsientoGestion(mes=mes, rubro=rubro, linea_pl=r["linea_pl"], importe=importe,
                                       grupo_prime=r.get("grupo_prime"), origen=origen))

    for c in comprobantes:
        mes = c.fecha.replace(day=1)
        if c.sentido == "emitido":
            meses_con_ventas.add(mes)
            agregar(mes, c.rubro or rubro_ventas, c.neto_ars, "ventas")
        elif c.rubro:
            cubiertos.add((mes, c.rubro))
            agregar(mes, c.rubro, -c.neto_ars, "compras")
        else:
            avisos.compras_sin_rubro += 1
            avisos.importe_sin_rubro += c.neto_ars

    for cl in costos_laborales:
        cubiertos.add((cl.periodo, rubro_personal))
        agregar(cl.periodo, rubro_personal, -(cl.remuneraciones + cl.cargas_patronales), "personal")

    meses_tesoreria: set[date] = set()
    for m in tesoreria:
        r = rubros.get(m.rubro)
        if not r or r["linea_pl"] == "NO P&L":
            continue
        mes = m.fecha.replace(day=1)
        meses_tesoreria.add(mes)
        if (mes, m.rubro) in cubiertos:
            avisos.tesoreria_omitida_por_comprobantes += 1
            continue
        cot = cotizacion_por_cuenta.get(m.cuenta, "ARS")
        tc = Decimal(1) if cot in ("", "ARS") else (indices.tc(mes, cot) if indices else None)
        if tc is None:
            avisos.movimientos_sin_tc += 1
            continue
        agregar(mes, m.rubro, m.importe_firmado * tc, "tesoreria")

    meses_con_actividad = {a.mes for a in asientos} | meses_tesoreria
    avisos.meses_sin_ventas = sorted(m for m in meses_con_actividad if m not in meses_con_ventas)
    return asientos, avisos
