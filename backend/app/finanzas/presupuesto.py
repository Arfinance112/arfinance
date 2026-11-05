"""Presupuesto con ajuste por inflación y control de desvíos (T_Presupuesto y Control_Ppto de la planilla;
método por etapas de la planilla Zuccardi).

La BASE de cada rubro se carga en positivo y a precios del mes base (enero del año presupuestado). El
NOMINAL de cada mes = base × Índice(mes) / Índice(mes base), con el índice propio del rubro (IPC, CCT,
TARIFA, USD o FIJO). Así un presupuesto armado en enero sigue valiendo en octubre sin recalcularlo a mano.

Etapas para generar la base desde lo real (todas opcionales):
  1. Base histórica: promedio mensual de lo real de los meses elegidos, llevado a precios del mes base.
  2. Ajuste por volumen: % sobre los rubros de comportamiento Variable (más actividad = más costo variable).
  3. Objetivos de reducción: % por rubro (negativo = reducir).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.finanzas.indices import TablaIndices
from app.finanzas.kpis import AsientoGestion, semaforo

CERO, UNO = Decimal(0), Decimal(1)


def meses_del_anio(anio: int) -> list[date]:
    return [date(anio, m, 1) for m in range(1, 13)]


def factor(indices: TablaIndices | None, indice: str, mes: date, mes_base: date) -> Decimal:
    if indices is None or indice == "FIJO":
        return UNO
    base = indices.factor(indice, mes_base)
    return indices.factor(indice, mes) / base if base else UNO


def nominal(base: Decimal, indice: str, mes: date, mes_base: date, indices: TablaIndices | None) -> Decimal:
    return (base * factor(indices, indice, mes, mes_base)).quantize(Decimal("0.01"))


def real_por_rubro(asientos: Iterable[AsientoGestion], rubros: dict[str, dict]) -> dict[tuple[str, date], Decimal]:
    """Real en POSITIVO (como se presupuesta): ingresos tal cual, costos con el signo invertido."""
    real: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for a in asientos:
        signo = rubros.get(a.rubro, {}).get("signo") or 1
        real[(a.rubro, a.mes)] += a.importe * signo
    return dict(real)


def generar_base(real: dict[tuple[str, date], Decimal], meses_historicos: list[date], mes_base: date,
                 rubros: dict[str, dict], indices: TablaIndices | None, ajuste_volumen: Decimal = CERO,
                 objetivos: dict[str, Decimal] | None = None) -> dict[str, Decimal]:
    """Base mensual por rubro, a precios del mes base, aplicando las 3 etapas."""
    objetivos = objetivos or {}
    base: dict[str, Decimal] = {}
    for rubro in sorted({r for r, _ in real}):
        info = rubros.get(rubro, {})
        indice = info.get("indice_ajuste") or "IPC"
        # 1. histórico deflactado al mes base: cada mes se lleva a precios de mes_base antes de promediar
        valores = [real.get((rubro, m), CERO) / factor(indices, indice, m, mes_base) for m in meses_historicos]
        promedio = sum(valores, CERO) / len(meses_historicos) if meses_historicos else CERO
        if promedio <= 0:
            continue
        # 2. volumen sobre lo variable
        if info.get("comportamiento") == "Variable":
            promedio *= UNO + ajuste_volumen
        # 3. objetivo propio del rubro
        promedio *= UNO + objetivos.get(rubro, CERO)
        base[rubro] = promedio.quantize(Decimal("0.01"))
    return base


@dataclass
class FilaControl:
    rubro: str
    nombre: str
    linea_pl: str
    signo: int
    tolerancia: Decimal
    ppto_mes: Decimal
    real_mes: Decimal
    ppto_acum: Decimal
    real_acum: Decimal
    nota: str = ""

    @property
    def desvio_mes(self) -> Decimal:
        return self.real_mes - self.ppto_mes

    @property
    def desvio_pct_mes(self) -> Decimal | None:
        return self.desvio_mes / self.ppto_mes if self.ppto_mes else None

    @property
    def desvio_acum(self) -> Decimal:
        return self.real_acum - self.ppto_acum

    @property
    def desvio_pct_acum(self) -> Decimal | None:
        return self.desvio_acum / self.ppto_acum if self.ppto_acum else None

    @property
    def semaforo_mes(self) -> str:
        return semaforo(self.real_mes, self.ppto_mes, self.tolerancia, self.signo)

    @property
    def semaforo_acum(self) -> str:
        return semaforo(self.real_acum, self.ppto_acum, self.tolerancia, self.signo)


def control(mes: date, bases: dict[tuple[str, date], Decimal], real: dict[tuple[str, date], Decimal],
            rubros: dict[str, dict], indices: TablaIndices | None, tolerancia_defecto: Decimal,
            notas: dict[tuple[str, date], str] | None = None) -> list[FilaControl]:
    """Real vs presupuesto nominal del mes y acumulado del año, por rubro de resultado."""
    notas = notas or {}
    mes_base = date(mes.year, 1, 1)
    # el acumulado arranca en el primer mes con datos reales del año: un cliente que empieza a cargar
    # en septiembre no debe compararse contra el presupuesto de enero a agosto
    con_datos = [m for _, m in real if m.year == mes.year and m <= mes]
    desde = min(con_datos) if con_datos else mes_base
    meses_acum = [m for m in meses_del_anio(mes.year) if desde <= m <= mes]
    filas = []
    codigos = {r for r, _ in bases} | {r for r, m in real if m.year == mes.year}
    for rubro in sorted(codigos):
        info = rubros.get(rubro)
        if not info or info["linea_pl"] == "NO P&L":
            continue
        indice = info.get("indice_ajuste") or "IPC"
        ppto = lambda m: nominal(bases.get((rubro, m), CERO), indice, m, mes_base, indices)
        filas.append(FilaControl(
            rubro=rubro, nombre=info["nombre"], linea_pl=info["linea_pl"], signo=int(info.get("signo") or 1),
            tolerancia=Decimal(str(info["tolerancia"])) if info.get("tolerancia") else tolerancia_defecto,
            ppto_mes=ppto(mes), real_mes=real.get((rubro, mes), CERO),
            ppto_acum=sum((ppto(m) for m in meses_acum), CERO),
            real_acum=sum((real.get((rubro, m), CERO) for m in meses_acum), CERO),
            nota=notas.get((rubro, mes), "")))
    orden = {"rojo": 0, "amarillo": 1, "azul": 2, "sin_ppto": 3, "verde": 4, "sin_datos": 5}
    return sorted(filas, key=lambda f: (orden[f.semaforo_mes], f.linea_pl, f.rubro))
