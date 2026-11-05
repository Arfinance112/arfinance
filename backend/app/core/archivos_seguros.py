"""Control de lo que se sube ANTES de leerlo o guardarlo.

  * Nombre: sin rutas, sin caracteres de control, largo acotado.
  * Contenido coherente con la extensión (firma de bytes): un .xlsx tiene que ser un ZIP de Office, un .pdf
    tiene que empezar con %PDF, un .csv no puede ser binario. Evita que un ejecutable entre renombrado.
  * .xlsx: tope de tamaño descomprimido y de tasa de compresión (bombas ZIP).
  * .pdf: se rechazan los que traen acciones automáticas (/Launch, /JavaScript, adjuntos embebidos).
  * Antivirus opcional: si CLAMAV_HOST está definida se escanea con clamd (protocolo INSTREAM).
"""
from __future__ import annotations

import io
import os
import re
import socket
import struct
import zipfile
from pathlib import PurePath

EXTENSIONES = {".xlsx", ".xlsm", ".csv", ".txt", ".pdf"}
MAX_DESCOMPRIMIDO = 200 * 1024 * 1024
MAX_TASA_COMPRESION = 100
PDF_PROHIBIDO = (b"/Launch", b"/JavaScript", b"/JS ", b"/EmbeddedFile")
FIRMAS_BINARIAS = (b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF", b"\xd0\xcf\x11\xe0")


class ArchivoRechazado(Exception):
    def __init__(self, status: int, mensaje: str):
        super().__init__(mensaje)
        self.status = status


def nombre_seguro(nombre: str | None) -> str:
    base = PurePath((nombre or "archivo").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", base).strip(" .") or "archivo"
    raiz, ext = os.path.splitext(base)
    return raiz[:100] + ext[:10].lower()


def validar(nombre: str, contenido: bytes) -> None:
    ext = PurePath(nombre).suffix.lower()
    if ext == ".xls":
        raise ArchivoRechazado(415, "Los .xls (Excel 97-2003) no se leen directo: guardalo como .xlsx o .csv.")
    if ext not in EXTENSIONES:
        raise ArchivoRechazado(415, f"Formato {ext or 'desconocido'} no soportado. Usá .xlsx, .csv o .pdf.")
    if not contenido:
        raise ArchivoRechazado(422, "El archivo está vacío.")
    if ext in (".xlsx", ".xlsm"):
        _validar_xlsx(contenido)
    elif ext == ".pdf":
        if not contenido.lstrip()[:5] == b"%PDF-":
            raise ArchivoRechazado(415, "El archivo no es un PDF válido aunque termine en .pdf.")
        if any(p in contenido for p in PDF_PROHIBIDO):
            raise ArchivoRechazado(422, "El PDF trae acciones automáticas o adjuntos embebidos: no se acepta. "
                                        "Descargalo de nuevo desde el banco o imprimilo a PDF.")
    else:
        muestra = contenido[:65536]
        if muestra.startswith(FIRMAS_BINARIAS) or _parece_binario(muestra):
            raise ArchivoRechazado(415, f"El archivo no es texto aunque termine en {ext}. Si es un Excel, guardalo como .xlsx.")
    escanear_antivirus(contenido)


def _parece_binario(muestra: bytes) -> bool:
    # UTF-16 (con BOM) es texto legítimo; fuera de eso, un NUL es señal de binario
    if muestra.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    return b"\x00" in muestra


def _validar_xlsx(contenido: bytes) -> None:
    if not contenido.startswith(b"PK\x03\x04"):
        raise ArchivoRechazado(415, "El archivo no es un Excel .xlsx válido aunque termine en .xlsx.")
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            infos = z.infolist()
            if "[Content_Types].xml" not in {i.filename for i in infos}:
                raise ArchivoRechazado(415, "El archivo es un ZIP pero no un Excel.")
            total = sum(i.file_size for i in infos)
            comprimido = sum(i.compress_size for i in infos) or 1
    except zipfile.BadZipFile:
        raise ArchivoRechazado(415, "El Excel está dañado o incompleto.")
    if total > MAX_DESCOMPRIMIDO or total / comprimido > MAX_TASA_COMPRESION:
        raise ArchivoRechazado(422, "El Excel descomprimido es desproporcionadamente grande: no se procesa.")


def escanear_antivirus(contenido: bytes) -> None:
    host = os.environ.get("CLAMAV_HOST")
    if not host:
        return
    puerto = int(os.environ.get("CLAMAV_PORT", "3310"))
    try:
        with socket.create_connection((host, puerto), timeout=30) as s:
            s.sendall(b"zINSTREAM\0")
            for i in range(0, len(contenido), 65536):
                trozo = contenido[i:i + 65536]
                s.sendall(struct.pack(">I", len(trozo)) + trozo)
            s.sendall(struct.pack(">I", 0))
            respuesta = s.recv(4096).decode(errors="replace").strip("\0 \n")
    except OSError:
        if os.environ.get("CLAMAV_OBLIGATORIO") == "1":
            raise ArchivoRechazado(503, "El antivirus no responde: intentá de nuevo en unos minutos.")
        return
    if respuesta.endswith("FOUND"):
        raise ArchivoRechazado(422, "El antivirus detectó una amenaza en el archivo: no se guardó.")
