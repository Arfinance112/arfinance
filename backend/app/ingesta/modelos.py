"""Modelos del motor de ingesta (independientes de la base de datos y del framework web)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class Alerta(str, Enum):
    SIN_REGLA = "SIN_REGLA"                    # bloquea la aprobación
    RUBRO_INEXISTENTE = "RUBRO_INEXISTENTE"    # bloquea la aprobación
    DUPLICADO_EXACTO = "DUPLICADO_EXACTO"      # misma referencia ya cargada: se omite siempre
    POSIBLE_DUPLICADO = "POSIBLE_DUPLICADO"    # misma cuenta, fecha, tipo e importe: se omite salvo que se fuerce
    SIN_COMPROBANTE = "SIN_COMPROBANTE"        # informativa: cobro/pago que no cancelará facturas

    @property
    def bloquea(self) -> bool:
        return self in (Alerta.SIN_REGLA, Alerta.RUBRO_INEXISTENTE)


class Pata(str, Enum):
    PRINCIPAL = "principal"
    COMISION = "comision"
    IMPUESTOS = "impuestos"


@dataclass
class Perfil:
    codigo: str
    nombre: str
    tipo_origen: str = "Banco"
    col_fecha: str | None = "A"
    formato_fecha: str = "DMY"
    col_descripcion: str | None = "B"
    col_descripcion2: str | None = None
    modo_importe: str = "Importe con signo"
    col_importe: str | None = None
    col_debito: str | None = None
    col_credito: str | None = None
    col_tipo: str | None = None
    texto_egreso: str | None = None
    col_comision: str | None = None
    col_impuestos: str | None = None
    col_referencia: str | None = None
    col_saldo: str | None = None
    separador_decimal: str = ","
    separador_miles: str = "."
    invertir_signo: bool = False
    rubro_comision: str | None = None
    rubro_impuestos: str | None = None
    medio_defecto: str | None = None
    orden: str = "Más nuevo arriba"
    notas: str | None = None

    @classmethod
    def desde_dict(cls, d: dict) -> "Perfil":
        campos = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        campos["separador_decimal"] = campos.get("separador_decimal") or ","
        campos["separador_miles"] = campos.get("separador_miles") or ""
        return cls(**campos)


@dataclass
class Regla:
    texto: str
    rubro: str
    prioridad: int
    tipo: str | None = None             # "Ingreso" | "Egreso" | None = ambos
    cuenta: str | None = None           # código de cuenta | None = todas
    tercero: str | None = None
    unidad_negocio: str | None = None
    medio_pago: str | None = None
    comentario: str | None = None
    cliente_id: str | None = None       # None = regla global del sistema
    id: str | None = None

    @classmethod
    def desde_dict(cls, d: dict) -> "Regla":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RegistroExtracto:
    """Una línea útil del archivo, ya interpretada con el perfil."""
    fila_origen: int
    fecha: date
    descripcion: str
    referencia: str
    principal: Decimal
    comision: Decimal
    impuestos: Decimal
    saldo: Decimal | None


@dataclass
class MovimientoPropuesto:
    """Una fila de IMP_Listo: lo que se va a volcar a T_Tesoreria si se aprueba."""
    fila_origen: int
    pata: Pata
    fecha: date
    cuenta: str
    tipo: str                           # Ingreso | Egreso
    importe: Decimal                    # siempre positivo, en la moneda de la cuenta
    descripcion: str
    referencia: str = ""
    rubro: str | None = None
    tercero: str | None = None
    unidad_negocio: str | None = None
    medio_pago: str | None = None
    comprobante: str | None = None
    regla_id: str | None = None
    regla_texto: str | None = None
    alertas: list[Alerta] = field(default_factory=list)

    @property
    def importe_firmado(self) -> Decimal:
        return self.importe if self.tipo == "Ingreso" else -self.importe

    @property
    def bloqueado(self) -> bool:
        return any(a.bloquea for a in self.alertas)


@dataclass
class MovimientoTesoreria:
    """Fila ya aprobada de T_Tesoreria (lo mínimo que necesita la detección de duplicados)."""
    cuenta: str
    fecha: date
    tipo: str
    importe: Decimal
    rubro: str
    descripcion: str = ""
    referencia: str = ""
    tercero: str | None = None
    comprobante: str | None = None
    medio_pago: str | None = None
    unidad_negocio: str | None = None
    conciliado: bool = True
    id: str | None = None

    @property
    def importe_firmado(self) -> Decimal:
        return self.importe if self.tipo == "Ingreso" else -self.importe
