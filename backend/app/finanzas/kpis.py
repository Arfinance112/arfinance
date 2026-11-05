"""Motor de indicadores: P&L de gestión, prime cost, capital de trabajo, Dupont, semáforos,
proyección de caja y suma móvil anual. Port de PyL_Gestion, Balance_Gestion, Control_Ppto,
Flujo_Caja y Tablero de la planilla.

Entrada común: ASIENTOS DE GESTIÓN, la capa de normalización. Cada venta, compra, gasto directo
de tesorería, costo laboral y merma se convierte en una fila con rubro, línea de P&L, grupo de
prime cost, unidad de negocio e importe en ARS con signo (+ ingreso, − costo). En la base de
datos es la vista v_asientos_gestion (ver db/schema.sql).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.numeros import div_segura

CERO = Decimal(0)

LINEAS = ["1 Ventas de bienes", "2 Ventas de servicios", "3 Otros ingresos operativos", "4 Costo variable",
          "5 Personal", "6 Estructura", "7 Comercialización", "8 Impuestos fijos y tasas",
          "9 Resultado financiero", "10 Impuesto a las ganancias"]


@dataclass
class AsientoGestion:
    mes: date
    rubro: str
    linea_pl: str
    importe: Decimal                  # ARS con signo
    grupo_prime: str | None = None    # MATERIALES | PERSONAL | None
    unidad_negocio: str = "GENERAL"
    origen: str = ""                  # ventas | cmv | compras | tesoreria | personal | mermas


def pyl_mensual(asientos: Iterable[AsientoGestion], meses: list[date],
                amortizaciones: dict[date, Decimal] | None = None) -> dict[str, dict[date, Decimal | None]]:
    amortizaciones = amortizaciones or {}
    por_linea: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(lambda: CERO))
    prime: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(lambda: CERO))
    for a in asientos:
        por_linea[a.linea_pl][a.mes] += a.importe
        if a.grupo_prime:
            prime[a.grupo_prime][a.mes] += a.importe
    filas: dict[str, dict[date, Decimal | None]] = {}
    for m in meses:
        L = lambda i: por_linea[LINEAS[i]][m]
        ingresos = L(0) + L(1) + L(2)
        mc = ingresos + L(3)
        ebitda = mc + L(4) + L(5) + L(6) + L(7)
        amort = -abs(amortizaciones.get(m, CERO))
        ebit = ebitda + amort
        bai = ebit + L(8)
        neto = bai + L(9)
        materiales, personal = -prime["MATERIALES"][m], -prime["PERSONAL"][m]
        valores = {
            "ingresos_netos": ingresos, "costo_variable": L(3), "margen_contribucion": mc,
            "margen_contribucion_pct": div_segura(mc, ingresos),
            "personal": L(4), "estructura": L(5), "comercializacion": L(6), "impuestos_fijos": L(7),
            "ebitda": ebitda, "ebitda_pct": div_segura(ebitda, ingresos), "amortizaciones": amort,
            "ebit": ebit, "resultado_financiero": L(8), "bai": bai, "ganancias": L(9),
            "resultado_neto": neto, "resultado_neto_pct": div_segura(neto, ingresos),
            "costo_materiales": materiales, "material_cost_pct": div_segura(materiales, ingresos),
            "costo_personal": personal, "people_cost_pct": div_segura(personal, ingresos),
            "prime_cost": materiales + personal, "prime_cost_pct": div_segura(materiales + personal, ingresos),
        }
        for k, v in valores.items():
            filas.setdefault(k, {})[m] = v
    return filas


def suma_movil_12(serie: dict[date, Decimal]) -> dict[date, Decimal | None]:
    """MAT (Moving Annual Total): suma de los 12 meses que terminan en cada mes; None si faltan meses."""
    meses = sorted(serie)
    salida = {}
    for i, m in enumerate(meses):
        salida[m] = sum((serie[x] for x in meses[i - 11:i + 1]), CERO) if i >= 11 else None
    return salida


@dataclass
class BalanceMes:
    disponibilidades: Decimal
    deudores: Decimal
    stock: Decimal
    otros_activos: Decimal
    bienes_uso: Decimal
    proveedores: Decimal
    remuneraciones_a_pagar: Decimal
    deudas_fiscales: Decimal
    deudas_financieras: Decimal
    otros_pasivos: Decimal
    ventas_con_iva_mes: Decimal
    compras_con_iva_mes: Decimal
    cmv_mes: Decimal


def capital_de_trabajo(b: BalanceMes) -> dict[str, Decimal | None]:
    activo_corriente = b.disponibilidades + b.deudores + b.stock + b.otros_activos
    pasivo_corriente = (b.proveedores + b.remuneraciones_a_pagar + b.deudas_fiscales
                        + b.deudas_financieras + b.otros_pasivos)
    activo_total = activo_corriente + b.bienes_uso
    pn = activo_total - pasivo_corriente
    dias_cobro = div_segura(b.deudores * 30, b.ventas_con_iva_mes)
    dias_pago = div_segura(b.proveedores * 30, b.compras_con_iva_mes)
    dias_stock = div_segura(b.stock * 30, b.cmv_mes)
    return {
        "activo_corriente": activo_corriente, "pasivo_corriente": pasivo_corriente,
        "activo_total": activo_total, "patrimonio_neto": pn,
        # NOF operativa: stock + deudores − deudas operativas (sin caja ni deuda financiera)
        "nof": b.stock + b.deudores - b.proveedores - b.remuneraciones_a_pagar - b.deudas_fiscales,
        "dias_cobro": dias_cobro, "dias_pago": dias_pago, "dias_stock": dias_stock,
        "pmm_ciclo_caja": (dias_stock or CERO) + (dias_cobro or CERO) - (dias_pago or CERO),
        "liquidez_corriente": div_segura(activo_corriente, pasivo_corriente),
        "prueba_acida": div_segura(activo_corriente - b.stock, pasivo_corriente),
        "endeudamiento": div_segura(pasivo_corriente, pn) if pn > 0 else None,
    }


def dupont(resultado_neto_mes: Decimal, ingresos_mes: Decimal, activo_total: Decimal,
           patrimonio_neto: Decimal) -> dict[str, Decimal | None]:
    """ROE anualizado = margen neto × rotación de activos (anualizada) × apalancamiento."""
    margen = div_segura(resultado_neto_mes, ingresos_mes)
    rotacion = div_segura(ingresos_mes * 12, activo_total)
    apalancamiento = div_segura(activo_total, patrimonio_neto) if patrimonio_neto > 0 else None
    roe = margen * rotacion * apalancamiento if None not in (margen, rotacion, apalancamiento) else None
    return {"margen_neto": margen, "rotacion_activos": rotacion, "apalancamiento": apalancamiento, "roe_anualizado": roe}


def semaforo(real: Decimal, presupuesto: Decimal, tolerancia: Decimal, signo: int) -> str:
    """Igual que Control_Ppto. Valores en positivo; `signo` +1 para ingresos, −1 para costos."""
    if presupuesto == 0 and real == 0:
        return "sin_datos"
    if presupuesto == 0:
        return "sin_ppto"
    desvio = (real - presupuesto) / presupuesto
    if abs(desvio) <= tolerancia:
        return "verde"
    if desvio * signo > 0:
        return "azul"           # desvío favorable
    return "amarillo" if abs(desvio) <= 2 * tolerancia else "rojo"


@dataclass
class Pendiente:
    vencimiento: date
    importe: Decimal


def proyeccion_caja(corte: date, disponible: Decimal, cobranzas: list[Pendiente], pagos: list[Pendiente],
                    sueldos_devengados: Decimal, presupuesto_sin_factura: tuple[Decimal, Decimal, Decimal],
                    pct_recupero_vencidas: Decimal, ajustes: tuple[Decimal, Decimal, Decimal] = (CERO, CERO, CERO)) -> dict:
    """Proyección a 0–30 / 31–60 / 61–90 días (Flujo_Caja de la planilla).
    presupuesto_sin_factura: (mes de corte sin personal, mes +1, mes +2), en ARS con signo."""
    tramos = [(corte, corte + timedelta(days=30)), (corte + timedelta(days=31), corte + timedelta(days=60)),
              (corte + timedelta(days=61), corte + timedelta(days=90))]
    suma = lambda items, d, h: sum((p.importe for p in items if d <= p.vencimiento <= h), CERO)
    cob_vencidas = sum((p.importe for p in cobranzas if p.vencimiento < corte), CERO)
    pag_vencidos = sum((p.importe for p in pagos if p.vencimiento < corte), CERO)
    saldo, salida = disponible, []
    for i, (d, h) in enumerate(tramos):
        flujo = suma(cobranzas, d, h) - suma(pagos, d, h) + presupuesto_sin_factura[i] + ajustes[i]
        if i == 0:
            flujo += cob_vencidas * pct_recupero_vencidas - pag_vencidos - sueldos_devengados
        saldo += flujo
        salida.append({"desde": d, "hasta": h, "flujo": flujo, "saldo": saldo})
    minimo = min(t["saldo"] for t in salida)
    return {"tramos": salida, "cobranzas_vencidas": cob_vencidas,
            "necesidad_financiamiento": -minimo if minimo < 0 else CERO}
