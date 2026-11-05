"""Tablero ejecutivo (hoja Tablero de la planilla): KPIs del mes vs mes anterior, presupuesto y meta.

Todo lo que se puede calcular sale de los registros; lo que no (stock, bienes de uso, deudas financieras y
fiscales) se carga una vez por mes en los datos de cierre (Balance_Gestion).
Deudores y proveedores pendientes: comprobantes menos cobros/pagos, imputados FIFO (a la factura más vieja).
"""
from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.core.numeros import div_segura
from app.finanzas.kpis import BalanceMes, Pendiente, capital_de_trabajo, dupont

CERO = Decimal(0)


def fin_de_mes(mes: date) -> date:
    return mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])


def mes_anterior(mes: date) -> date:
    return (mes.replace(day=1) - timedelta(days=1)).replace(day=1)


@dataclass
class DatosCierre:
    """Saldos de fin de mes que no salen de los registros (en ARS)."""
    mes: date
    stock: Decimal = CERO
    bienes_uso: Decimal = CERO
    otros_activos: Decimal = CERO
    deudas_financieras: Decimal = CERO
    deudas_fiscales: Decimal = CERO
    otros_pasivos: Decimal = CERO
    amortizacion_mes: Decimal = CERO


@dataclass
class Documento:
    """Factura (emitida o recibida) para saldos y vencimientos."""
    fecha: date
    total_ars: Decimal


def pendientes_fifo(documentos: Iterable[Documento], pagos_hasta: Decimal, plazo_dias: int, hasta: date) -> list[Pendiente]:
    """Saldo de cada factura emitida hasta `hasta`, aplicando lo cobrado (o pagado) a las más viejas primero."""
    restante = pagos_hasta
    salida = []
    for d in sorted((d for d in documentos if d.fecha <= hasta), key=lambda d: d.fecha):
        aplicado = min(restante, d.total_ars) if d.total_ars > 0 else CERO
        restante -= aplicado
        saldo = d.total_ars - aplicado
        if saldo > 0:
            salida.append(Pendiente(d.fecha + timedelta(days=plazo_dias), saldo))
    return salida


# ------------------------------------------------------------------ metas por defecto (planilla)
# clave: (nombre, sección, formato, meta, dirección)  — formato: ars | pct | dias | x | num
KPIS: dict[str, tuple[str, str, str, Decimal | None, str]] = {
    "ingresos_netos": ("Ingresos netos", "Resultados", "ars", None, "≥"),
    "margen_contribucion_pct": ("Margen de contribución", "Resultados", "pct", Decimal("0.40"), "≥"),
    "ebitda": ("EBITDA", "Resultados", "ars", Decimal(0), "≥"),
    "ebitda_pct": ("EBITDA %", "Resultados", "pct", Decimal("0.12"), "≥"),
    "resultado_neto": ("Resultado neto", "Resultados", "ars", Decimal(0), "≥"),
    "prime_cost_pct": ("Prime cost", "Resultados", "pct", Decimal("0.60"), "≤"),
    "material_cost_pct": ("Material cost", "Resultados", "pct", Decimal("0.35"), "≤"),
    "people_cost_pct": ("People cost", "Resultados", "pct", Decimal("0.30"), "≤"),
    "mermas_pct": ("Mermas sobre ingresos", "Resultados", "pct", Decimal("0.02"), "≤"),
    "disponibilidades": ("Disponibilidades a fin de mes", "Caja", "ars", None, "≥"),
    "flujo_operativo": ("Flujo de caja operativo", "Caja", "ars", Decimal(0), "≥"),
    "saldo_90_dias": ("Saldo proyectado a 90 días", "Caja", "ars", Decimal(0), "≥"),
    "deudores": ("Deudores por ventas", "Capital de trabajo", "ars", None, "≤"),
    "proveedores": ("Proveedores", "Capital de trabajo", "ars", None, "≤"),
    "nof": ("NOF operativa", "Capital de trabajo", "ars", None, "≤"),
    "dias_cobro": ("Días de cobro", "Capital de trabajo", "dias", Decimal(30), "≤"),
    "dias_pago": ("Días de pago", "Capital de trabajo", "dias", Decimal(30), "≥"),
    "dias_stock": ("Días de stock", "Capital de trabajo", "dias", Decimal(45), "≤"),
    "pmm_ciclo_caja": ("Ciclo de caja (PMM)", "Capital de trabajo", "dias", Decimal(45), "≤"),
    "liquidez_corriente": ("Liquidez corriente", "Solvencia y Dupont", "x", Decimal("1.2"), "≥"),
    "prueba_acida": ("Prueba ácida", "Solvencia y Dupont", "x", Decimal(1), "≥"),
    "endeudamiento": ("Endeudamiento (pasivo / PN)", "Solvencia y Dupont", "x", Decimal("1.5"), "≤"),
    "margen_neto": ("Margen neto", "Solvencia y Dupont", "pct", None, "≥"),
    "rotacion_activos": ("Rotación de activos (anual)", "Solvencia y Dupont", "x", None, "≥"),
    "apalancamiento": ("Apalancamiento (activo / PN)", "Solvencia y Dupont", "x", None, "≤"),
    "roe_anualizado": ("ROE anualizado (Dupont)", "Solvencia y Dupont", "pct", None, "≥"),
    "dotacion": ("Dotación (F.931)", "Productividad", "num", None, "≥"),
    "ingresos_por_persona": ("Ingresos por persona", "Productividad", "ars", None, "≥"),
}
SECCIONES = ["Resultados", "Caja", "Capital de trabajo", "Solvencia y Dupont", "Productividad"]


