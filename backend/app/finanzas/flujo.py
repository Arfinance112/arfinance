"""Cash flow real (método directo) desde Tesorería: la hoja Flujo_Caja de la planilla.

Fase 1b: agrupa por mes y línea de cash flow, en la moneda de cada cuenta (sin convertir). La versión
consolidada en ARS y USD llega con la carga de índices y tipos de cambio (fase 2), sobre la misma función.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from app.ingesta.modelos import MovimientoTesoreria

GRUPOS = {
    "Cobranzas de clientes": "Operativo", "Otros ingresos operativos": "Operativo", "Pagos a proveedores": "Operativo",
    "Sueldos y cargas sociales": "Operativo", "Impuestos y tasas": "Operativo", "Gastos operativos directos": "Operativo",
    "Ingresos y gastos financieros": "Operativo", "Inversiones (CapEx)": "Inversión", "Préstamos recibidos": "Financiación",
    "Cancelación de préstamos": "Financiación", "Aportes de socios": "Financiación", "Retiros / dividendos": "Financiación",
    "Movimientos internos": "Interno", "Sin movimiento de caja": "Interno",
}
ORDEN = list(GRUPOS)


def flujo_mensual(movimientos: Iterable[MovimientoTesoreria], linea_cf_por_rubro: dict[str, str],
                  moneda_por_cuenta: dict[str, str]) -> dict:
    """{moneda: {"meses": [...], "lineas": [{linea, grupo, valores{mes: importe}, total}], "totales": {...}}}"""
    datos: dict[str, dict[str, dict[date, Decimal]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    for m in movimientos:
        moneda = moneda_por_cuenta.get(m.cuenta, "ARS")
        linea = linea_cf_por_rubro.get(m.rubro, "Sin clasificar")
        datos[moneda][linea][m.fecha.replace(day=1)] += m.importe_firmado
    salida = {}
    for moneda, por_linea in datos.items():
        meses = sorted({mes for v in por_linea.values() for mes in v})
        lineas = [{"linea": l, "grupo": GRUPOS.get(l, "Sin clasificar"),
                   "valores": {mes.isoformat(): por_linea[l].get(mes, Decimal(0)) for mes in meses},
                   "total": sum(por_linea[l].values(), Decimal(0))}
                  for l in sorted(por_linea, key=lambda x: ORDEN.index(x) if x in ORDEN else 99)]
        totales = {}
        for grupo in ("Operativo", "Inversión", "Financiación", "Interno"):
            totales[grupo] = {mes.isoformat(): sum((por_linea[l].get(mes, Decimal(0)) for l in por_linea if GRUPOS.get(l) == grupo), Decimal(0))
                              for mes in meses}
        totales["Variación neta"] = {mes.isoformat(): sum((v.get(mes, Decimal(0)) for v in por_linea.values()), Decimal(0)) for mes in meses}
        salida[moneda] = {"meses": [m.isoformat() for m in meses], "lineas": lineas, "totales": totales}
    return salida
