"""Importación de un cliente desde la Planilla de Gestión Integral v2 (.xlsx).

Dos pasos: `leer` (no toca la base: devuelve lo que encontró, con avisos, para mostrar una vista previa) y
`aplicar` (lo carga en un cliente). Las columnas se ubican por el texto del encabezado, no por la letra, así
una planilla con columnas agregadas sigue funcionando.

Se toman los valores CALCULADOS de la planilla (Neto ARS, Total ARS, Cargas ARS): si el archivo nunca se
abrió y guardó en Excel esas celdas están vacías y se avisa en lugar de recalcular distinto.
Las filas de ejemplo de la plantilla (Observaciones con "EJEMPLO") se omiten salvo que se pida lo contrario.

Correspondencia: CONFIG → cliente · M_Cuentas → cuentas · M_Items → ítems · M_Reglas → reglas del cliente
(las que no son globales) · T_Tesoreria → tesorería aprobada · T_Ventas → comprobantes emitidos + detalle
por ítem · T_Compras → comprobantes recibidos con rubro · T_Personal → costo laboral por mes ·
T_Mermas → mermas · T_Presupuesto → base · Balance_Gestion → datos de cierre · Tablero → metas ·
Indices → índices globales (opcional y solo meses que la web no tiene).
"""
from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.api.repositorio import Cuenta
from app.finanzas.indices import FilaIndice
from app.finanzas.items import Item, LineaVenta, Merma
from app.finanzas.tablero import DatosCierre
from app.ingesta.comprobantes_arca import ComprobanteArca
from app.ingesta.f931 import DeclaracionF931
from app.ingesta.modelos import MovimientoTesoreria, Regla
from app.ingesta.reglas import normalizar as _normalizar

CERO = Decimal(0)


def normalizar(texto: str | None) -> str:
    """Sin acentos, espacios simples y en minúsculas (los rótulos de METAS están así)."""
    return _normalizar(texto).lower()
HOJAS_MINIMAS = {"CONFIG", "M_Cuentas", "T_Tesoreria"}
METAS = {"margen de contribucion %": "margen_contribucion_pct", "material cost %": "material_cost_pct",
         "people cost %": "people_cost_pct", "prime cost %": "prime_cost_pct", "ebitda %": "ebitda_pct",
         "mermas % s/ ingresos": "mermas_pct", "flujo de caja operativo": "flujo_operativo",
         "saldo de caja proyectado a 90 dias": "saldo_90_dias", "dias de cobro": "dias_cobro", "dias de pago": "dias_pago",
         "dias de stock": "dias_stock", "ciclo de caja (pmm financiero)": "pmm_ciclo_caja",
         "liquidez corriente": "liquidez_corriente", "prueba acida": "prueba_acida", "endeudamiento (pasivo / pn)": "endeudamiento"}
COTIZACIONES_INDICES = ("USD_OFICIAL", "USD_MEP", "USD_CCL", "USD_BLUE", "USDT", "EUR_OFICIAL", "BRL_OFICIAL")


class PlanillaInvalida(Exception):
    pass


@dataclass
class PlanillaV2:
    empresa: str = ""
    cuit: str = ""
    cuentas: list[Cuenta] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    reglas: list[Regla] = field(default_factory=list)
    tesoreria: list[MovimientoTesoreria] = field(default_factory=list)
    emitidos: list[tuple[ComprobanteArca, str]] = field(default_factory=list)     # (comprobante, rubro)
    lineas_venta: list[LineaVenta] = field(default_factory=list)
    recibidos: list[tuple[ComprobanteArca, str]] = field(default_factory=list)
    personal: list[DeclaracionF931] = field(default_factory=list)
    mermas: list[Merma] = field(default_factory=list)
    presupuesto: list[tuple[str, date, Decimal]] = field(default_factory=list)
    cierres: list[DatosCierre] = field(default_factory=list)
    metas: dict[str, tuple[Decimal, str]] = field(default_factory=dict)
    indices: list[FilaIndice] = field(default_factory=list)
    ejemplos_omitidos: int = 0
    avisos: list[str] = field(default_factory=list)

    def reglas_propias(self, globales: list[Regla]) -> list[Regla]:
        """Las reglas de la planilla que no son las globales del sistema (esas ya las tiene la web)."""
        ya = {(normalizar(g.texto), g.rubro) for g in globales}
        return [rg for rg in self.reglas if (normalizar(rg.texto), rg.rubro) not in ya]

    def resumen(self, globales: list[Regla] | None = None) -> dict:
        return {"empresa": self.empresa, "cuit": self.cuit, "cuentas": len(self.cuentas), "items": len(self.items),
                "reglas": len(self.reglas_propias(globales or [])), "tesoreria": len(self.tesoreria), "ventas": len(self.emitidos),
                "renglones_venta": len(self.lineas_venta), "compras": len(self.recibidos), "meses_personal": len(self.personal),
                "mermas": len(self.mermas), "celdas_presupuesto": len(self.presupuesto), "cierres": len(self.cierres),
                "metas": len(self.metas), "meses_indices": len(self.indices), "ejemplos_omitidos": self.ejemplos_omitidos,
                "avisos": self.avisos}


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