def semaforo_meta(valor: Decimal | None, meta: Decimal | None, direccion: str) -> str | None:
    """🟢 cumple · 🟡 dentro del 10 % de la meta · 🔴 fuera (misma regla que la hoja Tablero)."""
    if valor is None or meta is None:
        return None
    margen = abs(meta) * Decimal("0.1")
    if direccion == "≥":
        return "verde" if valor >= meta else ("amarillo" if valor >= meta - margen else "rojo")
    return "verde" if valor <= meta else ("amarillo" if valor <= meta + margen else "rojo")


@dataclass
class EntradaMes:
    """Todo lo necesario para los KPIs de un mes, ya calculado por la capa de datos."""
    pyl: dict[str, Decimal | None]               # filas de pyl_mensual para el mes
    disponibilidades: Decimal
    flujo_operativo: Decimal
    deudores: Decimal
    proveedores: Decimal
    remuneraciones_a_pagar: Decimal
    ventas_con_iva: Decimal
    compras_con_iva: Decimal
    cmv: Decimal
    mermas: Decimal
    dotacion: int | None
    cierre: DatosCierre | None
    saldo_90_dias: Decimal | None = None


def kpis_del_mes(e: EntradaMes) -> dict[str, Decimal | None]:
    c = e.cierre or DatosCierre(mes=date.min)
    b = BalanceMes(disponibilidades=e.disponibilidades, deudores=e.deudores, stock=c.stock, otros_activos=c.otros_activos,
                   bienes_uso=c.bienes_uso, proveedores=e.proveedores, remuneraciones_a_pagar=e.remuneraciones_a_pagar,
                   deudas_fiscales=c.deudas_fiscales, deudas_financieras=c.deudas_financieras, otros_pasivos=c.otros_pasivos,
                   ventas_con_iva_mes=e.ventas_con_iva, compras_con_iva_mes=e.compras_con_iva, cmv_mes=e.cmv)
    k = capital_de_trabajo(b)
    ingresos = e.pyl.get("ingresos_netos") or CERO
    d = dupont(e.pyl.get("resultado_neto") or CERO, ingresos, k["activo_total"], k["patrimonio_neto"])
    sin_stock = e.cierre is None   # sin datos de cierre, los indicadores que dependen del stock no se muestran
    return {
        **{clave: e.pyl.get(clave) for clave in ("ingresos_netos", "margen_contribucion_pct", "ebitda", "ebitda_pct",
                                                 "resultado_neto", "prime_cost_pct", "material_cost_pct", "people_cost_pct")},
        "mermas_pct": div_segura(e.mermas, ingresos),
        "disponibilidades": e.disponibilidades, "flujo_operativo": e.flujo_operativo, "saldo_90_dias": e.saldo_90_dias,
        "deudores": e.deudores, "proveedores": e.proveedores, "nof": k["nof"],
        "dias_cobro": k["dias_cobro"], "dias_pago": k["dias_pago"],
        "dias_stock": None if sin_stock else k["dias_stock"],
        "pmm_ciclo_caja": None if sin_stock else k["pmm_ciclo_caja"],
        "liquidez_corriente": k["liquidez_corriente"], "prueba_acida": None if sin_stock else k["prueba_acida"],
        "endeudamiento": None if sin_stock else k["endeudamiento"],
        "margen_neto": d["margen_neto"],
        **({k_: None for k_ in ("rotacion_activos", "apalancamiento", "roe_anualizado")} if sin_stock else
           {"rotacion_activos": d["rotacion_activos"], "apalancamiento": d["apalancamiento"], "roe_anualizado": d["roe_anualizado"]}),
        "dotacion": Decimal(e.dotacion) if e.dotacion else None,
        "ingresos_por_persona": div_segura(ingresos, Decimal(e.dotacion)) if e.dotacion else None,
    }


@dataclass
class KPI:
    clave: str
    nombre: str
    seccion: str
    formato: str
    valor: Decimal | None
    anterior: Decimal | None
    presupuesto: Decimal | None
    meta: Decimal | None
    direccion: str
    semaforo: str | None = None
    variacion: Decimal | None = field(default=None)


def armar_tablero(actual: dict, anterior: dict, presupuesto: dict[str, Decimal], metas: dict[str, tuple[Decimal | None, str]]) -> list[dict]:
    secciones = []
    for sec in SECCIONES:
        kpis = []
        for clave, (nombre, seccion, formato, meta_def, dir_def) in KPIS.items():
            if seccion != sec:
                continue
            meta, direccion = metas.get(clave, (meta_def, dir_def))
            valor, ant = actual.get(clave), anterior.get(clave)
            if formato in ("pct",):
                variacion = valor - ant if valor is not None and ant is not None else None       # puntos porcentuales
            else:
                variacion = div_segura(valor - ant, abs(ant)) if valor is not None and ant else None
            kpis.append(KPI(clave, nombre, seccion, formato, valor, ant, presupuesto.get(clave), meta, direccion,
                            semaforo_meta(valor, meta, direccion), variacion))
        secciones.append({"titulo": sec, "kpis": kpis})
    return secciones
