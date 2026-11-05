"""OCR para PDF escaneados (fotos o escaneos de extractos, F.931 impresos).

Un PDF es "escaneado" si casi no tiene texto extraíble. Cada página se rasteriza con pypdfium2 (viene con
pdfplumber) y se pasa a un motor de OCR. El motor por defecto es Tesseract por línea de comando con el
idioma español: TESSERACT_CMD, el PATH o la instalación típica de Windows. Sin motor, el documento se
rechaza con una explicación (nunca se inventa un resultado).

El texto reconocido se convierte en filas separando columnas por 2 o más espacios (Tesseract conserva el
espaciado con --psm 6). Lo leído por OCR siempre queda "con alertas": los importes hay que revisarlos.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from app.ingesta.lectores import ArchivoLeido

MIN_CARACTERES_POR_PAGINA = 20
MAX_PAGINAS = 30
DPI = 300


class MotorOCR(Protocol):
    nombre: str

    def reconocer(self, png: bytes) -> str: ...


class SinMotorOCR(Exception):
    pass


class MotorTesseract:
    nombre = "tesseract"

    def __init__(self, comando: str, idioma: str = "spa", datos: str | None = None):
        self.comando, self.idioma, self.datos = comando, idioma, datos

    def reconocer(self, png: bytes) -> str:
        with tempfile.TemporaryDirectory() as d:
            imagen = Path(d) / "pagina.png"
            imagen.write_bytes(png)
            extra = ["--tessdata-dir", self.datos] if self.datos else []
            r = subprocess.run([self.comando, str(imagen), "stdout", *extra, "-l", self.idioma, "--psm", "6",
                                "-c", "preserve_interword_spaces=1"], capture_output=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode(errors="replace")[:300])
            return r.stdout.decode("utf-8", errors="replace")


DATOS_LOCALES = Path(__file__).resolve().parents[2] / ".tessdata"   # backend/.tessdata (idiomas sin permisos de admin)


def motor_disponible() -> MotorOCR | None:
    datos = os.environ.get("OCR_DATOS") or (str(DATOS_LOCALES) if DATOS_LOCALES.is_dir() else None)
    for c in (os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"), r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
        if c and Path(c).exists():
            return MotorTesseract(c, os.environ.get("OCR_IDIOMA", "spa"), datos)
    return None


def es_escaneado(leido: ArchivoLeido, paginas: int) -> bool:
    return leido.extension == ".pdf" and len(leido.texto.strip()) < MIN_CARACTERES_POR_PAGINA * max(paginas, 1)


def contar_paginas(contenido: bytes) -> int:
    import pypdfium2 as pdfium
    return len(pdfium.PdfDocument(contenido))


# Variantes de rasterizado y limpieza: (dpi, umbral de blanco y negro o None). Ninguna gana siempre (depende del
# escaneo), así que se prueban todas y se queda la que mejor "cierra" (ver puntaje). Medido en tests/escaneo.py.
VARIANTES = ((200, None), (200, 200), (300, 200))


def paginas_como_png(contenido: bytes, variantes=VARIANTES) -> list[list[bytes]]:
    """Por página, una imagen PNG por variante."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(contenido)
    if len(pdf) > MAX_PAGINAS:
        raise ValueError(f"El PDF escaneado tiene {len(pdf)} páginas; el máximo para OCR es {MAX_PAGINAS}.")
    salida = []
    for pagina in pdf:
        imagenes = []
        for dpi, umbral in variantes:
            buf = io.BytesIO()
            limpiar(pagina.render(scale=dpi / 72, grayscale=True).to_pil(), umbral).save(buf, format="PNG")
            imagenes.append(buf.getvalue())
        salida.append(imagenes)
    return salida


def limpiar(imagen, umbral: int | None):
    """Escaneos reales: polvo, grises y fondo sucio. Mediana (saca puntos sueltos) y, opcional, blanco y negro."""
    from PIL import ImageFilter, ImageOps
    imagen = ImageOps.autocontrast(imagen.convert("L")).filter(ImageFilter.MedianFilter(3))
    return imagen if umbral is None else imagen.point(lambda p: 255 if p > umbral else 0)


