"""Lector de comprobantes emitidos / recibidos exportados de ARCA ("Mis Comprobantes", .csv o .xlsx).

Detecta la fila de encabezados y mapea columnas por nombre con alias tolerantes (sin acentos,
sin mayúsculas), así sobrevive a cambios menores de rótulos. Devuelve un registro por comprobante,
listo para T_Ventas (emitidos) o T_Compras (recibidos). VALIDAR los alias con un archivo real.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.numeros import parse_fecha, parse_numero
from app.ingesta.reglas import normalizar

ALIAS = {
    "fecha": ["FECHA", "FECHA DE EMISION"],
    "tipo": ["TIPO", "TIPO DE COMPROBANTE"],
    "punto_venta": ["PUNTO DE VENTA", "PTO VTA"],
    "numero": ["NUMERO DESDE", "NUMERO", "NRO"],
    "doc_contraparte": ["NRO DOC RECEPTOR", "NRO DOC EMISOR", "NRO. DOC. RECEPTOR", "NRO. DOC. EMISOR", "CUIT"],
    "contraparte": ["DENOMINACION RECEPTOR", "DENOMINACION EMISOR"],
    "tipo_cambio": ["TIPO CAMBIO", "TIPO DE CAMBIO"],
    "moneda": ["MONEDA"],
    # formato actual de ARCA: una columna por alícuota y "Imp. Neto Gravado Total"; el viejo, una sola
    "neto_gravado": ["IMP NETO GRAVADO TOTAL", "IMP NETO GRAVADO", "IMP. NETO GRAVADO", "NETO GRAVADO"],
    "no_gravado": ["IMP NETO NO GRAVADO", "IMP. NETO NO GRAVADO"],
    "exento": ["IMP OP EXENTAS", "IMP. OP. EXENTAS"],
    "iva": ["IVA", "TOTAL IVA"],
    "total": ["IMP TOTAL", "IMP. TOTAL", "IMPORTE TOTAL"],
}
MINIMO = ("fecha", "tipo", "total")
# Códigos ARCA de notas de crédito (el formato actual trae solo el número: "3", "8", "13"…)
CODIGOS_NOTA_CREDITO = {3, 8, 13, 21, 38, 43, 44, 48, 53, 110, 112, 113, 114, 119, 203, 208, 213}


def es_nota_credito(tipo: str) -> bool:
    t = normalizar(tipo)
    if "CREDITO" in t:
        return True
    m = re.match(r"^0*(\d{1,3})\b", t)
    return bool(m) and int(m.group(1)) in CODIGOS_NOTA_CREDITO


@dataclass
class ComprobanteArca:
    fecha: date
    tipo: str
    comprobante: str            # "PPPPP-NNNNNNNN"
    doc_contraparte: str
    contraparte: str
    moneda: str
    tipo_cambio: Decimal
    neto: Decimal               # gravado + no gravado + exento, en moneda del comprobante
    iva: Decimal
    total: Decimal
    es_nota_credito: bool
    sentido: str = "emitido"    # emitido (venta) | recibido (compra)

    @property
    def neto_ars(self) -> Decimal:
        return self.neto * self.tipo_cambio


def detectar_sentido(encabezado: list) -> str:
    """Emitidos traen solo columnas del Receptor (el cliente). Recibidos traen las del Emisor (el proveedor);
    el formato actual de ARCA agrega además las del Receptor (uno mismo), así que manda la presencia de Emisor."""
    texto = " ".join(normalizar(str(c or "")) for c in encabezado)
    return "recibido" if "EMISOR" in texto else "emitido"


def _mapear(encabezado: list, sentido: str = "emitido") -> dict[str, int]:
    norm = [normalizar(str(c or "")).replace(".", "") for c in encabezado]
    mapa: dict[str, int] = {}
    # la contraparte es el Emisor en las compras y el Receptor en las ventas (nunca uno mismo)
    lado = "EMISOR" if sentido == "recibido" else "RECEPTOR"
    for campo, alias in ALIAS.items():
        if campo in ("doc_contraparte", "contraparte"):
            alias = [a for a in alias if lado in a or ("EMISOR" not in a and "RECEPTOR" not in a)]
        for a in alias:
            a_n = normalizar(a).replace(".", "")
            if a_n in norm:
                mapa[campo] = norm.index(a_n)
                break
    return mapa


def es_mis_comprobantes(filas: list[list]) -> bool:
    return any(all(c in _mapear(f) for c in MINIMO) for f in filas[:10])


def leer_mis_comprobantes(filas: list[list]) -> list[ComprobanteArca]:
    for i, fila in enumerate(filas[:10]):
        mapa = _mapear(fila)
        if all(c in mapa for c in MINIMO):
            break
    else:
        raise ValueError("No se encontró la fila de encabezados de 'Mis Comprobantes'.")
    sentido = detectar_sentido(filas[i])
    mapa = _mapear(filas[i], sentido)
    v = lambda f, c: f[mapa[c]] if c in mapa and mapa[c] < len(f) else None
    n = lambda f, c: abs(parse_numero(v(f, c), ",", "."))
    salida = []
    for fila in filas[i + 1:]:
        fecha = parse_fecha(v(fila, "fecha"))
        if not fecha:
            continue
        tipo = str(v(fila, "tipo") or "")
        nc = es_nota_credito(tipo)
        signo = -1 if nc else 1
        pv, nro = str(v(fila, "punto_venta") or "0"), str(v(fila, "numero") or "0")
        salida.append(ComprobanteArca(
            fecha=fecha, tipo=tipo,
            comprobante=f"{int(float(pv)):05d}-{int(float(nro)):08d}" if pv.replace('.', '').isdigit() and nro.replace('.', '').isdigit() else f"{pv}-{nro}",
            doc_contraparte=str(v(fila, "doc_contraparte") or ""), contraparte=str(v(fila, "contraparte") or ""),
            moneda=str(v(fila, "moneda") or "$"), tipo_cambio=n(fila, "tipo_cambio") or Decimal(1),
            neto=signo * (n(fila, "neto_gravado") + n(fila, "no_gravado") + n(fila, "exento")),
            iva=signo * n(fila, "iva"), total=signo * n(fila, "total"), es_nota_credito=nc, sentido=sentido))
    return salida