class _Hoja:
    """Filas de datos de una hoja con acceso por encabezado (prefijo normalizado)."""

    def __init__(self, ws, fila_encabezado: int):
        filas = list(ws.iter_rows(min_row=fila_encabezado, values_only=True))
        self.encabezados = [normalizar(_txt(h)) for h in (filas[0] if filas else [])]
        self.filas = [f for f in filas[1:] if any(c not in (None, "") for c in f)]

    def col(self, prefijo: str) -> int:
        p = normalizar(prefijo)
        for i, h in enumerate(self.encabezados):
            if h.startswith(p):
                return i
        raise PlanillaInvalida(f"No encuentro la columna «{prefijo}»: ¿es la planilla v2?")


def leer(contenido: bytes, omitir_ejemplos: bool = True) -> PlanillaV2:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise PlanillaInvalida(f"No se pudo abrir el Excel: {e}")
    faltan = HOJAS_MINIMAS - set(wb.sheetnames)
    if faltan:
        raise PlanillaInvalida(f"No parece la Planilla de Gestión Integral v2: faltan las hojas {', '.join(sorted(faltan))}.")
    p = PlanillaV2()
    sin_calcular: set[str] = set()

    def es_ejemplo(h: _Hoja, f) -> bool:
        try:
            obs = _txt(f[h.col("Observaciones")])
        except PlanillaInvalida:
            obs = ""
        if not obs:    # T_Tesoreria no tiene "Observaciones": el EJEMPLO va en la descripción
            try:
                obs = _txt(f[h.col("Descripción")])
            except PlanillaInvalida:
                pass
        if omitir_ejemplos and "EJEMPLO" in obs.upper():
            p.ejemplos_omitidos += 1
            return True
        return False

    # CONFIG: pares rótulo / valor
    for f in wb["CONFIG"].iter_rows(min_row=1, max_row=40, values_only=True):
        rotulo = normalizar(_txt(f[0]))
        if rotulo == "empresa":
            p.empresa = _txt(f[1])
        elif rotulo == "cuit":
            p.cuit = _txt(f[1])

    h = _Hoja(wb["M_Cuentas"], 4)
    for f in h.filas:
        codigo = _txt(f[h.col("Código")])
        if not codigo or es_ejemplo(h, f):
            continue
        p.cuentas.append(Cuenta(codigo, _txt(f[h.col("Nombre")]) or codigo, _txt(f[h.col("Tipo de cuenta")]) or "Banco - Cuenta corriente",
                                _txt(f[h.col("Moneda / cotización")]) or "ARS", _dec(f[h.col("Saldo inicial")]) or CERO))

    if "M_Items" in wb.sheetnames:
        h = _Hoja(wb["M_Items"], 4)
        for f in h.filas:
            codigo = _txt(f[h.col("Código")]).upper()
            if not codigo or es_ejemplo(h, f):
                continue
            p.items.append(Item(codigo, _txt(f[h.col("Descripción")]) or codigo, _txt(f[h.col("Tipo")]) or "Bien",
                                _txt(f[h.col("Unidad de negocio")]) or "GENERAL", _dec(f[h.col("Precio de lista")]) or CERO,
                                _txt(f[h.col("Moneda / cotiz. del precio")]) or "ARS", _dec(f[h.col("Costo unitario")]) or CERO,
                                _txt(f[h.col("Moneda / cotiz. del costo")]) or "ARS", _dec(f[h.col("Alícuota IVA")]) or Decimal("0.21")))

    if "M_Reglas" in wb.sheetnames:
        h = _Hoja(wb["M_Reglas"], 4)
        for f in h.filas:
            texto, rubro = _txt(f[h.col("Texto")]), _txt(f[h.col("Rubro")])
            if texto and rubro:
                p.reglas.append(Regla(texto=texto, rubro=rubro, prioridad=0, cuenta=_txt(f[h.col("Solo para la cuenta")]) or None,
                                      tipo=_txt(f[h.col("Solo si es")]) or None, medio_pago=_txt(f[h.col("Medio de pago")]) or None,
                                      comentario=_txt(f[h.col("Comentario")]) or None))

    h = _Hoja(wb["T_Tesoreria"], 4)
    for f in h.filas:
        fecha, importe = _fecha(f[h.col("Fecha")]), _dec(f[h.col("Importe")])
        if not fecha or importe is None or es_ejemplo(h, f):
            continue
        p.tesoreria.append(MovimientoTesoreria(
            cuenta=_txt(f[h.col("Cuenta")]), fecha=fecha, tipo=_txt(f[h.col("Tipo")]) or "Egreso", importe=abs(importe),
            rubro=_txt(f[h.col("Rubro")]), descripcion=_txt(f[h.col("Descripción")]), tercero=_txt(f[h.col("Tercero")]) or None,
            comprobante=_txt(f[h.col("Comprobante vinculado")]) or None, medio_pago=_txt(f[h.col("Medio de pago")]) or None,
            unidad_negocio=_txt(f[h.col("Unidad de negocio")]) or None, conciliado=_txt(f[h.col("Conciliado")]).upper() != "N"))

    terceros: dict[str, tuple[str, str]] = {}
    if "M_Terceros" in wb.sheetnames:
        h = _Hoja(wb["M_Terceros"], 4)
        for f in h.filas:
            if _txt(f[h.col("Código")]):
                terceros[_txt(f[h.col("Código")])] = (_txt(f[h.col("Razón social")]), _txt(f[h.col("CUIT")]))

    def contraparte(codigo: str) -> tuple[str, str]:
        nombre, cuit = terceros.get(codigo, (codigo, ""))
        return nombre or codigo, cuit or codigo     # sin CUIT, el código identifica al tercero

    if "T_Ventas" in wb.sheetnames:
        h = _Hoja(wb["T_Ventas"], 4)
        grupos: dict[tuple, list] = defaultdict(lambda: [CERO, CERO, CERO, None, False])
        for f in h.filas:
            fecha = _fecha(f[h.col("Fecha")])
            if not fecha or es_ejemplo(h, f):
                continue
            neto, iva, total = _dec(f[h.col("Neto ARS")]), _dec(f[h.col("IVA ARS")]), _dec(f[h.col("Total ARS")])
            if neto is None or total is None:
                sin_calcular.add("T_Ventas")
                continue
            comp, tipo = _txt(f[h.col("N° comprobante")]), _txt(f[h.col("Tipo de comprobante")]) or "Factura"
            nc = "credito" in normalizar(tipo)
            signo = -1 if nc else 1
            rubro = _txt(f[h.col("Rubro ingreso")]) or "ING01"
            g = grupos[(comp, tipo, _txt(f[h.col("Cliente")]), rubro)]
            g[0] += abs(neto); g[1] += abs(iva or CERO); g[2] += abs(total); g[3] = fecha; g[4] = nc
            cantidad, item = _dec(f[h.col("Cantidad")]) or CERO, _txt(f[h.col("Ítem")]).upper()
            if item and cantidad:
                p.lineas_venta.append(LineaVenta(fecha, comp, item, signo * abs(cantidad), abs(neto) / abs(cantidad)))
        rubros_por_comp = defaultdict(set)
        for (comp, _, _, rubro) in grupos:
            rubros_por_comp[comp].add(rubro)
        for (comp, tipo, cli, rubro), (neto, iva, total, fecha, nc) in grupos.items():
            nombre, cuit = contraparte(cli)
            numero = comp if len(rubros_por_comp[comp]) == 1 else f"{comp} ({rubro})"
            s = -1 if nc else 1
            p.emitidos.append((ComprobanteArca(fecha, tipo, numero, cuit, nombre, "ARS", Decimal(1), s * neto, s * iva, s * total, nc, "emitido"), rubro))

    if "T_Compras" in wb.sheetnames:
        h = _Hoja(wb["T_Compras"], 4)
        grupos = defaultdict(lambda: [CERO, CERO, CERO, None, False])
        for f in h.filas:
            fecha = _fecha(f[h.col("Fecha")])
            if not fecha or es_ejemplo(h, f):
                continue
            neto, iva, total = _dec(f[h.col("Neto ARS")]), _dec(f[h.col("IVA ARS")]), _dec(f[h.col("Total ARS")])
            if neto is None or total is None:
                sin_calcular.add("T_Compras")
                continue
            tipo = _txt(f[h.col("Tipo de comprobante")]) or "Factura"
            nc = "credito" in normalizar(tipo)
            g = grupos[(_txt(f[h.col("N° comprobante")]), tipo, _txt(f[h.col("Proveedor")]), _txt(f[h.col("Rubro")]))]
            g[0] += abs(neto); g[1] += abs(iva or CERO); g[2] += abs(total); g[3] = fecha; g[4] = nc
        rubros_por_comp = defaultdict(set)
        for (comp, _, prov, rubro) in grupos:
            rubros_por_comp[(comp, prov)].add(rubro)
        for (comp, tipo, prov, rubro), (neto, iva, total, fecha, nc) in grupos.items():
            nombre, cuit = contraparte(prov)
            numero = comp if len(rubros_por_comp[(comp, prov)]) == 1 else f"{comp} ({rubro})"
            s = -1 if nc else 1
            p.recibidos.append((ComprobanteArca(fecha, tipo, numero, cuit, nombre, "ARS", Decimal(1), s * neto, s * iva, s * total, nc, "recibido"), rubro))

    if "T_Personal" in wb.sheetnames:
        h = _Hoja(wb["T_Personal"], 4)
        por_mes: dict[date, list] = defaultdict(lambda: [CERO, CERO, set()])
        otros_rubros = 0
        for f in h.filas:
            mes = _fecha(f[h.col("Mes (1")])
            if not mes or es_ejemplo(h, f):
                continue
            rubro = _txt(f[h.col("Rubro efectivo")]) or _txt(f[h.col("Rubro (vacío")]) or "PER01"
            if rubro != "PER01":
                otros_rubros += 1
            cargas = _dec(f[h.col("Cargas ARS")])
            if cargas is None:
                sin_calcular.add("T_Personal")
                continue
            bruto = (_dec(f[h.col("Sueldo bruto")]) or CERO) + (_dec(f[h.col("Adicionales")]) or CERO) + (_dec(f[h.col("Provisión SAC")]) or CERO)
            m = por_mes[mes.replace(day=1)]
            m[0] += bruto; m[1] += cargas; m[2].add(_txt(f[h.col("Colaborador")]))
        for mes, (rem, cargas, gente) in sorted(por_mes.items()):
            p.personal.append(DeclaracionF931(cuit=p.cuit, periodo=mes, empleados=len(gente),
                                              importes={"remuneracion_total": rem, "contribuciones_ss": cargas}))
        if otros_rubros:
            p.avisos.append(f"{otros_rubros} renglones de personal con rubro distinto de PER01 (por ejemplo sueldo de socios) "
                            "se suman al costo laboral (PER01).")

    if "T_Mermas" in wb.sheetnames:
        h = _Hoja(wb["T_Mermas"], 4)
        for f in h.filas:
            fecha, cant = _fecha(f[h.col("Fecha")]), _dec(f[h.col("Cantidad")])
            if fecha and cant and not es_ejemplo(h, f):
                p.mermas.append(Merma(fecha, _txt(f[h.col("Ítem")]).upper(), cant, _txt(f[h.col("Causa")]) or "Otra",
                                      _txt(f[h.col("Turno")])))

    if "T_Presupuesto" in wb.sheetnames:
        filas = list(wb["T_Presupuesto"].iter_rows(min_row=5, values_only=True))
        meses = [(i, _fecha(v)) for i, v in enumerate(filas[0]) if _fecha(v)] if filas else []
        for f in filas[1:]:
            codigo = _txt(f[0])
            if not codigo or len(codigo) > 8:
                continue
            for i, mes in meses:
                v = _dec(f[i]) if i < len(f) else None
                if v:
                    p.presupuesto.append((codigo, mes.replace(day=1), v))

    if "Balance_Gestion" in wb.sheetnames:
        h = _Hoja(wb["Balance_Gestion"], 5)
        for f in h.filas:
            mes = _fecha(f[h.col("Mes")])
            if not mes:
                continue
            v = [_dec(f[h.col(c)]) or CERO for c in ("Stock", "Bienes de uso", "Otros activos", "Deudas financieras",
                                                      "Deudas fiscales", "Otros pasivos", "Amortización")]
            if any(v):
                p.cierres.append(DatosCierre(mes.replace(day=1), *v))

    if "Tablero" in wb.sheetnames:
        for f in wb["Tablero"].iter_rows(min_row=7, values_only=True):
            clave = METAS.get(normalizar(_txt(f[0])))
            meta = _dec(f[7]) if len(f) > 8 else None
            if clave and meta is not None and _txt(f[8]) in ("≥", "≤"):
                p.metas[clave] = (meta, _txt(f[8]))

    if "Indices" in wb.sheetnames:
        h = _Hoja(wb["Indices"], 5)
        for f in h.filas:
            mes = _fecha(f[h.col("Mes")])
            if not mes:
                continue
            tc = {}
            for cot in COTIZACIONES_INDICES:
                try:
                    v = _dec(f[h.col(cot)])
                except PlanillaInvalida:
                    continue
                if v and v > 0:
                    tc[cot] = v
            p.indices.append(FilaIndice(mes.replace(day=1), _dec(f[h.col("IPC %")]), _dec(f[h.col("Paritaria")]),
                                        _dec(f[h.col("Tarifas")]), tc))

    for hoja in sorted(sin_calcular):
        p.avisos.append(f"{hoja}: hay filas sin los importes calculados. Abrí la planilla en Excel, guardala y volvé a "
                        "subirla (los archivos generados por otros programas no traen los resultados de las fórmulas).")
    if p.ejemplos_omitidos:
        p.avisos.append(f"Se omitieron {p.ejemplos_omitidos} filas marcadas como EJEMPLO en Observaciones.")
    return p


