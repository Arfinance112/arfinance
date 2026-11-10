"""Persistencia detrás de una interfaz. RepositorioMemoria sirve para tests y demo;
RepositorioPostgres (app/db/repositorio_pg.py) implementa las mismas operaciones sobre db/migraciones."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.finanzas.asientos import ComprobanteRegistrado, CostoLaboral
from app.finanzas.indices import FilaIndice
from app.finanzas.inversiones import MovInversion
from app.finanzas.items import Item, LineaCompra, LineaVenta, Merma
from app.finanzas.plan_cuentas import CuentaContable
from app.finanzas.tablero import DatosCierre
from app.ingesta.comprobantes_arca import ComprobanteArca
from app.ingesta.f931 import DeclaracionF931
from app.ingesta.modelos import MovimientoTesoreria, Regla
from app.ingesta.pipeline import ResultadoImportacion


DIAS_RECUPERO = 30


@dataclass
class Cliente:
    id: str
    nombre: str
    cuit: str = ""
    organizacion_id: str = ""
    creado: datetime = field(default_factory=datetime.now)
    archivado_en: datetime | None = None       # archivado: no se ve; se recupera durante DIAS_RECUPERO días


@dataclass
class Cuenta:
    codigo: str
    nombre: str
    tipo: str
    cotizacion: str = "ARS"
    saldo_inicial: Decimal = Decimal(0)
    fecha_saldo_inicial: date | None = None
    perfil_defecto: str | None = None


@dataclass
class Lote:
    id: str
    cliente_id: str
    cuenta: str
    documento: str
    resultado: ResultadoImportacion
    estado: str = "pendiente"          # pendiente | aprobado | descartado
    sha256: str = ""
    tamano_bytes: int = 0
    storage_path: str = ""
    creado: datetime = field(default_factory=datetime.now)


@dataclass
class Documento:
    """Archivo subido. Los extractos además generan un lote; F.931 y Mis Comprobantes solo se registran."""
    id: str
    cliente_id: str
    nombre: str
    tipo: str                      # extracto | f931 | mis_comprobantes
    estado: str                    # pendiente | procesado | con_alertas | error
    sha256: str
    tamano_bytes: int
    storage_path: str
    lote_id: str | None = None
    detalle: str = ""
    subido_en: datetime = field(default_factory=datetime.now)


ROLES = ("admin", "consultor", "carga", "lectura")


@dataclass
class Miembro:
    usuario_id: str
    email: str
    rol: str


MAX_INTENTOS = 3


@dataclass
class Trabajo:
    """Tarea en segundo plano (archivos grandes; en 4b, OCR). Estados: pendiente → procesando → hecho | error."""
    id: str
    cliente_id: str
    tipo: str
    parametros: dict
    estado: str = "pendiente"
    intentos: int = 0
    resultado: dict | None = None
    error: str | None = None
    creado: datetime = field(default_factory=datetime.now)
    actualizado: datetime = field(default_factory=datetime.now)


class Repositorio(Protocol):
    # acceso
    def alta_usuario(self, usuario_id: str, email: str, organizacion: str) -> str: ...
    def organizacion_de(self, usuario_id: str) -> str | None: ...
    def puede_ver_cliente(self, usuario_id: str, cliente_id: str) -> bool: ...
    # miembros de la organización y sus roles (admin | consultor | carga | lectura)
    def rol_de(self, usuario_id: str) -> str | None: ...
    def miembros(self, organizacion_id: str) -> list[Miembro]: ...
    def agregar_miembro(self, organizacion_id: str, usuario_id: str, email: str, rol: str) -> None: ...
    def cambiar_rol(self, organizacion_id: str, usuario_id: str, rol: str) -> None: ...
    def quitar_miembro(self, organizacion_id: str, usuario_id: str) -> None: ...
    # clientes y maestros
    def crear_cliente(self, organizacion_id: str, nombre: str, cuit: str) -> Cliente: ...
    def clientes(self, usuario_id: str) -> list[Cliente]: ...
    def cliente(self, cliente_id: str) -> Cliente | None: ...
    def archivar_cliente(self, cliente_id: str) -> None: ...
    def restaurar_cliente(self, cliente_id: str) -> bool: ...
    def clientes_archivados(self, usuario_id: str) -> list[Cliente]: ...
    # inversiones (paso 5)
    def movs_inversion(self, cliente_id: str) -> list[MovInversion]: ...
    def guardar_mov_inversion(self, cliente_id: str, mov: MovInversion) -> MovInversion: ...
    def borrar_mov_inversion(self, cliente_id: str, mov_id: str) -> bool: ...
    def agregar_cuenta(self, cliente_id: str, cuenta: Cuenta) -> Cuenta: ...
    def cuentas(self, cliente_id: str) -> dict[str, Cuenta]: ...
    def agregar_regla(self, regla: Regla) -> Regla: ...
    def reglas_cliente(self, cliente_id: str) -> list[Regla]: ...
    # ingesta
    def documento_existe(self, cliente_id: str, sha256: str) -> bool: ...
    def registrar_documento(self, doc: Documento) -> Documento: ...
    def documentos(self, cliente_id: str) -> list[Documento]: ...
    def documento(self, documento_id: str) -> Documento | None: ...
    def borrar_documento(self, documento_id: str) -> None: ...
    def guardar_lote(self, lote: Lote) -> Lote: ...
    def actualizar_lote(self, lote: Lote) -> None: ...
    def lote(self, lote_id: str) -> Lote | None: ...
    def lotes(self, cliente_id: str, estado: str | None = None) -> list[Lote]: ...
    # tesorería
    def tesoreria(self, cliente_id: str) -> list[MovimientoTesoreria]: ...
    def insertar_tesoreria(self, cliente_id: str, movimientos: list[MovimientoTesoreria], lote_id: str | None = None) -> None: ...
    # devengado (fase 2a)
    def guardar_comprobantes(self, cliente_id: str, documento_id: str, comps: list[ComprobanteArca]) -> tuple[int, int]: ...
    def comprobantes(self, cliente_id: str, sentido: str | None = None, sin_rubro: bool = False) -> list[ComprobanteRegistrado]: ...
    def asignar_rubro(self, cliente_id: str, comprobante_id: str, rubro: str, recordar: bool) -> int: ...
    def clasificar_comprobante(self, cliente_id: str, comprobante_id: str, unidad_negocio: str | None,
                               centro_costo: str | None, mismo_cuit: bool) -> int: ...
    def guardar_f931(self, cliente_id: str, documento_id: str, dj: DeclaracionF931) -> None: ...
    def costos_laborales(self, cliente_id: str) -> list[CostoLaboral]: ...
    def indices(self) -> list[FilaIndice]: ...
    def guardar_indice(self, fila: FilaIndice) -> None: ...
    # presupuesto (fase 2b): base a precios de enero, por rubro y mes; nota = explicación del desvío
    def presupuesto(self, cliente_id: str, anio: int) -> dict[tuple[str, date], Decimal]: ...
    def guardar_presupuesto(self, cliente_id: str, filas: list[tuple[str, date, Decimal | None]]) -> None: ...
    def notas_desvio(self, cliente_id: str, anio: int) -> dict[tuple[str, date], str]: ...
    def guardar_nota_desvio(self, cliente_id: str, rubro: str, mes: date, nota: str) -> None: ...
    # ítems, ventas por ítem y mermas (fase 2c)
    def items(self, cliente_id: str) -> dict[str, Item]: ...
    def guardar_item(self, cliente_id: str, item: Item) -> Item: ...
    def guardar_lineas_venta(self, cliente_id: str, documento_id: str, lineas: list[LineaVenta]) -> tuple[int, int]: ...
    def lineas_venta(self, cliente_id: str) -> list[LineaVenta]: ...
    def guardar_lineas_compra(self, cliente_id: str, documento_id: str, lineas: list[LineaCompra]) -> tuple[int, int]: ...
    def lineas_compra(self, cliente_id: str) -> list[LineaCompra]: ...
    def registrar_merma(self, cliente_id: str, merma: Merma) -> Merma: ...
    def mermas(self, cliente_id: str) -> list[Merma]: ...
    # tablero (fase 3)
    def cierres(self, cliente_id: str) -> dict[date, DatosCierre]: ...
    def guardar_cierre(self, cliente_id: str, cierre: DatosCierre) -> None: ...
    def metas(self, cliente_id: str) -> dict[str, tuple[Decimal | None, str]]: ...
    def guardar_meta(self, cliente_id: str, kpi: str, meta: Decimal | None, direccion: str) -> None: ...
    # plan de cuentas contable y vínculo rubro → cuenta
    def plan_cuentas(self, cliente_id: str) -> dict[str, CuentaContable]: ...
    def iniciar_plan(self, cliente_id: str, cuentas: list[CuentaContable]) -> None: ...
    def guardar_cuenta_contable(self, cliente_id: str, cuenta: CuentaContable) -> None: ...
    def borrar_cuenta_contable(self, cliente_id: str, codigo: str) -> None: ...
    def rubro_cuenta(self, cliente_id: str) -> dict[str, str]: ...
    def vincular_rubro(self, cliente_id: str, rubro: str, cuenta: str | None) -> None: ...
    # cola de trabajos (fase 4a)
    def encolar(self, cliente_id: str, tipo: str, parametros: dict) -> Trabajo: ...
    def tomar_trabajo(self, worker: str) -> Trabajo | None: ...
    def terminar_trabajo(self, trabajo_id: str, resultado: dict | None, error: str | None, reintentar: bool = False) -> None: ...
    def trabajo(self, trabajo_id: str) -> Trabajo | None: ...
    def estado_cola(self) -> dict[str, int]: ...


class RepositorioMemoria:
    """Todo en memoria. Un único usuario de desarrollo con acceso a toda su organización."""

    def __init__(self) -> None:
        self._orgs: dict[str, str] = {}                    # usuario → organización
        self._roles: dict[str, str] = {}                   # usuario → rol en su organización
        self._emails: dict[str, str] = {}
        self._clientes: dict[str, Cliente] = {}
        self._cuentas: dict[str, dict[str, Cuenta]] = {}
        self._reglas: dict[str, list[Regla]] = {}
        self._lotes: dict[str, Lote] = {}
        self._docs: dict[str, Documento] = {}
        self._comps: dict[str, dict[tuple, ComprobanteRegistrado]] = {}
        self._rubro_tercero: dict[str, dict[str, str]] = {}
        self._f931: dict[str, dict[date, CostoLaboral]] = {}
        self._indices: dict[date, FilaIndice] = {}
        self._ppto: dict[str, dict[tuple[str, date], Decimal]] = {}
        self._notas: dict[str, dict[tuple[str, date], str]] = {}
        self._items: dict[str, dict[str, Item]] = {}
        self._ventas: dict[str, dict[tuple, LineaVenta]] = {}
        self._compras_item: dict[str, dict[tuple, LineaCompra]] = {}
        self._inversiones: dict[str, list[MovInversion]] = {}
        self._mermas: dict[str, list[Merma]] = {}
        self._cierres: dict[str, dict[date, DatosCierre]] = {}
        self._metas: dict[str, dict[str, tuple[Decimal | None, str]]] = {}
        self._tesoreria: dict[str, list[MovimientoTesoreria]] = {}
        self._trabajos: dict[str, Trabajo] = {}
        self._origen: dict[str, list[tuple]] = {}           # documento → registros cargados desde él
        self._plan: dict[str, dict[str, CuentaContable]] = {}
        self._rubro_cuenta: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def alta_usuario(self, usuario_id: str, email: str, organizacion: str) -> str:
        if usuario_id not in self._orgs:
            self._roles[usuario_id], self._emails[usuario_id] = "admin", email
        return self._orgs.setdefault(usuario_id, uuid.uuid4().hex[:12])

    def rol_de(self, usuario_id: str) -> str | None:
        return self._roles.get(usuario_id) if usuario_id in self._orgs else None

    def miembros(self, organizacion_id: str) -> list[Miembro]:
        return sorted((Miembro(u, self._emails.get(u, ""), self._roles.get(u, "lectura"))
                       for u, o in self._orgs.items() if o == organizacion_id), key=lambda m: m.email)

    def agregar_miembro(self, organizacion_id: str, usuario_id: str, email: str, rol: str) -> None:
        if self._orgs.get(usuario_id, organizacion_id) != organizacion_id:
            raise ValueError("Ese usuario ya pertenece a otra organización.")
        self._orgs[usuario_id], self._roles[usuario_id], self._emails[usuario_id] = organizacion_id, rol, email

    def cambiar_rol(self, organizacion_id: str, usuario_id: str, rol: str) -> None:
        if self._orgs.get(usuario_id) == organizacion_id:
            self._roles[usuario_id] = rol

    def quitar_miembro(self, organizacion_id: str, usuario_id: str) -> None:
        if self._orgs.get(usuario_id) == organizacion_id:
            del self._orgs[usuario_id]
            self._roles.pop(usuario_id, None)

    def organizacion_de(self, usuario_id: str) -> str | None:
        return self._orgs.get(usuario_id)

    def puede_ver_cliente(self, usuario_id: str, cliente_id: str) -> bool:
        c = self._clientes.get(cliente_id)
        return bool(c) and c.organizacion_id == self._orgs.get(usuario_id)

    def crear_cliente(self, organizacion_id: str, nombre: str, cuit: str) -> Cliente:
        c = Cliente(id=uuid.uuid4().hex[:12], nombre=nombre, cuit=cuit, organizacion_id=organizacion_id)
        self._clientes[c.id] = c
        self._cuentas[c.id], self._reglas[c.id], self._tesoreria[c.id] = {}, [], []
        return c

    def clientes(self, usuario_id: str) -> list[Cliente]:
        return [c for c in self._clientes.values() if c.organizacion_id == self._orgs.get(usuario_id) and not c.archivado_en]

    def archivar_cliente(self, cliente_id: str) -> None:
        self._clientes[cliente_id].archivado_en = datetime.now()

    def restaurar_cliente(self, cliente_id: str) -> bool:
        c = self._clientes.get(cliente_id)
        if not c or not c.archivado_en or datetime.now() - c.archivado_en > timedelta(days=DIAS_RECUPERO):
            return False
        c.archivado_en = None
        return True

    def clientes_archivados(self, usuario_id: str) -> list[Cliente]:
        limite = datetime.now() - timedelta(days=DIAS_RECUPERO)
        return sorted((c for c in self._clientes.values() if c.organizacion_id == self._orgs.get(usuario_id)
                       and c.archivado_en and c.archivado_en > limite), key=lambda c: c.archivado_en, reverse=True)

    def movs_inversion(self, cliente_id: str) -> list[MovInversion]:
        return sorted(self._inversiones.get(cliente_id, []), key=lambda m: (m.fecha, m.id))

    def guardar_mov_inversion(self, cliente_id: str, mov: MovInversion) -> MovInversion:
        mov.id = uuid.uuid4().hex[:12]
        self._inversiones.setdefault(cliente_id, []).append(mov)
        return mov

    def borrar_mov_inversion(self, cliente_id: str, mov_id: str) -> bool:
        antes = self._inversiones.get(cliente_id, [])
        self._inversiones[cliente_id] = [m for m in antes if m.id != mov_id]
        return len(antes) != len(self._inversiones[cliente_id])

    def cliente(self, cliente_id: str) -> Cliente | None:
        return self._clientes.get(cliente_id)

    def agregar_cuenta(self, cliente_id: str, cuenta: Cuenta) -> Cuenta:
        self._cuentas[cliente_id][cuenta.codigo] = cuenta
        return cuenta

    def cuentas(self, cliente_id: str) -> dict[str, Cuenta]:
        return self._cuentas[cliente_id]

    def agregar_regla(self, regla: Regla) -> Regla:
        regla.id = regla.id or uuid.uuid4().hex[:12]
        self._reglas[regla.cliente_id].append(regla)
        return regla

    def reglas_cliente(self, cliente_id: str) -> list[Regla]:
        return self._reglas[cliente_id]

    def documento_existe(self, cliente_id: str, sha256: str) -> bool:
        return any(d.cliente_id == cliente_id and d.sha256 == sha256 for d in self._docs.values())

    def registrar_documento(self, doc: Documento) -> Documento:
        doc.id = doc.id or uuid.uuid4().hex[:12]      # sin esto todos los documentos compartían la clave ""
        self._docs[doc.id] = doc
        return doc

    def documento(self, documento_id: str) -> Documento | None:
        doc = self._docs.get(documento_id)
        if doc and doc.lote_id and self._lotes[doc.lote_id].estado == "aprobado":
            doc.estado = "aprobado"
        return doc

    def borrar_documento(self, documento_id: str) -> None:
        """Borra el documento y lo que se cargó desde él (para reprocesarlo)."""
        doc = self._docs.pop(documento_id, None)
        if not doc:
            return
        for tipo, cliente, clave in self._origen.pop(documento_id, []):
            {"comprobante": self._comps, "f931": self._f931, "venta": self._ventas, "compra": self._compras_item}[tipo].get(cliente, {}).pop(clave, None)
        if doc.lote_id:
            self._lotes.pop(doc.lote_id, None)

    def _anotar_origen(self, documento_id: str, tipo: str, cliente_id: str, clave) -> None:
        if documento_id:
            self._origen.setdefault(documento_id, []).append((tipo, cliente_id, clave))

    def documentos(self, cliente_id: str) -> list[Documento]:
        docs = [d for d in self._docs.values() if d.cliente_id == cliente_id]
        for d in docs:   # el estado de un extracto sigue al de su lote
            if d.lote_id and self._lotes[d.lote_id].estado == "aprobado":
                d.estado = "aprobado"
        return sorted(docs, key=lambda d: d.subido_en, reverse=True)

    def guardar_lote(self, lote: Lote) -> Lote:
        self._lotes[lote.id] = lote
        res = lote.resultado.resumen()
        alertas = res["sin_regla"] or res["rubro_inexistente"] or res["duplicados"]
        self._docs[lote.id] = Documento(lote.id, lote.cliente_id, lote.documento, "extracto",
                                        "con_alertas" if alertas else "procesado", lote.sha256, lote.tamano_bytes,
                                        lote.storage_path, lote_id=lote.id, detalle=f"{res['movimientos']} movimientos")
        return lote

    def actualizar_lote(self, lote: Lote) -> None:
        self._lotes[lote.id] = lote

    def lote(self, lote_id: str) -> Lote | None:
        return self._lotes.get(lote_id)

    def lotes(self, cliente_id: str, estado: str | None = None) -> list[Lote]:
        return [l for l in self._lotes.values() if l.cliente_id == cliente_id and (estado is None or l.estado == estado)]

    def tesoreria(self, cliente_id: str) -> list[MovimientoTesoreria]:
        return self._tesoreria[cliente_id]

    def insertar_tesoreria(self, cliente_id: str, movimientos: list[MovimientoTesoreria], lote_id: str | None = None) -> None:
        for m in movimientos:
            m.id = m.id or uuid.uuid4().hex[:12]
        self._tesoreria[cliente_id].extend(movimientos)

    # ------------------------------------------------------------------ devengado
    def guardar_comprobantes(self, cliente_id: str, documento_id: str, comps: list[ComprobanteArca]) -> tuple[int, int]:
        """Devuelve (nuevos, repetidos). Los recibidos toman el rubro recordado del proveedor."""
        existentes = self._comps.setdefault(cliente_id, {})
        recordados = self._rubro_tercero.setdefault(cliente_id, {})
        nuevos = repetidos = 0
        for c in comps:
            clave = (c.sentido, c.tipo, c.comprobante, c.doc_contraparte)
            if clave in existentes:
                repetidos += 1
                continue
            existentes[clave] = ComprobanteRegistrado(
                uuid.uuid4().hex[:12], c.sentido, c.fecha, c.comprobante, c.doc_contraparte, c.contraparte,
                c.neto_ars, recordados.get(c.doc_contraparte) if c.sentido == "recibido" else None,
                c.total * c.tipo_cambio)
            self._anotar_origen(documento_id, "comprobante", cliente_id, clave)
            nuevos += 1
        return nuevos, repetidos

    def comprobantes(self, cliente_id: str, sentido: str | None = None, sin_rubro: bool = False) -> list[ComprobanteRegistrado]:
        return sorted((c for c in self._comps.get(cliente_id, {}).values()
                       if (sentido is None or c.sentido == sentido) and (not sin_rubro or not c.rubro)),
                      key=lambda c: (c.fecha, c.comprobante))

    def asignar_rubro(self, cliente_id: str, comprobante_id: str, rubro: str, recordar: bool) -> int:
        objetivo = next((c for c in self._comps.get(cliente_id, {}).values() if c.id == comprobante_id), None)
        if not objetivo:
            return 0
        objetivo.rubro = rubro
        if not recordar:
            return 1
        self._rubro_tercero.setdefault(cliente_id, {})[objetivo.cuit] = rubro
        otros = [c for c in self._comps[cliente_id].values()
                 if c.sentido == "recibido" and c.cuit == objetivo.cuit and not c.rubro]
        for c in otros:
            c.rubro = rubro
        return 1 + len(otros)

    def clasificar_comprobante(self, cliente_id: str, comprobante_id: str, unidad_negocio: str | None,
                               centro_costo: str | None, mismo_cuit: bool) -> int:
        """Unidad de negocio y centro de costo; con mismo_cuit, también a los del mismo sentido y CUIT."""
        objetivo = next((c for c in self._comps.get(cliente_id, {}).values() if c.id == comprobante_id), None)
        if not objetivo:
            return 0
        destino = [c for c in self._comps[cliente_id].values()
                   if c is objetivo or (mismo_cuit and c.sentido == objetivo.sentido and c.cuit == objetivo.cuit)]
        for c in destino:
            c.unidad_negocio, c.centro_costo = unidad_negocio, centro_costo
        return len(destino)

    def guardar_f931(self, cliente_id: str, documento_id: str, dj: DeclaracionF931) -> None:
        self._f931.setdefault(cliente_id, {})[dj.periodo] = CostoLaboral(
            dj.periodo, dj.importes.get("remuneracion_total", Decimal(0)), dj.cargas_patronales, dj.empleados)
        self._anotar_origen(documento_id, "f931", cliente_id, dj.periodo)

    def costos_laborales(self, cliente_id: str) -> list[CostoLaboral]:
        return list(self._f931.get(cliente_id, {}).values())

    def indices(self) -> list[FilaIndice]:
        return sorted(self._indices.values(), key=lambda f: f.mes)

    def guardar_indice(self, fila: FilaIndice) -> None:
        actual = self._indices.get(fila.mes)
        if actual:
            fila.tc = {**actual.tc, **fila.tc}
            fila.ipc = fila.ipc if fila.ipc is not None else actual.ipc
            fila.cct = fila.cct if fila.cct is not None else actual.cct
            fila.tarifa = fila.tarifa if fila.tarifa is not None else actual.tarifa
        self._indices[fila.mes] = fila

    # ------------------------------------------------------------------ presupuesto
    def presupuesto(self, cliente_id: str, anio: int) -> dict[tuple[str, date], Decimal]:
        return {k: v for k, v in self._ppto.get(cliente_id, {}).items() if k[1].year == anio}

    def guardar_presupuesto(self, cliente_id: str, filas: list[tuple[str, date, Decimal | None]]) -> None:
        p = self._ppto.setdefault(cliente_id, {})
        for rubro, mes, base in filas:
            if base is None:
                p.pop((rubro, mes), None)
            else:
                p[(rubro, mes)] = base

    def notas_desvio(self, cliente_id: str, anio: int) -> dict[tuple[str, date], str]:
        return {k: v for k, v in self._notas.get(cliente_id, {}).items() if k[1].year == anio}

    def guardar_nota_desvio(self, cliente_id: str, rubro: str, mes: date, nota: str) -> None:
        self._notas.setdefault(cliente_id, {})[(rubro, mes)] = nota

    # ------------------------------------------------------------------ ítems y mermas
    def items(self, cliente_id: str) -> dict[str, Item]:
        return dict(sorted(self._items.get(cliente_id, {}).items()))

    def guardar_item(self, cliente_id: str, item: Item) -> Item:
        self._items.setdefault(cliente_id, {})[item.codigo] = item
        return item

    def guardar_lineas_venta(self, cliente_id: str, documento_id: str, lineas: list[LineaVenta]) -> tuple[int, int]:
        actuales = self._ventas.setdefault(cliente_id, {})
        nuevas = 0
        for l in lineas:
            clave = (l.fecha, l.comprobante, l.item, l.cantidad, l.precio_unitario)
            if clave not in actuales:
                l.id = uuid.uuid4().hex[:12]
                actuales[clave] = l
                self._anotar_origen(documento_id, "venta", cliente_id, clave)
                nuevas += 1
        return nuevas, len(lineas) - nuevas

    def lineas_venta(self, cliente_id: str) -> list[LineaVenta]:
        return sorted(self._ventas.get(cliente_id, {}).values(), key=lambda l: (l.fecha, l.comprobante))

    def guardar_lineas_compra(self, cliente_id: str, documento_id: str, lineas: list[LineaCompra]) -> tuple[int, int]:
        actuales = self._compras_item.setdefault(cliente_id, {})
        nuevas = 0
        for l in lineas:
            clave = (l.fecha, l.comprobante, l.proveedor, l.item, l.cantidad, l.costo_unitario)
            if clave not in actuales:
                l.id = uuid.uuid4().hex[:12]
                actuales[clave] = l
                self._anotar_origen(documento_id, "compra", cliente_id, clave)
                nuevas += 1
        return nuevas, len(lineas) - nuevas

    def lineas_compra(self, cliente_id: str) -> list[LineaCompra]:
        return sorted(self._compras_item.get(cliente_id, {}).values(), key=lambda l: (l.fecha, l.comprobante))

    def registrar_merma(self, cliente_id: str, merma: Merma) -> Merma:
        merma.id = uuid.uuid4().hex[:12]
        self._mermas.setdefault(cliente_id, []).append(merma)
        return merma

    def mermas(self, cliente_id: str) -> list[Merma]:
        return sorted(self._mermas.get(cliente_id, []), key=lambda m: m.fecha)

    # ------------------------------------------------------------------ plan de cuentas
    def plan_cuentas(self, cliente_id: str) -> dict[str, CuentaContable]:
        return dict(self._plan.get(cliente_id, {}))

    def iniciar_plan(self, cliente_id: str, cuentas: list[CuentaContable]) -> None:
        self._plan.setdefault(cliente_id, {}).update({c.codigo: c for c in cuentas})

    def guardar_cuenta_contable(self, cliente_id: str, cuenta: CuentaContable) -> None:
        self._plan.setdefault(cliente_id, {})[cuenta.codigo] = cuenta

    def borrar_cuenta_contable(self, cliente_id: str, codigo: str) -> None:
        self._plan.get(cliente_id, {}).pop(codigo, None)
        vinculos = self._rubro_cuenta.get(cliente_id, {})
        for rubro in [r for r, c in vinculos.items() if c == codigo]:
            del vinculos[rubro]

    def rubro_cuenta(self, cliente_id: str) -> dict[str, str]:
        return dict(self._rubro_cuenta.get(cliente_id, {}))

    def vincular_rubro(self, cliente_id: str, rubro: str, cuenta: str | None) -> None:
        vinculos = self._rubro_cuenta.setdefault(cliente_id, {})
        if cuenta is None:
            vinculos.pop(rubro, None)
        else:
            vinculos[rubro] = cuenta

    # ------------------------------------------------------------------ tablero
    def cierres(self, cliente_id: str) -> dict[date, DatosCierre]:
        return dict(self._cierres.get(cliente_id, {}))

    def guardar_cierre(self, cliente_id: str, cierre: DatosCierre) -> None:
        self._cierres.setdefault(cliente_id, {})[cierre.mes] = cierre

    def metas(self, cliente_id: str) -> dict[str, tuple[Decimal | None, str]]:
        return dict(self._metas.get(cliente_id, {}))

    def guardar_meta(self, cliente_id: str, kpi: str, meta: Decimal | None, direccion: str) -> None:
        self._metas.setdefault(cliente_id, {})[kpi] = (meta, direccion)

    # cola de trabajos: el lock evita que dos hilos tomen el mismo trabajo (worker embebido + request)
    def encolar(self, cliente_id: str, tipo: str, parametros: dict) -> Trabajo:
        t = Trabajo(str(uuid.uuid4()), cliente_id, tipo, dict(parametros))
        with self._lock:
            self._trabajos[t.id] = t
        return t

    def tomar_trabajo(self, worker: str) -> Trabajo | None:
        with self._lock:
            t = next((t for t in sorted(self._trabajos.values(), key=lambda t: t.creado) if t.estado == "pendiente"), None)
            if t:
                t.estado, t.intentos, t.actualizado = "procesando", t.intentos + 1, datetime.now()
            return t

    def terminar_trabajo(self, trabajo_id: str, resultado: dict | None, error: str | None, reintentar: bool = False) -> None:
        with self._lock:
            t = self._trabajos[trabajo_id]
            t.resultado, t.error, t.actualizado = resultado, error, datetime.now()
            t.estado = "hecho" if error is None else ("pendiente" if reintentar and t.intentos < MAX_INTENTOS else "error")

    def trabajo(self, trabajo_id: str) -> Trabajo | None:
        return self._trabajos.get(trabajo_id)

    def estado_cola(self) -> dict[str, int]:
        cuenta: dict[str, int] = {"pendiente": 0, "procesando": 0, "hecho": 0, "error": 0}
        for t in self._trabajos.values():
            cuenta[t.estado] += 1
        return cuenta
