"""Ítems, ventas por ítem, mermas y rentabilidad por unidad de negocio e ítem (M_Items, T_Ventas,
T_Mermas y Rentab_UN de la planilla).

El costo estándar de cada ítem puede estar en otra moneda: se re-expresa con el tipo de cambio del mes de
cada venta o merma (lógica de costo de reposición). El CMV y las mermas entran al P&L como CV01 y CV10.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.numeros import div_segura
from app.finanzas.indices import TablaIndices
from app.finanzas.kpis import AsientoGestion

CERO = Decimal(0)


@dataclass
class Item:
    codigo: str
    descripcion: str
    tipo: str = "Bien"                       # Bien | Servicio
    unidad_negocio: str = "GENERAL"
    precio_lista: Decimal = CERO
    cotizacion_precio: str = "ARS"
    costo_estandar: Decimal = CERO
    cotizacion_costo: str = "ARS"
    alicuota_iva: Decimal = Decimal("0.21")


@dataclass
class LineaVenta:
    fecha: date
    comprobante: str
    item: str
    cantidad: Decimal                         # notas de crédito: negativa
    precio_unitario: Decimal                  # neto sin IVA, en ARS
    id: str = ""


@dataclass
class Merma:
    fecha: date
    item: str
    cantidad: Decimal
    causa: str
    turno: str = ""
    id: str = ""


@dataclass
class AvisosItems:
    items_desconocidos: set[str] = field(default_factory=set)
    sin_tc: int = 0


def costo_unitario_ars(item: Item, mes: date, indices: TablaIndices | None) -> Decimal | None:
    if item.cotizacion_costo in ("", "ARS"):
        return item.costo_estandar
    tc = indices.tc(mes, item.cotizacion_costo) if indices else None
    return item.costo_estandar * tc if tc else None


def asientos_de_items(lineas: Iterable[LineaVenta], mermas: Iterable[Merma], items: dict[str, Item],
                      indices: TablaIndices | None, rubros: dict[str, dict],
                      rubro_cmv: str = "CV01", rubro_mermas: str = "CV10") -> tuple[list[AsientoGestion], AvisosItems]:
    """CMV (cantidad vendida × costo estándar al TC del mes) y mermas valorizadas, como asientos de gestión."""
    avisos = AvisosItems()
    asientos: list[AsientoGestion] = []
    fuentes = [(l.fecha, l.item, l.cantidad, rubro_cmv, "cmv") for l in lineas] + \
              [(m.fecha, m.item, m.cantidad, rubro_mermas, "mermas") for m in mermas]
    for fecha, codigo, cantidad, rubro, origen in fuentes:
        item = items.get(codigo)
        if not item:
            avisos.items_desconocidos.add(codigo)
            continue
        mes = fecha.replace(day=1)
        costo = costo_unitario_ars(item, mes, indices)
        if costo is None:
            avisos.sin_tc += 1
            continue
        info = rubros[rubro]
        asientos.append(AsientoGestion(mes=mes, rubro=rubro, linea_pl=info["linea_pl"], importe=-(cantidad * costo),
                                       grupo_prime=info.get("grupo_prime"), unidad_negocio=item.unidad_negocio, origen=origen))
    return asientos, avisos


@dataclass
class FilaRentabilidad:
    clave: str                # código de UN o de ítem
    nombre: str
    unidad_negocio: str
    cantidad: Decimal = CERO
    ventas: Decimal = CERO
    cmv: Decimal = CERO
    mermas: Decimal = CERO

    @property
    def margen(self) -> Decimal:
        return self.ventas - self.cmv - self.mermas

    @property
    def margen_pct(self) -> Decimal | None:
        return div_segura(self.margen, self.ventas)

    @property
    def margen_unitario(self) -> Decimal | None:
        return div_segura(self.margen, self.cantidad)


def rentabilidad(lineas: Iterable[LineaVenta], mermas: Iterable[Merma], items: dict[str, Item],
                 indices: TablaIndices | None, costos_fijos: Decimal, desde: date, hasta: date) -> dict:
    """Margen de contribución por ítem y por unidad de negocio, punto de equilibrio ponderado por la mezcla
    real y margen de seguridad (Rentab_UN). `costos_fijos` en positivo, del mismo período."""
    por_item: dict[str, FilaRentabilidad] = {}

    def fila(codigo: str) -> FilaRentabilidad | None:
        it = items.get(codigo)
        if not it:
            return None
        return por_item.setdefault(codigo, FilaRentabilidad(codigo, it.descripcion, it.unidad_negocio))

    for l in lineas:
        if not (desde <= l.fecha <= hasta) or not (f := fila(l.item)):
            continue
        costo = costo_unitario_ars(items[l.item], l.fecha.replace(day=1), indices) or CERO
        f.cantidad += l.cantidad
        f.ventas += l.cantidad * l.precio_unitario
        f.cmv += l.cantidad * costo
    for m in mermas:
        if not (desde <= m.fecha <= hasta) or not (f := fila(m.item)):
            continue
        f.mermas += m.cantidad * (costo_unitario_ars(items[m.item], m.fecha.replace(day=1), indices) or CERO)

    por_un: dict[str, FilaRentabilidad] = {}
    for f in por_item.values():
        u = por_un.setdefault(f.unidad_negocio, FilaRentabilidad(f.unidad_negocio, f.unidad_negocio, f.unidad_negocio))
        u.cantidad += f.cantidad
        u.ventas += f.ventas
        u.cmv += f.cmv
        u.mermas += f.mermas

    ventas = sum((f.ventas for f in por_item.values()), CERO)
    margen = sum((f.margen for f in por_item.values()), CERO)
    mc_pct = div_segura(margen, ventas)
    equilibrio = div_segura(costos_fijos, mc_pct) if mc_pct and mc_pct > 0 else None
    return {
        "items": sorted(por_item.values(), key=lambda f: f.margen),
        "unidades": sorted(por_un.values(), key=lambda f: f.margen),
        "ventas": ventas, "margen": margen, "margen_pct": mc_pct, "costos_fijos": costos_fijos,
        "punto_equilibrio": equilibrio,
        "margen_seguridad": div_segura(ventas - equilibrio, ventas) if equilibrio is not None else None,
    }


def costos_fijos_del_periodo(asientos: Iterable[AsientoGestion], desde: date, hasta: date) -> Decimal:
    """Personal + estructura + comercialización + impuestos fijos del período, en positivo."""
    lineas = {"5 Personal", "6 Estructura", "7 Comercialización", "8 Impuestos fijos y tasas"}
    total = CERO
    for a in asientos:
        if a.linea_pl in lineas and desde.replace(day=1) <= a.mes <= hasta:
            total -= a.importe
    return total


def agrupar_mermas_por_causa(mermas: Iterable[Merma], items: dict[str, Item], indices: TablaIndices | None) -> dict[str, Decimal]:
    por_causa: dict[str, Decimal] = defaultdict(Decimal)
    for m in mermas:
        it = items.get(m.item)
        if it:
            por_causa[m.causa] += m.cantidad * (costo_unitario_ars(it, m.fecha.replace(day=1), indices) or CERO)
    return dict(sorted(por_causa.items(), key=lambda kv: -kv[1]))
