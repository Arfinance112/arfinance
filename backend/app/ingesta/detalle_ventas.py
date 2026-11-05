"""Lector del detalle de ventas por ítem (exportación del punto de venta, facturador o e-commerce).

Columnas mínimas, con alias tolerantes: Fecha · Comprobante · Código de ítem · Cantidad · Precio unitario
(neto sin IVA). Si en vez del precio trae el importe del renglón, se calcula el unitario.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.numeros import parse_fecha, parse_numero
from app.finanzas.items import LineaVenta
from app.ingesta.reglas import normalizar

ALIAS = {
    "fecha": ["FECHA", "FECHA DE VENTA", "FECHA EMISION"],
    "comprobante": ["COMPROBANTE", "NRO COMPROBANTE", "FACTURA", "TICKET", "NUMERO"],
    "item": ["CODIGO", "CODIGO ITEM", "ITEM", "SKU", "CODIGO PRODUCTO", "PRODUCTO CODIGO"],
    "cantidad": ["CANTIDAD", "CANT", "UNIDADES"],
    "precio": ["PRECIO UNITARIO", "PRECIO UNIT", "PRECIO NETO", "PRECIO"],
    "importe": ["IMPORTE NETO", "SUBTOTAL", "IMPORTE", "TOTAL NETO"],
}


def _mapear(fila: list) -> dict[str, int]:
    norm = [normalizar(str(c or "")).replace(".", "") for c in fila]
    mapa = {}
    for campo, alias in ALIAS.items():
        for a in alias:
            if a in norm:
                mapa[campo] = norm.index(a)
                break
    return mapa


def _encabezado(filas: list[list]) -> tuple[int, dict[str, int]] | None:
    for i, f in enumerate(filas[:10]):
        m = _mapear(f)
        if {"fecha", "item", "cantidad"} <= m.keys() and ({"precio", "importe"} & m.keys()):
            return i, m
    return None


def es_detalle_ventas(filas: list[list]) -> bool:
    return _encabezado(filas) is not None


def leer_detalle_ventas(filas: list[list]) -> list[LineaVenta]:
    hallado = _encabezado(filas)
    if not hallado:
        raise ValueError("No se encontraron las columnas Fecha, Código de ítem, Cantidad y Precio.")
    i, mapa = hallado
    v = lambda f, c: f[mapa[c]] if c in mapa and mapa[c] < len(f) else None
    salida = []
    for fila in filas[i + 1:]:
        fecha = parse_fecha(v(fila, "fecha"))
        codigo = str(v(fila, "item") or "").strip()
        cantidad = parse_numero(v(fila, "cantidad"))
        if not fecha or not codigo or cantidad == 0:
            continue
        precio = parse_numero(v(fila, "precio")) if "precio" in mapa else parse_numero(v(fila, "importe")) / cantidad
        salida.append(LineaVenta(fecha, str(v(fila, "comprobante") or "").strip(), codigo.upper(), cantidad, abs(precio)))
    return salida
