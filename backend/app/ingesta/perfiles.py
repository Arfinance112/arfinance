"""Aplicación de perfiles de extracto: de filas crudas a registros y de registros a patas."""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.core.numeros import parse_fecha, parse_numero
from app.ingesta.modelos import MovimientoPropuesto, Pata, Perfil, RegistroExtracto


def _col(letra: str | None) -> int | None:
    """'A' → 0 ... 'Z' → 25, 'AA' → 26. Vacío → None."""
    if not letra:
        return None
    n = 0
    for ch in letra.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _celda(fila: Sequence, letra: str | None):
    i = _col(letra)
    if i is None or i >= len(fila):
        return None
    return fila[i]


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def leer_registros(filas: Sequence[Sequence], perfil: Perfil) -> tuple[list[RegistroExtracto], int]:
    """Interpreta cada fila con el perfil. Las filas sin fecha válida o sin importe (títulos,
    totales, renglones vacíos) se descartan y se cuentan."""
    num = lambda v: parse_numero(v, perfil.separador_decimal, perfil.separador_miles)
    registros: list[RegistroExtracto] = []
    descartadas = 0
    for i, fila in enumerate(filas, start=1):
        fecha = parse_fecha(_celda(fila, perfil.col_fecha), perfil.formato_fecha)
        if fecha is None:
            descartadas += 1
            continue
        if perfil.modo_importe == "Débito / Crédito separados":
            principal = abs(num(_celda(fila, perfil.col_credito))) - abs(num(_celda(fila, perfil.col_debito)))
        elif perfil.modo_importe == "Importe + columna de tipo":
            base = abs(num(_celda(fila, perfil.col_importe)))
            marca = _texto(_celda(fila, perfil.col_tipo)).upper()
            egreso = bool(perfil.texto_egreso) and perfil.texto_egreso.upper() in marca
            principal = -base if egreso else base
        else:
            principal = num(_celda(fila, perfil.col_importe))
        if perfil.invertir_signo:
            principal = -principal
        comision = num(_celda(fila, perfil.col_comision)) if perfil.col_comision else Decimal(0)
        impuestos = num(_celda(fila, perfil.col_impuestos)) if perfil.col_impuestos else Decimal(0)
        if principal == 0 and comision == 0 and impuestos == 0:
            descartadas += 1
            continue
        descripcion = " ".join(x for x in (_texto(_celda(fila, perfil.col_descripcion)),
                                           _texto(_celda(fila, perfil.col_descripcion2))) if x)
        saldo = num(_celda(fila, perfil.col_saldo)) if perfil.col_saldo else None
        registros.append(RegistroExtracto(i, fecha, descripcion, _texto(_celda(fila, perfil.col_referencia)),
                                          principal, comision, impuestos, saldo))
    return registros, descartadas


def abrir_patas(registro: RegistroExtracto, perfil: Perfil, cuenta: str) -> list[MovimientoPropuesto]:
    """Un registro de billetera o procesador se abre en hasta 3 movimientos: el principal (bruto),
    la comisión y los impuestos/retenciones. En una devolución (principal negativo) la comisión se revierte."""
    signo_principal = -1 if registro.principal < 0 else 1
    patas = [
        (Pata.PRINCIPAL, registro.principal, None, ""),
        (Pata.COMISION, -abs(registro.comision) * signo_principal, perfil.rubro_comision, " · comisión"),
        (Pata.IMPUESTOS, -abs(registro.impuestos) * signo_principal, perfil.rubro_impuestos, " · impuestos / retenciones"),
    ]
    salida = []
    for pata, importe, rubro, sufijo in patas:
        if importe == 0:
            continue
        salida.append(MovimientoPropuesto(
            fila_origen=registro.fila_origen, pata=pata, fecha=registro.fecha, cuenta=cuenta,
            tipo="Egreso" if importe < 0 else "Ingreso", importe=abs(importe),
            descripcion=registro.descripcion + sufijo, referencia=registro.referencia,
            rubro=rubro, medio_pago=perfil.medio_defecto,
            regla_texto=None if pata is Pata.PRINCIPAL else f"Perfil: {pata.value}"))
    return salida


def orden_por_saldos(registros: list[RegistroExtracto]) -> str | None:
    """Deduce el orden del archivo de la cadena de saldos: si cada saldo es el de la fila de ARRIBA más el
    importe, lo más viejo está arriba; si es el de la fila de ABAJO, lo más nuevo. None si no se puede decidir."""
    con_saldo = [r for r in registros if r.saldo is not None]
    neto = lambda r: r.principal + r.comision + r.impuestos
    arriba = sum(abs(b.saldo - a.saldo - neto(b)) < Decimal("0.01") for a, b in zip(con_saldo, con_saldo[1:]))
    abajo = sum(abs(a.saldo - b.saldo - neto(a)) < Decimal("0.01") for a, b in zip(con_saldo, con_saldo[1:]))
    if arriba == abajo:
        return None
    return "Más viejo arriba" if arriba > abajo else "Más nuevo arriba"


def saldo_final(registros: list[RegistroExtracto], perfil: Perfil) -> Decimal | None:
    """Saldo del último movimiento del extracto. El orden se deduce de los saldos (cada banco ordena a su
    manera y un perfil genérico no lo sabe); si no alcanza para decidir, se usa el del perfil."""
    con_saldo = [r for r in registros if r.saldo is not None]
    if not con_saldo:
        return None
    orden = orden_por_saldos(con_saldo) or perfil.orden
    ultima = max(r.fecha for r in con_saldo)
    del_dia = [r for r in con_saldo if r.fecha == ultima]
    return (del_dia[-1] if orden == "Más viejo arriba" else del_dia[0]).saldo


def puntuar_perfil(filas: Sequence[Sequence], perfil: Perfil) -> float:
    """Qué tan bien encaja un perfil con el archivo: proporción de filas que interpreta."""
    if not filas:
        return 0.0
    registros, _ = leer_registros(filas, perfil)
    return len(registros) / len(filas)
