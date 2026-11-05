"""Lector del F.931 (declaración jurada de cargas sociales, ARCA ex AFIP) a partir del texto del PDF.

El layout del acuse varía según la versión del aplicativo / Declaración en Línea, por eso los
rótulos están en una tabla configurable (ROTULOS) con varios alias por campo y la comparación
ignora mayúsculas, acentos y puntos. VALIDAR contra un F.931 real del cliente antes de producción:
si un rótulo no coincide, se agrega el alias, no se toca el algoritmo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.numeros import parse_numero
from app.ingesta.reglas import normalizar

ROTULOS: dict[str, list[str]] = {
    "cuit": ["CUIT"],
    "periodo": ["PERIODO", "PERIODO FISCAL", "MES/ANO"],
    "empleados": ["EMPLEADOS EN NOMINA", "CANTIDAD DE EMPLEADOS", "NOMINA"],
    "remuneracion_total": ["SUMA DE REM. 1", "REMUNERACION TOTAL", "TOTAL REMUNERACIONES"],
    "aportes_ss": ["APORTES SEG. SOCIAL", "APORTES SEGURIDAD SOCIAL", "SEGURIDAD SOCIAL APORTES"],
    "contribuciones_ss": ["CONTRIBUCIONES SEG. SOCIAL", "CONTRIBUCIONES SEGURIDAD SOCIAL", "SEGURIDAD SOCIAL CONTRIBUCIONES"],
    "aportes_os": ["APORTES OBRA SOCIAL", "OBRA SOCIAL APORTES"],
    "contribuciones_os": ["CONTRIBUCIONES OBRA SOCIAL", "OBRA SOCIAL CONTRIBUCIONES"],
    "lrt": ["L.R.T.", "LEY DE RIESGOS DEL TRABAJO", "ART"],
    "scvo": ["S.C.V.O.", "SEGURO COLECTIVO DE VIDA"],
    "total_a_pagar": ["TOTAL A PAGAR", "IMPORTE A PAGAR", "TOTAL DECLARACION"],
}
_IMPORTE = r"(-?\d+(?:,\d{1,2})?)(?!\d|/)"
_PERIODO = r"(\d{2}/\d{4})"
OBLIGATORIOS = ("cuit", "periodo", "total_a_pagar")

# Sección "VIII - Montos que se ingresan": códigos de concepto de ARCA, iguales en todos los F.931.
# Son lo más confiable del formulario: los rótulos cambian de versión en versión, los códigos no.
CODIGOS_VIII = {"301": "aportes_ss", "302": "aportes_os", "351": "contribuciones_ss", "352": "contribuciones_os",
                "312": "lrt", "028": "scvo", "360": "renatre", "270": "vales_alimentarios", "935": "sepelio_uatre"}
_MONTO_CODIGO = re.compile(r"(?<![\d.,])(" + "|".join(CODIGOS_VIII) + r")\s*-\s*[A-Za-zÁÉÍÓÚáéíóúÑñ./ ]+?\s(\d{1,3}(?:\.\d{3})*,\d{2})")


def _montos_por_codigo(texto: str) -> dict[str, Decimal]:
    montos = {}
    for codigo, valor in _MONTO_CODIGO.findall(texto):
        montos.setdefault(CODIGOS_VIII[codigo], abs(parse_numero(valor)))
    return montos


def _periodo(texto: str) -> date | None:
    """El enlace del formulario trae Periodo=AAAAMM; si no, "Mes - Año" con MM/AAAA cerca (puede venir en otra
    línea por cómo se extrae el texto del PDF); si no, el primer MM/AAAA del documento."""
    m = re.search(r"Periodo=(20\d{2})(0[1-9]|1[0-2])", texto, re.I)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    rotulo = re.search(r"Mes\s*-\s*A[ñn]o", texto, re.I)
    zona = texto[rotulo.end(): rotulo.end() + 300] if rotulo else texto
    m = re.search(r"(?<![\d/])(0[1-9]|1[0-2])/(20\d{2})(?![\d/])", zona) or \
        re.search(r"(?<![\d/])(0[1-9]|1[0-2])/(20\d{2})(?![\d/])", texto)
    return date(int(m.group(2)), int(m.group(1)), 1) if m else None


@dataclass
class DeclaracionF931:
    cuit: str | None = None
    periodo: date | None = None
    empleados: int | None = None
    importes: dict[str, Decimal] = field(default_factory=dict)
    faltantes: list[str] = field(default_factory=list)

    @property
    def completa(self) -> bool:
        return not self.faltantes

    @property
    def cargas_patronales(self) -> Decimal:
        """Lo que es costo de la empresa (va al costo laboral): contribuciones + LRT + SCVO."""
        return sum((self.importes.get(k, Decimal(0)) for k in ("contribuciones_ss", "contribuciones_os", "lrt", "scvo")),
                   Decimal(0))


def _norm(texto: str) -> str:
    return normalizar(texto).replace(".", "")


def _valor_tras(rotulo: str, lineas: list[str], patron: str) -> str | None:
    """Primer valor con `patron` que aparece DESPUÉS del rótulo en la misma línea.
    Se trabaja sobre la línea normalizada (sin acentos ni puntos: '1.234,56' queda '1234,56')."""
    clave = re.compile(r"(?<![A-Z0-9])" + re.escape(_norm(rotulo)) + r"(?![A-Z0-9])")
    for linea in lineas:
        n = _norm(linea)
        m = clave.search(n)
        if not m:
            continue
        v = re.search(patron, n[m.end():])
        if v:
            return v.group(1)
    return None


def leer_f931(texto: str) -> DeclaracionF931:
    lineas = [l for l in texto.splitlines() if l.strip()]
    dj = DeclaracionF931()
    m = re.search(r"\b(\d{2}-?\d{8}-?\d)\b", texto)
    if m:
        dj.cuit = re.sub(r"\D", "", m.group(1))
    for campo, alias in ROTULOS.items():
        if campo == "cuit":
            continue
        patron = _PERIODO if campo == "periodo" else _IMPORTE
        valor = next((v for a in alias if (v := _valor_tras(a, lineas, patron)) is not None), None)
        if valor is None:
            continue
        if campo == "periodo":
            mm = re.match(r"(\d{2})/(\d{4})", valor)
            if mm:
                dj.periodo = date(int(mm.group(2)), int(mm.group(1)), 1)
        elif campo == "empleados":
            dj.empleados = int(parse_numero(valor))
        else:
            dj.importes[campo] = abs(parse_numero(valor))
    if not dj.periodo:
        dj.periodo = _periodo(texto)
    # los montos de la sección VIII pisan lo leído por rótulo (más confiables), y su suma es el total a pagar
    por_codigo = _montos_por_codigo(texto)
    if por_codigo:
        dj.importes.update(por_codigo)
        dj.importes["total_a_pagar"] = sum(por_codigo.values(), Decimal(0))
    dj.faltantes = [c for c in OBLIGATORIOS
                    if (c == "cuit" and not dj.cuit) or (c == "periodo" and not dj.periodo)
                    or (c not in ("cuit", "periodo") and c not in dj.importes)]
    return dj


def es_f931(texto: str) -> bool:
    t = normalizar(texto)
    return "931" in t and ("SEGURIDAD SOCIAL" in t or "SUSS" in t or "SICOSS" in t)