def _fecha_valida(t: str) -> bool:
    partes = re.split(r"[/.-]", t)
    return len(partes) == 3 and 1 <= int(partes[0]) <= 31 and 1 <= int(partes[1]) <= 12


def puntaje(texto: str) -> int:
    """Calidad de una lectura: renglones de extracto cuyo importe cierra con el saldo valen mucho; con fecha
    válida, algo; para documentos que no son extractos (F.931), desempata la cantidad de texto reconocido."""
    movs, cierran = _parsear(texto)
    return cierran * 1000 + sum(_fecha_valida(m[0]) for m in movs) * 100 + min(len(re.findall(r"\w", texto)), 99)


FECHA = r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})"
IMPORTE = r"(-?\s?\$?\s?\d{1,3}(?:[.\s]\d{3})*,\d{2}-?)"
RENGLON = re.compile(rf"{FECHA}\s+(.+?)\s+{IMPORTE}\s+{IMPORTE}\s*\W*$")


def _num(t: str) -> float:
    neg = "-" in t
    t = re.sub(r"[^\d,]", "", t).replace(",", ".")
    return -float(t) if neg else float(t)


def _fmt(v: float) -> str:
    entero, dec = f"{abs(v):,.2f}".split(".")
    return ("-" if v < 0 else "") + entero.replace(",", ".") + "," + dec


def _parsear(texto: str) -> tuple[list[list], int]:
    """Renglones fecha · concepto · importe · saldo, y cuántos cierran con el saldo del renglón anterior.
    El OCR suele perder el signo menos: se reconstruye con la diferencia de saldos entre renglones vecinos, en el
    orden que tenga el extracto (más nuevo arriba o abajo). Si importe y saldo no cierran, se deja como se leyó:
    la conciliación lo va a marcar."""
    movs = []
    for linea in texto.splitlines():
        m = RENGLON.search(linea)
        if m:
            concepto = re.sub(r"[^\w\s./-]", "", m.group(2)).strip(" .-")
            movs.append([m.group(1), concepto, _num(m.group(3)), _num(m.group(4))])

    def cierra(i: int, j: int) -> float | None:          # importe de i según los saldos de i y su anterior j
        delta = movs[i][3] - movs[j][3]
        return delta if abs(abs(delta) - abs(movs[i][2])) < 0.01 else None

    # orden: más nuevo arriba si el saldo de abajo es el anterior de arriba
    arriba = sum(cierra(i, i + 1) is not None for i in range(len(movs) - 1))
    abajo = sum(cierra(i, i - 1) is not None for i in range(1, len(movs)))
    cierran = 0
    for i in range(len(movs)):
        j = i + 1 if arriba >= abajo else i - 1
        if 0 <= j < len(movs) and (d := cierra(i, j)) is not None:
            movs[i][2] = d
            cierran += 1
    return movs, cierran


def renglones_de_extracto(texto: str) -> list[list[str]] | None:
    """Si el texto parece un extracto, filas limpias con encabezado (las que lee el perfil de extracto)."""
    movs, _ = _parsear(texto)
    if len(movs) < 2:
        return None
    return [["Fecha", "Concepto", "Importe", "Saldo"]] + [[f, c, _fmt(i), _fmt(s)] for f, c, i, s in movs]


def texto_a_filas(texto: str) -> list[list[str]]:
    extracto = renglones_de_extracto(texto)
    if extracto:
        return extracto
    filas = []
    for linea in texto.splitlines():
        if linea.strip():
            filas.append([c.strip() for c in re.split(r"\s{2,}|\t|\s\|\s", linea.strip()) if c.strip()])
    return filas


def leer_con_ocr(nombre: str, contenido: bytes, motor: MotorOCR | None) -> ArchivoLeido:
    if motor is None:
        raise SinMotorOCR("El PDF es una imagen escaneada y este servidor no tiene OCR configurado. "
                          "Pedí el extracto en Excel, CSV o PDF descargado del home banking (con texto).")
    paginas = []
    for variantes in paginas_como_png(contenido):
        lecturas = [motor.reconocer(png) for png in variantes]
        paginas.append(max(lecturas, key=puntaje))                       # empate: gana la primera variante
    texto = "\n".join(paginas)
    return ArchivoLeido(nombre, ".pdf", filas=texto_a_filas(texto), texto=texto)
