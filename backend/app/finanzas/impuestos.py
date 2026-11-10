"""Proyección impositiva de gestión (estimativa, no reemplaza la liquidación del contador).

  * IVA:       débito (IVA de comprobantes emitidos) − crédito (IVA de recibidos), mes a mes, arrastrando el
               saldo técnico a favor. No incluye percepciones, retenciones ni saldo de libre disponibilidad.
  * IIBB:      ventas netas del mes × alícuota (una sola alícuota; no contempla convenio multilateral ni
               retenciones/percepciones sufridas).
  * Ganancias: resultado antes de impuestos acumulado del período × tasa (una sola tasa; por defecto 35 %,
               la marginal máxima de sociedades). Se anualiza para estimar el impuesto del ejercicio.
  * Proyección de los próximos meses: promedio de los últimos 3 meses con datos.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

CERO = Decimal(0)
DOS = Decimal("0.01")


def _sumar_mes(m: date, n: int) -> date:
    t = m.year * 12 + m.month - 1 + n
    return date(t // 12, t % 12 + 1, 1)


def impuestos_mensuales(comprobantes: Iterable, bai_por_mes: dict[date, Decimal], alicuota_iibb: Decimal,
                        tasa_ganancias: Decimal, meses_proyeccion: int = 3) -> dict:
    debito: dict[date, Decimal] = {}
    credito: dict[date, Decimal] = {}
    ventas: dict[date, Decimal] = {}
    for c in comprobantes:
        mes = c.fecha.replace(day=1)
        if c.sentido == "emitido":
            debito[mes] = debito.get(mes, CERO) + c.iva_ars
            ventas[mes] = ventas.get(mes, CERO) + c.neto_ars
        else:
            credito[mes] = credito.get(mes, CERO) + c.iva_ars
    meses = sorted(set(debito) | set(credito) | set(ventas) | set(bai_por_mes))
    filas, a_favor, bai_acum = [], CERO, CERO
    for m in meses:
        d, cr = debito.get(m, CERO), credito.get(m, CERO)
        saldo = d - cr - a_favor
        iva_pagar = max(saldo, CERO)
        a_favor = max(-saldo, CERO)
        iibb = (max(ventas.get(m, CERO), CERO) * alicuota_iibb).quantize(DOS)
        bai_acum += bai_por_mes.get(m) or CERO
        filas.append({"mes": m, "debito_iva": d, "credito_iva": cr, "iva_a_pagar": iva_pagar, "saldo_a_favor": a_favor,
                      "ventas_netas": ventas.get(m, CERO), "iibb": iibb, "bai": bai_por_mes.get(m) or CERO,
                      "total": iva_pagar + iibb, "proyectado": False})

    reales = filas[-3:]
    proyeccion = []
    if reales:
        n = Decimal(len(reales))
        prom = lambda k: (sum((f[k] for f in reales), CERO) / n).quantize(DOS)
        d, cr, v = prom("debito_iva"), prom("credito_iva"), prom("ventas_netas")
        for i in range(1, meses_proyeccion + 1):
            m = _sumar_mes(filas[-1]["mes"], i)
            saldo = d - cr - a_favor
            iva_pagar, a_favor = max(saldo, CERO), max(-saldo, CERO)
            iibb = (max(v, CERO) * alicuota_iibb).quantize(DOS)
            proyeccion.append({"mes": m, "debito_iva": d, "credito_iva": cr, "iva_a_pagar": iva_pagar, "saldo_a_favor": a_favor,
                               "ventas_netas": v, "iibb": iibb, "bai": None, "total": iva_pagar + iibb, "proyectado": True})

    meses_bai = sum(1 for m in meses if m in bai_por_mes)
    anual = (bai_acum / meses_bai * 12).quantize(DOS) if meses_bai else None
    ganancias = {"bai_acumulado": bai_acum, "meses": meses_bai, "bai_anualizado": anual, "tasa": tasa_ganancias,
                 "impuesto_acumulado": (max(bai_acum, CERO) * tasa_ganancias).quantize(DOS),
                 "impuesto_anual_estimado": (max(anual, CERO) * tasa_ganancias).quantize(DOS) if anual is not None else None}
    return {"meses": filas, "proyeccion": proyeccion, "ganancias": ganancias,
            "alicuota_iibb": alicuota_iibb, "saldo_tecnico_a_favor": a_favor}
