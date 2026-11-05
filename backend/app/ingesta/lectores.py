"""Lectura de archivos subidos: .xlsx, .csv/.txt y .pdf → filas de celdas (+ texto plano en PDF)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import PurePath


class FormatoNoSoportado(ValueError):
    pass


@dataclass
class ArchivoLeido:
    nombre: str
    extension: str
    filas: list[list] = field(default_factory=list)
    texto: str = ""                     # texto completo (PDF) para parsers de documentos como el F.931
    hojas: list[str] = field(default_factory=list)


def leer_archivo(nombre: str, contenido: bytes) -> ArchivoLeido:
    ext = PurePath(nombre).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _leer_xlsx(nombre, contenido)
    if ext in (".csv", ".txt"):
        return _leer_csv(nombre, contenido)
    if ext == ".pdf":
        return _leer_pdf(nombre, contenido)
    if ext == ".xls":
        raise FormatoNoSoportado("Los .xls (Excel 97-2003) no se leen directo: guardalo como .xlsx o .csv "
                                 "(en producción se agrega la librería xlrd).")
    raise FormatoNoSoportado(f"Formato {ext or 'desconocido'} no soportado. Usá .xlsx, .csv o .pdf.")


def _leer_xlsx(nombre: str, contenido: bytes) -> ArchivoLeido:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    filas = [list(f) for f in ws.iter_rows(values_only=True)]
    return ArchivoLeido(nombre, ".xlsx", filas=filas, hojas=wb.sheetnames)


def _decodificar(contenido: bytes) -> str:
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenido.decode(cod)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1", errors="replace")


def _delimitador(texto: str) -> str:
    """En Argentina la coma es el separador decimal, así que los CSV de bancos usan ';'.
    Se elige el primer candidato que aparece la misma cantidad de veces (>0) en todas las líneas;
    la coma va última porque también aparece dentro de los importes."""
    lineas = [l for l in texto.splitlines()[:30] if l.strip()]
    for d in (";", "\t", "|", ","):
        cuentas = {l.count(d) for l in lineas}
        if len(cuentas) == 1 and cuentas.pop() > 0:
            return d
    for d in (";", "\t", "|"):
        if any(d in l for l in lineas):
            return d
    return ","


def _leer_csv(nombre: str, contenido: bytes) -> ArchivoLeido:
    texto = _decodificar(contenido)
    filas = [fila for fila in csv.reader(io.StringIO(texto), delimiter=_delimitador(texto))]
    return ArchivoLeido(nombre, ".csv", filas=filas, texto=texto)


def _leer_pdf(nombre: str, contenido: bytes) -> ArchivoLeido:
    import pdfplumber

    filas: list[list] = []
    partes: list[str] = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
            for tabla in pagina.extract_tables() or []:
                filas.extend([list(f) for f in tabla])
        texto = "\n".join(partes)
        # sin tablas útiles (todo en una columna): extracto de home banking, se lee por posición de columnas
        if not filas or all(len([c for c in f if c not in (None, "")]) <= 1 for f in filas):
            from app.ingesta.pdf_extracto import leer_por_columnas
            por_columnas = leer_por_columnas(pdf)
            if por_columnas:
                filas = por_columnas
    if not filas:   # PDF sin tablas detectables: una fila por renglón de texto
        filas = [[linea] for linea in texto.splitlines() if linea.strip()]
    return ArchivoLeido(nombre, ".pdf", filas=filas, texto=texto)