def aplicar(r, cliente_id: str, p: PlanillaV2, documento_id: str, reglas_globales: list[Regla],
            importar_indices: bool = False) -> dict:
    """Carga lo leído en un cliente (pensado para un cliente nuevo: no borra lo que ya tenga)."""
    hecho: dict[str, int] = defaultdict(int)
    existentes = r.cuentas(cliente_id)
    for c in p.cuentas:
        if c.codigo not in existentes:
            r.agregar_cuenta(cliente_id, c)
            hecho["cuentas"] += 1
    for it in p.items:
        r.guardar_item(cliente_id, it)
        hecho["items"] += 1
    prioridad = max((x.prioridad for x in r.reglas_cliente(cliente_id)), default=0)
    for rg in p.reglas_propias(reglas_globales):
        prioridad += 10
        rg.prioridad, rg.cliente_id = prioridad, cliente_id
        r.agregar_regla(rg)
        hecho["reglas"] += 1
    if p.tesoreria:
        r.insertar_tesoreria(cliente_id, p.tesoreria)
        hecho["tesoreria"] = len(p.tesoreria)
    for sentido, lista in (("emitido", p.emitidos), ("recibido", p.recibidos)):
        if not lista:
            continue
        nuevos, _ = r.guardar_comprobantes(cliente_id, documento_id, [c for c, _ in lista])
        hecho["ventas" if sentido == "emitido" else "compras"] = nuevos
        rubro_de = {(c.comprobante, c.doc_contraparte): rubro for c, rubro in lista}
        for reg in r.comprobantes(cliente_id, sentido):
            rubro = rubro_de.get((reg.comprobante, reg.cuit))
            if rubro and reg.rubro != rubro and (sentido == "recibido" or rubro != "ING01"):
                r.asignar_rubro(cliente_id, reg.id, rubro, False)
    if p.lineas_venta:
        hecho["renglones_venta"], _ = r.guardar_lineas_venta(cliente_id, documento_id, p.lineas_venta)
    for dj in p.personal:
        r.guardar_f931(cliente_id, documento_id, dj)
        hecho["meses_personal"] += 1
    for m in p.mermas:
        r.registrar_merma(cliente_id, m)
        hecho["mermas"] += 1
    if p.presupuesto:
        r.guardar_presupuesto(cliente_id, p.presupuesto)
        hecho["celdas_presupuesto"] = len(p.presupuesto)
    for c in p.cierres:
        r.guardar_cierre(cliente_id, c)
        hecho["cierres"] += 1
    for clave, (meta, direccion) in p.metas.items():
        r.guardar_meta(cliente_id, clave, meta, direccion)
        hecho["metas"] += 1
    if importar_indices:
        ya = {f.mes for f in r.indices()}
        for fila in p.indices:
            if fila.mes not in ya:
                r.guardar_indice(fila)
                hecho["meses_indices"] += 1
    return dict(hecho)
