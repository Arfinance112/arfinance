"""Interpretación robusta de números y fechas tal como vienen en extractos argentinos.

Es el port de las fórmulas de IMP_Calc de la planilla: acepta valores ya tipados
(número, fecha) o texto en cualquier formato habitual ('1.234,56', '-$ 1.234',
'(1.234,56)', '1,234.56', '05/10/26', '2026-10-05T10:00').
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

_EXCEL_EPOCH = date(1899, 12, 30)
_LIMPIAR = re.compile(r"U\$S|US\$|USD|ARS|\$|\+|\s| ", re.IGNORECASE)


def parse_numero(valor, sep_decimal: str = ",", sep_miles: str = ".") -> Decimal:
    """Devuelve el importe como Decimal. Texto ilegible o vacío → 0."""
    if valor is None or valor == "":
        return Decimal(0)
    if isinstance(valor, bool):
        return Decimal(0)
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor))
    texto = str(valor).strip()
    negativo = "-" in texto or "(" in texto
    s = _LIMPIAR.sub("", texto).replace("-", "").replace("(", "").replace(")", "")
    if sep_miles:
        s = s.replace(sep_miles, "")
    if sep_decimal and sep_decimal != ".":
        s = s.replace(sep_decimal, ".")
    try:
        numero = Decimal(s) if s else Decimal(0)
    except InvalidOperation:
        return Decimal(0)
    return -numero if negativo else numero


def parse_fecha(valor, formato: str = "DMY") -> date | None:
    """Fecha desde date/datetime, serial de Excel o texto DMY / YMD / MDY (con o sin hora)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return _EXCEL_EPOCH + timedelta(days=int(valor)) if valor >= 20000 else None
    texto = str(valor).strip().upper().replace("T", " ")
    partes = re.split(r"[/\-.]", texto.split(" ")[0])
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return None
    a, b, c = (int(p) for p in partes)
    if a > 31:                       # AAAA-MM-DD aunque el perfil diga otra cosa
        formato = "YMD"
    if formato == "YMD":
        anio, mes, dia = a, b, c
    elif formato == "MDY":
        mes, dia, anio = a, b, c
    else:
        dia, mes, anio = a, b, c
    if anio < 100:
        anio += 2000
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def div_segura(numerador, denominador, defecto=None):
    """Equivalente estandarizado de SI.ERROR(a/b; defecto): nunca lanza por división por cero."""
    try:
        if denominador in (None, 0) or numerador is None:
            return defecto
        return numerador / denominador
    except (ZeroDivisionError, InvalidOperation, TypeError):
        return defecto


def primer_dia_mes(d: date) -> date:
    return d.replace(day=1)
