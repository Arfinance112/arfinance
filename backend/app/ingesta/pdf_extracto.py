"""Extractos bancarios en PDF sin tablas dibujadas (Galicia y la mayoría de los resúmenes de home banking).

Cada movimiento es un renglón "fecha · descripción · [origen] · importe(s) · saldo", a veces seguido de renglones
con la contraparte (nombre, CUIT, CBU). El importe aparece UNA vez y lo que dice si es crédito o débito es la
COLUMNA donde está, así que se lee por posición: se ubican los encabezados (Crédito / Débito / Importe / Saldo) y
cada importe va a la columna cuyo centro tiene más cerca.

Sale en filas del perfil "débito y crédito separados" (Fecha, Descripción, Débito, Crédito, Saldo, Referencia) o
"importe con signo" (Fecha, Descripción, Importe, Saldo, Referencia), que el detector de perfiles reconoce solo.
"""
from __future__ import annotations

import re

from app.ingesta.reglas import normalizar

FECHA = re.compile(r"^\d{1,2}/\d{1,2}/(\d{2}|\d{4})$")
MONTO = re.compile(r"^\(?-?\$?\d{1,3}(?:\.\d{3})*,\d{2}-?\)?$")
COLUMNAS = {"CREDITO": "credito", "CREDITOS": "credito", "DEBITO": "debito", "DEBITOS": "debito",
            "IMPORTE": "importe", "SALDO": "saldo"}
MAX_CONTINUACION = 8      # renglones de contraparte que siguen a un movimiento


def _renglones(palabras: list[dict], tolerancia: float = 3) -> list[list[dict]]:
    """Agrupa palabras por renglón (misma altura, con tolerancia) y las ordena de izquierda a derecha."""
    renglones: list[list[dict]] = []
    for w in sorted(palabras, key=lambda w: (round(w["top"]), w["x0"])):
        if renglones and abs(renglones[-1][0]["top"] - w["top"]) <= tolerancia:
            renglones[-1].append(w)
        else:
            renglones.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in renglones]


def _encabezado(renglon: list[dict]) -> dict[str, float] | None:
    centros = {}
    for w in renglon:
        col = COLUMNAS.get(normalizar(w["text"]).strip(":"))
        if col and col not in centros:
            centros[col] = (w["x0"] + w["x1"]) / 2
    tiene_importe = "importe" in centros or ("credito" in centros and "debito" in centros)
    tiene_fecha = any(normalizar(w["text"]) == "FECHA" for w in renglon)
    return centros if tiene_importe and tiene_fecha else None


def leer_por_columnas(pdf) -> list[list[str]] | None:
    """`pdf`: documento abierto con pdfplumber. Devuelve filas con encabezado, o None si no parece un extracto."""
    centros: dict[str, float] | None = None
    movimientos: list[dict] = []
    for pagina in pdf.pages:
        actual = None
        for renglon in _renglones(pagina.extract_words(keep_blank_chars=False, use_text_flow=False)):
            enc = _encabezado(renglon)
            if enc:
                centros, actual = enc, None
                continue
            if centros is None:
                continue
            textos = [w["text"] for w in renglon]
            if FECHA.match(textos[0]) and any(MONTO.match(t) for t in textos[1:]):
                mov = {"fecha": textos[0], "descripcion": [], "valores": {}, "extra": []}
                for w in renglon[1:]:
                    if MONTO.match(w["text"]):
                        centro = (w["x0"] + w["x1"]) / 2
                        col = min(centros, key=lambda c: abs(centros[c] - centro))
                        mov["valores"].setdefault(col, w["text"])
                    elif not mov["valores"]:
                        mov["descripcion"].append(w["text"])
                movimientos.append(mov)
                actual = mov
            elif actual is not None and len(actual["extra"]) < MAX_CONTINUACION:
                actual["extra"].append(" ".join(textos))
    if len(movimientos) < 2:
        return None

    separados = any("credito" in m["valores"] or "debito" in m["valores"] for m in movimientos)
    filas = [["Fecha", "Descripción", "Débito", "Crédito", "Saldo", "Referencia"] if separados
             else ["Fecha", "Descripción", "Importe", "Saldo", "Referencia"]]
    for m in movimientos:
        # la primera línea de continuación suele ser la contraparte: suma a la descripción (para las reglas)
        descripcion = " ".join(m["descripcion"] + m["extra"][:1]).strip()
        referencia = " ".join(m["extra"][1:])[:120]
        v = m["valores"]
        if separados:
            filas.append([m["fecha"], descripcion, v.get("debito", ""), v.get("credito", ""), v.get("saldo", ""), referencia])
        else:
            filas.append([m["fecha"], descripcion, v.get("importe", ""), v.get("saldo", ""), referencia])
    return filas
