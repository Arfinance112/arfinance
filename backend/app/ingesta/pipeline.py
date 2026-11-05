"""Orquestación de la ingesta: archivo subido → lote de movimientos propuestos (la grilla IMP_Listo)."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.ingesta import comprobantes_arca, detalle_ventas, f931
from app.ingesta.duplicados import marcar_duplicados
from app.ingesta.lectores import ArchivoLeido
from app.ingesta.modelos import Alerta, MovimientoPropuesto, MovimientoTesoreria, Perfil
from app.ingesta.perfiles import abrir_patas, leer_registros, puntuar_perfil, saldo_final
from app.ingesta.reglas import MotorReglas

# qué tipo de perfil conviene probar primero según el tipo de cuenta destino
_AFINIDAD = {
    "Billetera": "Billetera virtual / PSP", "Procesador": "Procesador de pagos",
    "Tarjeta": "Tarjeta de crédito", "Broker": "Broker / exchange", "Exchange": "Broker / exchange",
}


@dataclass
class ResultadoImportacion:
    tipo_documento: str                          # extracto | f931 | mis_comprobantes
    perfil: Perfil | None = None
    perfil_autodetectado: bool = False
    filas_leidas: int = 0
    filas_descartadas: int = 0
    movimientos: list[MovimientoPropuesto] = field(default_factory=list)
    saldo_extracto: Decimal | None = None
    fecha_ultima: date | None = None
    f931: f931.DeclaracionF931 | None = None
    comprobantes: list[comprobantes_arca.ComprobanteArca] = field(default_factory=list)

    def resumen(self) -> dict:
        cuenta = lambda a: sum(1 for m in self.movimientos if a in m.alertas)
        return {
            "movimientos": len(self.movimientos),
            "sin_regla": cuenta(Alerta.SIN_REGLA),
            "rubro_inexistente": cuenta(Alerta.RUBRO_INEXISTENTE),
            "duplicados": cuenta(Alerta.POSIBLE_DUPLICADO) + cuenta(Alerta.DUPLICADO_EXACTO),
            "sin_comprobante": cuenta(Alerta.SIN_COMPROBANTE),
            "listos": sum(1 for m in self.movimientos if not m.bloqueado),
        }


def tipo_documento(archivo: ArchivoLeido) -> str:
    if archivo.extension == ".pdf" and f931.es_f931(archivo.texto):
        return "f931"
    if comprobantes_arca.es_mis_comprobantes(archivo.filas):
        return "mis_comprobantes"
    if detalle_ventas.es_detalle_ventas(archivo.filas):
        return "detalle_ventas"
    return "extracto"


def elegir_perfil(filas, perfiles: list[Perfil], tipo_cuenta: str = "") -> Perfil:
    """El perfil que interpreta más filas; ante empate, el afín al tipo de cuenta y después el primero."""
    afin = next((v for k, v in _AFINIDAD.items() if k.lower() in tipo_cuenta.lower()), None)
    return max(perfiles, key=lambda p: (round(puntuar_perfil(filas, p), 4), p.tipo_origen == afin,
                                        -perfiles.index(p)))


def marcar_informativas(mov: MovimientoPropuesto, rubro_cobro: str, rubro_pago: str) -> None:
    mov.alertas = [a for a in mov.alertas if a is not Alerta.SIN_COMPROBANTE]
    if mov.rubro in (rubro_cobro, rubro_pago) and not mov.comprobante:
        mov.alertas.append(Alerta.SIN_COMPROBANTE)


def procesar_extracto(archivo: ArchivoLeido, cuenta: str, perfiles: list[Perfil], motor: MotorReglas,
                      rubros_validos: set[str], existentes: Iterable[MovimientoTesoreria],
                      perfil: Perfil | None = None, tipo_cuenta: str = "",
                      rubro_cobro: str = "COB01", rubro_pago: str = "PAG01") -> ResultadoImportacion:
    auto = perfil is None
    perfil = perfil or elegir_perfil(archivo.filas, perfiles, tipo_cuenta)
    registros, descartadas = leer_registros(archivo.filas, perfil)
    movimientos = [m for r in registros for m in abrir_patas(r, perfil, cuenta)]
    for m in movimientos:
        motor.clasificar(m, rubros_validos)
        marcar_informativas(m, rubro_cobro, rubro_pago)
    marcar_duplicados(movimientos, existentes)
    return ResultadoImportacion(
        tipo_documento="extracto", perfil=perfil, perfil_autodetectado=auto,
        filas_leidas=len(archivo.filas), filas_descartadas=descartadas, movimientos=movimientos,
        saldo_extracto=saldo_final(registros, perfil),
        fecha_ultima=max((r.fecha for r in registros), default=None))


def reprocesar(resultado: ResultadoImportacion, motor: MotorReglas, rubros_validos: set[str],
               existentes: Iterable[MovimientoTesoreria], rubro_cobro: str = "COB01",
               rubro_pago: str = "PAG01") -> None:
    """Vuelve a clasificar un lote abierto (por ejemplo después de crear una regla nueva).
    Respeta las asignaciones manuales: solo se reclasifican movimientos sin rubro."""
    for m in resultado.movimientos:
        motor.clasificar(m, rubros_validos)
        marcar_informativas(m, rubro_cobro, rubro_pago)
    marcar_duplicados(resultado.movimientos, existentes)
