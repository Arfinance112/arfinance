"""API REST del módulo de ingesta y conciliación (la versión web de IMP_Pegado → IMP_Listo → T_Tesoreria).

Levantar:  uvicorn app.api.main:app --reload   (desde la carpeta backend)
Documentación interactiva: http://localhost:8000/docs
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.core.archivos_seguros import ArchivoRechazado, nombre_seguro
from app.core.archivos_seguros import validar as validar_archivo
from app.core.observabilidad import instalar as instalar_observabilidad
from app.core.observabilidad import log, metricas
from pydantic import BaseModel, Field

from app import seeds
from app.api.auth import Usuario, es_admin_plataforma, usuario_actual, verificar_configuracion
from app.api import invitaciones
from app.api.repositorio import ROLES, Cuenta, Documento, Lote, Repositorio, RepositorioMemoria
from app.finanzas.asientos import construir_asientos
from app.finanzas.flujo import flujo_mensual
from app.finanzas.indices import FilaIndice, TablaIndices
from app.finanzas.items import (Item, Merma, agrupar_mermas_por_causa, asientos_de_items, costos_fijos_del_periodo,
                                rentabilidad)
from app.finanzas import plan_cuentas
from app.finanzas.flujo import GRUPOS as GRUPOS_CF
from app.finanzas.kpis import proyeccion_caja, pyl_mensual
from app.finanzas.tablero import KPIS, DatosCierre, EntradaMes, armar_tablero, fin_de_mes, kpis_del_mes, mes_anterior, pendientes_fifo
from app.finanzas.tablero import Documento as TDoc
from app.ingesta import detalle_ventas
from app.finanzas.presupuesto import control, generar_base, meses_del_anio, nominal, real_por_rubro
from app.storage import Almacenamiento, crear_almacenamiento
from fastapi.encoders import jsonable_encoder

from app.ingesta import comprobantes_arca, f931, ocr, planilla_v2
from app.ingesta.lectores import FormatoNoSoportado, leer_archivo
from app.ingesta.modelos import Alerta, MovimientoPropuesto, MovimientoTesoreria, Regla
from app.ingesta.pipeline import ResultadoImportacion, procesar_extracto, reprocesar, tipo_documento
from app.ingesta.reglas import MotorReglas

PRODUCCION = os.environ.get("ENTORNO") == "produccion"
_problemas_config = verificar_configuracion()      # en producción, si hay problemas, la API no arranca

def repo() -> Repositorio:
    return _repo


def almacen() -> Almacenamiento:
    return _almacen


# ------------------------------------------------------------------ permisos por rol
# Se aplica a TODO pedido que modifica algo (no a las lecturas: el acceso a cada cliente ya lo controla cada ruta).
SOLO_ADMIN = ("/organizacion/",)
PERMITIDO_A_CARGA = {
    ("POST", "/clientes/{cliente_id}/documentos"), ("POST", "/documentos/{documento_id}/reprocesar"),
    ("PATCH", "/lotes/{lote_id}/movimientos/{mov_id}"), ("POST", "/lotes/{lote_id}/aprobar"),
    ("POST", "/clientes/{cliente_id}/reglas"), ("PATCH", "/clientes/{cliente_id}/comprobantes/{comprobante_id}"),
    ("POST", "/clientes/{cliente_id}/mermas"),
}
LIBRE = {("POST", "/me/organizacion")}
ROLES_TEXTO = {"lectura": "solo lectura", "carga": "carga de documentos", "consultor": "consultor"}


def control_de_rol(request: Request, authorization: str | None = Header(default=None), r: Repositorio = Depends(repo)) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    ruta = getattr(request.scope.get("route"), "path", request.url.path)
    if (request.method, ruta) in LIBRE:
        return
    u = usuario_actual(authorization)
    rol = r.rol_de(u.id)
    if rol is None or rol == "admin":
        return                                      # sin organización: cada ruta ya exige tenerla
    if ruta.startswith(SOLO_ADMIN):
        raise HTTPException(403, "Solo un administrador de la organización puede gestionar usuarios.")
    if rol == "lectura" or (rol == "carga" and (request.method, ruta) not in PERMITIDO_A_CARGA):
        raise HTTPException(403, f"Tu usuario es de {ROLES_TEXTO[rol]}: no puede hacer este cambio. Pedíselo a un administrador.")


# en producción no se publica la documentación interactiva (mapa completo de la API)
app = FastAPI(title="Gestión PyME – Ingesta y conciliación", version="0.4.0", dependencies=[Depends(control_de_rol)],
              docs_url=None if PRODUCCION else "/docs", redoc_url=None, openapi_url=None if PRODUCCION else "/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGENES", "http://localhost:5173").split(","),
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
                   expose_headers=["X-Request-Id", "Content-Disposition"])


@app.middleware("http")
async def _encabezados_seguridad(request, call_next):
    respuesta = await call_next(request)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "no-referrer")
    respuesta.headers.setdefault("Cache-Control", "no-store")                 # datos financieros: nada en caché
    if PRODUCCION:
        respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return respuesta


def _crear_repo() -> Repositorio:
    """DATABASE_URL definida → PostgreSQL/Supabase; si no, memoria (demo y tests)."""
    url = os.environ.get("DATABASE_URL")
    if url:
        from app.db.repositorio_pg import RepositorioPostgres
        return RepositorioPostgres(url)
    return RepositorioMemoria()


_repo = _crear_repo()
_almacen = crear_almacenamiento()


instalar_observabilidad(app)
for _p in _problemas_config:
    log.warning("configuracion", extra={"problema": _p})


@app.on_event("startup")
def _worker_embebido() -> None:
    # en desarrollo (un solo proceso) el worker corre en un hilo; en producción va aparte: python -m app.worker
    # por defecto embebido solo en modo memoria (desarrollo): ahí no hay otro proceso que pueda ver la cola
    if os.environ.get("WORKER_EMBEBIDO", "0" if os.environ.get("DATABASE_URL") else "1") == "1":
        from app.worker import iniciar_en_hilo
        iniciar_en_hilo(_repo, _almacen)


@app.get("/salud")
def salud(r: Repositorio = Depends(repo), alm: Almacenamiento = Depends(almacen)):
    """Para el balanceador y el monitoreo: base, almacenamiento y cola. 503 si algo falla."""
    chequeos: dict[str, object] = {}
    try:
        chequeos["cola"] = r.estado_cola()
        chequeos["base"] = "ok"
    except Exception as e:  # noqa: BLE001 — el detalle va al log, no al público
        log.error("salud_base", extra={"error": repr(e)})
        chequeos["base"] = "error"
    try:
        alm.guardar("_salud/ping.txt", b"ok", "text/plain")
        chequeos["almacenamiento"] = "ok" if alm.leer("_salud/ping.txt") == b"ok" else "error"
    except Exception as e:  # noqa: BLE001
        log.error("salud_almacenamiento", extra={"error": repr(e)})
        chequeos["almacenamiento"] = "error"
    ok = chequeos["base"] == "ok" and chequeos["almacenamiento"] == "ok"
    return JSONResponse(status_code=200 if ok else 503, content={"estado": "ok" if ok else "degradado", "version": app.version, **chequeos})


@app.get("/metricas")
def ver_metricas(authorization: str | None = Header(None), r: Repositorio = Depends(repo)):
    """Formato Prometheus. Si METRICAS_TOKEN está definido, se exige como Bearer."""
    token = os.environ.get("METRICAS_TOKEN")
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "Token de métricas inválido")
    return Response(metricas.texto(r.estado_cola()), media_type="text/plain; version=0.0.4")


# ------------------------------------------------------------------ esquemas
class ClienteIn(BaseModel):
    nombre: str
    cuit: str = ""


class CuentaIn(BaseModel):
    codigo: str
    nombre: str
    tipo: str
    cotizacion: str = "ARS"
    saldo_inicial: Decimal = Decimal(0)
    fecha_saldo_inicial: date | None = None
    perfil_defecto: str | None = None


class ReglaIn(BaseModel):
    texto: str = Field(min_length=2)
    rubro: str
    tipo: str | None = None
    cuenta: str | None = None
    tercero: str | None = None
    unidad_negocio: str | None = None
    medio_pago: str | None = None
    comentario: str | None = None


class CorreccionIn(BaseModel):
    rubro: str | None = None
    tercero: str | None = None
    comprobante: str | None = None
    unidad_negocio: str | None = None


class AprobacionIn(BaseModel):
    """Sin opciones: los posibles duplicados nunca se cargan (se quitó la opción de pasarlos igual)."""


# ------------------------------------------------------------------ helpers
def _cliente_o_404(r: Repositorio, cliente_id: str, u: Usuario):
    # 404 y no 403: no se revela que existe un cliente de otra organización
    c = r.cliente(cliente_id)
    if not c or not r.puede_ver_cliente(u.id, cliente_id):
        raise HTTPException(404, "Cliente inexistente")
    return c


def _lote_o_404(r: Repositorio, lote_id: str, u: Usuario) -> Lote:
    lote = r.lote(lote_id)
    if not lote or not r.puede_ver_cliente(u.id, lote.cliente_id):
        raise HTTPException(404, "Lote inexistente")
    return lote


def _motor(r: Repositorio, cliente_id: str) -> MotorReglas:
    return MotorReglas([*r.reglas_cliente(cliente_id), *seeds.reglas_globales()])


def _saldo_planilla(r: Repositorio, cliente_id: str, cuenta: str, hasta: date | None) -> Decimal:
    c = r.cuentas(cliente_id)[cuenta]
    movs = (m.importe_firmado for m in r.tesoreria(cliente_id) if m.cuenta == cuenta and (hasta is None or m.fecha <= hasta))
    return c.saldo_inicial + sum(movs, Decimal(0))


def _a_insertar(res: ResultadoImportacion, incluir_dup: bool) -> list[MovimientoPropuesto]:
    return [m for m in res.movimientos if Alerta.DUPLICADO_EXACTO not in m.alertas
            and (incluir_dup or Alerta.POSIBLE_DUPLICADO not in m.alertas)]


def _conciliacion(r: Repositorio, lote: Lote) -> dict:
    res = lote.resultado
    if res.fecha_ultima is None:
        return {}
    actual = _saldo_planilla(r, lote.cliente_id, lote.cuenta, res.fecha_ultima)
    pendiente = Decimal(0) if lote.estado == "aprobado" else sum(
        (m.importe_firmado for m in _a_insertar(res, False) if m.fecha <= res.fecha_ultima), Decimal(0))
    despues = actual + pendiente
    # saldo inicial: el banco arranca en (saldo final − neto de TODOS los movimientos del extracto, duplicados
    # incluidos, porque el extracto los trae); el sistema, en su saldo del día anterior al primer movimiento
    primera = min((m.fecha for m in res.movimientos), default=res.fecha_ultima)
    neto = sum((m.importe_firmado for m in res.movimientos), Decimal(0))
    inicial_extracto = None if res.saldo_extracto is None else res.saldo_extracto - neto
    inicial_sistema = _saldo_planilla(r, lote.cliente_id, lote.cuenta, primera - timedelta(days=1))
    return {"fecha": res.fecha_ultima, "fecha_inicial": primera, "saldo_extracto": res.saldo_extracto,
            "saldo_inicial_extracto": inicial_extracto, "saldo_inicial_sistema": inicial_sistema,
            "diferencia_inicial": None if inicial_extracto is None else inicial_extracto - inicial_sistema,
            "saldo_planilla_actual": actual, "saldo_planilla_despues_de_aprobar": despues,
            "diferencia": None if res.saldo_extracto is None else res.saldo_extracto - despues}


def _mov_json(i: int, m: MovimientoPropuesto) -> dict:
    return {"id": i, "fila_origen": m.fila_origen, "pata": m.pata.value, "fecha": m.fecha, "cuenta": m.cuenta,
            "tipo": m.tipo, "importe": m.importe, "descripcion": m.descripcion, "referencia": m.referencia,
            "rubro": m.rubro, "tercero": m.tercero, "unidad_negocio": m.unidad_negocio, "medio_pago": m.medio_pago,
            "comprobante": m.comprobante, "regla": m.regla_texto, "alertas": [a.value for a in m.alertas],
            "bloqueado": m.bloqueado}


def _lote_json(r: Repositorio, lote: Lote) -> dict:
    res = lote.resultado
    return {"id": lote.id, "cliente_id": lote.cliente_id, "cuenta": lote.cuenta, "documento": lote.documento,
            "estado": lote.estado, "perfil": res.perfil.nombre if res.perfil else None,
            "perfil_autodetectado": res.perfil_autodetectado, "filas_leidas": res.filas_leidas,
            "filas_descartadas": res.filas_descartadas, "resumen": res.resumen(),
            "conciliacion": _conciliacion(r, lote),
            "movimientos": [_mov_json(i, m) for i, m in enumerate(res.movimientos)]}


# ------------------------------------------------------------------ sesión y organización
class OrganizacionIn(BaseModel):
    nombre: str = Field(min_length=2)


@app.get("/me")
def yo(u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    return {"id": u.id, "email": u.email, "organizacion_id": r.organizacion_de(u.id), "rol": r.rol_de(u.id)}


# ------------------------------------------------------------------ usuarios de la organización
class MiembroIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    rol: str = Field(pattern="^(admin|consultor|carga|lectura)$")


class RolIn(BaseModel):
    rol: str = Field(pattern="^(admin|consultor|carga|lectura)$")


def _mi_organizacion(r: Repositorio, u: Usuario) -> str:
    org = r.organizacion_de(u.id)
    if not org:
        raise HTTPException(403, "Primero creá tu organización: POST /me/organizacion")
    return org


def _miembro_o_404(r: Repositorio, org: str, usuario_id: str):
    m = next((m for m in r.miembros(org) if m.usuario_id == usuario_id), None)
    if not m:
        raise HTTPException(404, "Ese usuario no es miembro de tu organización")
    return m


def _queda_admin(r: Repositorio, org: str, sin: str) -> bool:
    return any(m.rol == "admin" and m.usuario_id != sin for m in r.miembros(org))


@app.get("/organizacion/miembros")
def listar_miembros(u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    org = _mi_organizacion(r, u)
    return {"roles": list(ROLES), "miembros": [{"usuario_id": m.usuario_id, "email": m.email, "rol": m.rol, "vos": m.usuario_id == u.id}
                                               for m in r.miembros(org)]}


@app.post("/organizacion/miembros", status_code=201)
def invitar_miembro(body: MiembroIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Invita un email a la organización con un rol. Si no tiene cuenta, Supabase le manda el mail de invitación."""
    org = _mi_organizacion(r, u)
    email = body.email.strip().lower()
    if any(m.email.lower() == email for m in r.miembros(org)):
        raise HTTPException(409, f"{email} ya es miembro de la organización.")
    try:
        invitado = invitaciones.invitar(email)
        r.agregar_miembro(org, invitado.usuario_id, email, body.rol)
    except invitaciones.InvitacionFallida as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    log.info("miembro_invitado", extra={"rol": body.rol, "mail_enviado": invitado.mail_enviado})
    return {"usuario_id": invitado.usuario_id, "email": email, "rol": body.rol, "mail_enviado": invitado.mail_enviado}


@app.patch("/organizacion/miembros/{usuario_id}")
def cambiar_rol_miembro(usuario_id: str, body: RolIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    org = _mi_organizacion(r, u)
    m = _miembro_o_404(r, org, usuario_id)
    if m.rol == "admin" and body.rol != "admin" and not _queda_admin(r, org, usuario_id):
        raise HTTPException(409, "Es el único administrador: nombrá a otro antes de cambiarle el rol.")
    r.cambiar_rol(org, usuario_id, body.rol)
    return {"usuario_id": usuario_id, "rol": body.rol}


@app.delete("/organizacion/miembros/{usuario_id}", status_code=204)
def quitar_miembro(usuario_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Saca al usuario de la organización (deja de ver sus clientes). Su cuenta de acceso no se borra."""
    org = _mi_organizacion(r, u)
    m = _miembro_o_404(r, org, usuario_id)
    if m.rol == "admin" and not _queda_admin(r, org, usuario_id):
        raise HTTPException(409, "Es el único administrador: la organización no puede quedarse sin administrador.")
    r.quitar_miembro(org, usuario_id)
    return Response(status_code=204)


@app.post("/me/organizacion", status_code=201)
def crear_organizacion(body: OrganizacionIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Primer ingreso de un estudio o consultora: crea la organización y deja al usuario como admin."""
    actual = r.organizacion_de(u.id)
    if actual:
        return {"organizacion_id": actual, "creada": False}
    return {"organizacion_id": r.alta_usuario(u.id, u.email, body.nombre), "creada": True}


# ------------------------------------------------------------------ maestros
@app.get("/perfiles")
def listar_perfiles(u: Usuario = Depends(usuario_actual)):
    return [{"codigo": p.codigo, "nombre": p.nombre, "tipo_origen": p.tipo_origen, "notas": p.notas} for p in seeds.perfiles()]


@app.get("/rubros")
def listar_rubros(u: Usuario = Depends(usuario_actual)):
    return list(seeds.rubros().values())


@app.post("/clientes", status_code=201)
def crear_cliente(body: ClienteIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    org = r.organizacion_de(u.id)
    if not org:
        raise HTTPException(403, "Primero creá tu organización: POST /me/organizacion")
    return r.crear_cliente(org, body.nombre, body.cuit)


@app.post("/clientes/importar-planilla")
async def importar_planilla(archivo: UploadFile = File(...), simular: bool = Form(True), omitir_ejemplos: bool = Form(True),
                            importar_indices: bool = Form(False), nombre: str | None = Form(None), cuit: str | None = Form(None),
                            u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo),
                            alm: Almacenamiento = Depends(almacen)):
    """Alta de un cliente desde la Planilla v2. Con simular=true (por defecto) solo devuelve lo que encontró."""
    org = r.organizacion_de(u.id)
    if not org:
        raise HTTPException(403, "Primero creá tu organización: POST /me/organizacion")
    contenido = await _leer_con_tope(archivo)
    nombre_archivo = nombre_seguro(archivo.filename)
    if not nombre_archivo.endswith((".xlsx", ".xlsm")):
        raise HTTPException(415, "Subí la planilla en formato .xlsx.")
    try:
        validar_archivo(nombre_archivo, contenido)
        p = planilla_v2.leer(contenido, omitir_ejemplos)
    except ArchivoRechazado as e:
        raise HTTPException(e.status, str(e))
    except planilla_v2.PlanillaInvalida as e:
        raise HTTPException(422, str(e))
    if simular:
        return {"simulacion": True, **p.resumen(seeds.reglas_globales())}
    cliente = r.crear_cliente(org, (nombre or p.empresa or "Cliente importado").strip(), (cuit or p.cuit).strip())
    sha = hashlib.sha256(contenido).hexdigest()
    ruta = alm.guardar(f"clientes/{cliente.id}/{sha[:16]}-{nombre_archivo}", contenido,
                       archivo.content_type or "application/octet-stream")
    doc = r.registrar_documento(Documento("", cliente.id, nombre_archivo, "planilla_v2", "procesado", sha, len(contenido), ruta,
                                          detalle="Importación inicial desde la planilla v2"))
    if importar_indices and not es_admin_plataforma(u):
        importar_indices = False
        p.avisos.append("Los índices de la planilla no se importaron: son comunes a todos los estudios y los carga el administrador.")
    hecho = planilla_v2.aplicar(r, cliente.id, p, doc.id, seeds.reglas_globales(), importar_indices)
    log.info("planilla_importada", extra={"cliente_id": cliente.id, **hecho})
    return JSONResponse(status_code=201, content=jsonable_encoder(
        {"simulacion": False, "cliente_id": cliente.id, "nombre": cliente.nombre, "importado": hecho, "avisos": p.avisos}))


@app.get("/clientes")
def listar_clientes(u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    return [{"id": c.id, "nombre": c.nombre, "cuit": c.cuit, "cuentas": len(r.cuentas(c.id)),
             "movimientos_tesoreria": len(r.tesoreria(c.id)), "lotes_pendientes": len(r.lotes(c.id, "pendiente"))}
            for c in r.clientes(u.id)]


@app.post("/clientes/{cliente_id}/cuentas", status_code=201)
def crear_cuenta(cliente_id: str, body: CuentaIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return r.agregar_cuenta(cliente_id, Cuenta(**body.model_dump()))


@app.get("/clientes/{cliente_id}/saldos")
def saldos(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return [{"cuenta": c.codigo, "nombre": c.nombre, "tipo": c.tipo, "cotizacion": c.cotizacion,
             "saldo": _saldo_planilla(r, cliente_id, c.codigo, None)} for c in r.cuentas(cliente_id).values()]


@app.get("/clientes/{cliente_id}/tesoreria")
def tesoreria(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return r.tesoreria(cliente_id)


@app.get("/clientes/{cliente_id}")
def ver_cliente(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    c = _cliente_o_404(r, cliente_id, u)
    return {"id": c.id, "nombre": c.nombre, "cuit": c.cuit}


@app.get("/clientes/{cliente_id}/cuentas")
def listar_cuentas(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return list(r.cuentas(cliente_id).values())


@app.get("/clientes/{cliente_id}/documentos")
def listar_documentos(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return [{"id": d.id, "nombre": d.nombre, "tipo": d.tipo, "estado": d.estado, "tamano_bytes": d.tamano_bytes,
             "lote_id": d.lote_id, "detalle": d.detalle, "subido_en": d.subido_en} for d in r.documentos(cliente_id)]


@app.get("/clientes/{cliente_id}/flujo")
def flujo_de_caja(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Cash flow real por mes y línea, en la moneda de cada cuenta."""
    _cliente_o_404(r, cliente_id, u)
    monedas = {c.codigo: ("ARS" if c.cotizacion in ("", "ARS") else c.cotizacion.split("_")[0])
               for c in r.cuentas(cliente_id).values()}
    lineas = {codigo: rb["linea_cf"] for codigo, rb in seeds.rubros().items()}
    return flujo_mensual(r.tesoreria(cliente_id), lineas, monedas)


# ------------------------------------------------------------------ devengado (fase 2a)
class AsignacionRubroIn(BaseModel):
    rubro: str
    recordar: bool = True          # aplicar a todas las facturas de ese proveedor, actuales y futuras


class IndiceIn(BaseModel):
    ipc: Decimal | None = None
    cct: Decimal | None = None
    tarifa: Decimal | None = None
    tc: dict[str, Decimal] = Field(default_factory=dict)


@app.get("/clientes/{cliente_id}/comprobantes")
def listar_comprobantes(cliente_id: str, sentido: str | None = None, sin_rubro: bool = False,
                        u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return r.comprobantes(cliente_id, sentido, sin_rubro)


@app.patch("/clientes/{cliente_id}/comprobantes/{comprobante_id}")
def asignar_rubro_comprobante(cliente_id: str, comprobante_id: str, body: AsignacionRubroIn,
                              u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    if body.rubro not in seeds.rubros():
        raise HTTPException(422, f"Rubro {body.rubro} inexistente")
    n = r.asignar_rubro(cliente_id, comprobante_id, body.rubro, body.recordar)
    if n == 0:
        raise HTTPException(404, "Comprobante inexistente")
    return {"actualizados": n}


@app.get("/indices")
def listar_indices(u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    return r.indices()


@app.put("/indices/{mes}")
def guardar_indice(mes: date, body: IndiceIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Índices del mes (variaciones como fracción: 0.021 = 2,1 %) y tipos de cambio por cotización."""
    # los índices son comunes a todos los estudios: solo los cambia quien opera la plataforma
    if not es_admin_plataforma(u):
        raise HTTPException(403, "Los índices y tipos de cambio son comunes a todos los estudios: los carga el administrador de la plataforma.")
    if any(v <= 0 for v in body.tc.values()):
        raise HTTPException(422, "Los tipos de cambio deben ser positivos")
    r.guardar_indice(FilaIndice(mes.replace(day=1), body.ipc, body.cct, body.tarifa, dict(body.tc)))
    return {"mes": mes.replace(day=1)}


def _asientos(r: Repositorio, cliente_id: str, rubro_ventas: str = "ING01"):
    filas_idx = r.indices()
    indices = TablaIndices(filas_idx) if filas_idx else None
    asientos, avisos = construir_asientos(
        comprobantes=r.comprobantes(cliente_id), tesoreria=r.tesoreria(cliente_id),
        costos_laborales=r.costos_laborales(cliente_id), rubros=seeds.rubros(),
        cotizacion_por_cuenta={c.codigo: c.cotizacion for c in r.cuentas(cliente_id).values()},
        indices=indices, rubro_ventas=rubro_ventas)
    # CMV a costo estándar y mermas valorizadas (fase 2c)
    de_items, av = asientos_de_items(r.lineas_venta(cliente_id), r.mermas(cliente_id), r.items(cliente_id), indices, seeds.rubros())
    asientos += de_items
    if av.items_desconocidos:
        avisos.extra.append(f"{len(av.items_desconocidos)} códigos vendidos sin alta en Ítems ({', '.join(sorted(av.items_desconocidos)[:5])}): "
                            "su costo de mercadería no se calcula hasta darlos de alta.")
    if av.sin_tc:
        avisos.extra.append(f"{av.sin_tc} ventas o mermas con costo en moneda extranjera sin tipo de cambio del mes.")
    return asientos, avisos, indices


@app.get("/clientes/{cliente_id}/resultados")
def resultados(cliente_id: str, rubro_ventas: str = "ING01", u: Usuario = Depends(usuario_actual),
               r: Repositorio = Depends(repo)):
    """P&L de gestión mensual en ARS (devengado), con prime cost y avisos de datos faltantes."""
    _cliente_o_404(r, cliente_id, u)
    asientos, avisos, _ = _asientos(r, cliente_id, rubro_ventas)
    meses = sorted({a.mes for a in asientos})
    # la amortización no sale de los registros: se carga en los datos de cierre (Balance_Gestion)
    pyl = pyl_mensual(asientos, meses, {m: c.amortizacion_mes for m, c in r.cierres(cliente_id).items()})
    # detalle por línea → rubro → mes (y "total"), para abrir cada línea del P&L
    detalle: dict[str, dict[str, dict[str, Decimal]]] = {}
    for a in asientos:
        clave = f"{a.rubro} · {seeds.rubros()[a.rubro]['nombre']}"
        serie = detalle.setdefault(a.linea_pl, {}).setdefault(clave, {})
        for k in (a.mes.isoformat(), "total"):
            serie[k] = serie.get(k, Decimal(0)) + a.importe
    return {"meses": [m.isoformat() for m in meses],
            "filas": {k: {m.isoformat(): v for m, v in serie.items()} for k, serie in pyl.items()},
            "detalle_por_linea": detalle, "avisos": avisos.lista()}


# ------------------------------------------------------------------ presupuesto y control (fase 2b)
TOLERANCIA_DEFECTO = Decimal("0.05")


class CeldaPresupuestoIn(BaseModel):
    rubro: str
    mes: date
    base: Decimal | None = Field(default=None, ge=0)     # None borra la celda


class PresupuestoIn(BaseModel):
    filas: list[CeldaPresupuestoIn]


class GenerarPresupuestoIn(BaseModel):
    anio: int = Field(ge=2000, le=2100)
    meses_historicos: list[date] = Field(min_length=1)    # meses reales que se promedian (etapa 1)
    ajuste_volumen: Decimal = Decimal(0)                 # etapa 2: +0.10 = 10 % más actividad
    objetivos: dict[str, Decimal] = Field(default_factory=dict)   # etapa 3: {"EST01": -0.05}
    reemplazar: bool = True


class NotaIn(BaseModel):
    rubro: str
    mes: date
    nota: str = Field(max_length=1000)


def _rubro_presupuestable(codigo: str) -> dict:
    info = seeds.rubros().get(codigo)
    if not info or info["linea_pl"] == "NO P&L":
        raise HTTPException(422, f"El rubro {codigo} no existe o no es de resultado")
    return info


@app.get("/clientes/{cliente_id}/presupuesto")
def ver_presupuesto(cliente_id: str, anio: int, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Base (a precios de enero) y nominal ajustado por el índice de cada rubro, mes a mes."""
    _cliente_o_404(r, cliente_id, u)
    filas_idx = r.indices()
    indices = TablaIndices(filas_idx) if filas_idx else None
    bases = r.presupuesto(cliente_id, anio)
    meses = meses_del_anio(anio)
    salida = []
    for rubro in sorted({k[0] for k in bases}):
        info = seeds.rubros()[rubro]
        ind = info.get("indice_ajuste") or "IPC"
        b = {m.isoformat(): bases.get((rubro, m), Decimal(0)) for m in meses}
        n = {m.isoformat(): nominal(bases.get((rubro, m), Decimal(0)), ind, m, meses[0], indices) for m in meses}
        salida.append({"rubro": rubro, "nombre": info["nombre"], "linea_pl": info["linea_pl"], "indice": ind,
                       "base": b, "nominal": n, "total_base": sum(b.values(), Decimal(0)),
                       "total_nominal": sum(n.values(), Decimal(0))})
    return {"anio": anio, "meses": [m.isoformat() for m in meses], "filas": salida,
            "avisos": [] if indices else ["No hay índices cargados: el nominal es igual a la base."]}


@app.put("/clientes/{cliente_id}/presupuesto")
def guardar_presupuesto(cliente_id: str, body: PresupuestoIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    for f in body.filas:
        _rubro_presupuestable(f.rubro)
    r.guardar_presupuesto(cliente_id, [(f.rubro, f.mes.replace(day=1), f.base) for f in body.filas])
    return {"guardadas": len(body.filas)}


@app.post("/clientes/{cliente_id}/presupuesto/generar")
def generar_presupuesto(cliente_id: str, body: GenerarPresupuestoIn, u: Usuario = Depends(usuario_actual),
                        r: Repositorio = Depends(repo)):
    """Arma la base desde lo real: histórico deflactado → volumen → objetivos. Misma base los 12 meses."""
    _cliente_o_404(r, cliente_id, u)
    for rubro in body.objetivos:
        _rubro_presupuestable(rubro)
    asientos, _, indices = _asientos(r, cliente_id)
    real = real_por_rubro(asientos, seeds.rubros())
    base = generar_base(real, [m.replace(day=1) for m in body.meses_historicos], date(body.anio, 1, 1),
                        seeds.rubros(), indices, body.ajuste_volumen, body.objetivos)
    if not base:
        raise HTTPException(422, "No hay datos reales en los meses elegidos para armar la base.")
    meses = meses_del_anio(body.anio)
    if body.reemplazar:
        r.guardar_presupuesto(cliente_id, [(rb, m, None) for rb, m in r.presupuesto(cliente_id, body.anio)])
    r.guardar_presupuesto(cliente_id, [(rubro, m, valor) for rubro, valor in base.items() for m in meses])
    return {"rubros": len(base), "base_mensual": base}


@app.get("/clientes/{cliente_id}/control")
def control_presupuestario(cliente_id: str, mes: date, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Real vs presupuesto del mes y acumulado del año, con semáforo por tolerancia (Control_Ppto)."""
    _cliente_o_404(r, cliente_id, u)
    mes = mes.replace(day=1)
    asientos, avisos, indices = _asientos(r, cliente_id)
    filas = control(mes, r.presupuesto(cliente_id, mes.year), real_por_rubro(asientos, seeds.rubros()), seeds.rubros(),
                    indices, TOLERANCIA_DEFECTO, r.notas_desvio(cliente_id, mes.year))
    resumen: dict[str, int] = {}
    for f in filas:
        resumen[f.semaforo_mes] = resumen.get(f.semaforo_mes, 0) + 1
    return {"mes": mes, "resumen": resumen, "avisos": avisos.lista(), "filas": [{
        "rubro": f.rubro, "nombre": f.nombre, "linea_pl": f.linea_pl, "signo": f.signo, "tolerancia": f.tolerancia,
        "ppto_mes": f.ppto_mes, "real_mes": f.real_mes, "desvio_mes": f.desvio_mes, "desvio_pct_mes": f.desvio_pct_mes,
        "semaforo_mes": f.semaforo_mes, "ppto_acum": f.ppto_acum, "real_acum": f.real_acum, "desvio_acum": f.desvio_acum,
        "desvio_pct_acum": f.desvio_pct_acum, "semaforo_acum": f.semaforo_acum, "nota": f.nota} for f in filas]}


@app.put("/clientes/{cliente_id}/control/nota")
def guardar_nota(cliente_id: str, body: NotaIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    _rubro_presupuestable(body.rubro)
    r.guardar_nota_desvio(cliente_id, body.rubro, body.mes.replace(day=1), body.nota.strip())
    return {"ok": True}


# ------------------------------------------------------------------ ítems, mermas y rentabilidad (fase 2c)
COTIZACIONES = {"ARS", "USD_OFICIAL", "USD_MEP", "USD_CCL", "USD_BLUE", "USDT", "EUR_OFICIAL", "BRL_OFICIAL"}
CAUSAS_MERMA = ["Vencimiento", "Rotura / daño", "Robo / faltante", "Error de producción / preparación", "Devolución de cliente",
                "Reproceso / garantía (servicios)", "Muestra / degustación", "Ajuste de inventario", "Bonificación / descuento no previsto"]


class ItemIn(BaseModel):
    descripcion: str = Field(min_length=1)
    tipo: str = Field(default="Bien", pattern="^(Bien|Servicio)$")
    unidad_negocio: str = "GENERAL"
    precio_lista: Decimal = Field(default=Decimal(0), ge=0)
    cotizacion_precio: str = "ARS"
    costo_estandar: Decimal = Field(default=Decimal(0), ge=0)
    cotizacion_costo: str = "ARS"
    alicuota_iva: Decimal = Field(default=Decimal("0.21"), ge=0, le=1)


class MermaIn(BaseModel):
    fecha: date
    item: str
    cantidad: Decimal = Field(gt=0)
    causa: str
    turno: str = ""


@app.get("/clientes/{cliente_id}/items")
def listar_items(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    vendidos = {l.item for l in r.lineas_venta(cliente_id)}
    items = r.items(cliente_id)
    return {"items": list(items.values()), "vendidos_sin_alta": sorted(vendidos - items.keys())}


@app.put("/clientes/{cliente_id}/items/{codigo}")
def guardar_item(cliente_id: str, codigo: str, body: ItemIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    if body.cotizacion_precio not in COTIZACIONES or body.cotizacion_costo not in COTIZACIONES:
        raise HTTPException(422, "Cotización inexistente")
    return r.guardar_item(cliente_id, Item(codigo.strip().upper(), **body.model_dump()))


@app.get("/clientes/{cliente_id}/mermas")
def listar_mermas(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    filas_idx = r.indices()
    indices = TablaIndices(filas_idx) if filas_idx else None
    mermas = r.mermas(cliente_id)
    return {"causas": CAUSAS_MERMA, "mermas": mermas,
            "por_causa": agrupar_mermas_por_causa(mermas, r.items(cliente_id), indices)}


@app.post("/clientes/{cliente_id}/mermas", status_code=201)
def registrar_merma(cliente_id: str, body: MermaIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    if body.item.upper() not in r.items(cliente_id):
        raise HTTPException(422, f"El ítem {body.item} no existe: dalo de alta primero.")
    if body.causa not in CAUSAS_MERMA:
        raise HTTPException(422, "Causa inexistente")
    return r.registrar_merma(cliente_id, Merma(body.fecha, body.item.upper(), body.cantidad, body.causa, body.turno))


@app.get("/clientes/{cliente_id}/rentabilidad")
def ver_rentabilidad(cliente_id: str, desde: date, hasta: date, u: Usuario = Depends(usuario_actual),
                     r: Repositorio = Depends(repo)):
    """Margen por unidad de negocio e ítem, punto de equilibrio con la mezcla real y margen de seguridad."""
    _cliente_o_404(r, cliente_id, u)
    asientos, avisos, indices = _asientos(r, cliente_id)
    res = rentabilidad(r.lineas_venta(cliente_id), r.mermas(cliente_id), r.items(cliente_id), indices,
                       costos_fijos_del_periodo(asientos, desde, hasta), desde, hasta)
    fila = lambda f: {"clave": f.clave, "nombre": f.nombre, "unidad_negocio": f.unidad_negocio, "cantidad": f.cantidad,
                      "ventas": f.ventas, "cmv": f.cmv, "mermas": f.mermas, "margen": f.margen,
                      "margen_pct": f.margen_pct, "margen_unitario": f.margen_unitario}
    return {**res, "items": [fila(f) for f in res["items"]], "unidades": [fila(f) for f in res["unidades"]],
            "avisos": avisos.lista()}


# ------------------------------------------------------------------ tablero ejecutivo (fase 3)
PLAZO_COBRO_PAGO_DIAS = 30          # vencimiento estimado de facturas de ARCA (no traen vencimiento)
PCT_RECUPERO_VENCIDAS = Decimal("0.5")


class CierreIn(BaseModel):
    stock: Decimal = Decimal(0)
    bienes_uso: Decimal = Decimal(0)
    otros_activos: Decimal = Decimal(0)
    deudas_financieras: Decimal = Decimal(0)
    deudas_fiscales: Decimal = Decimal(0)
    otros_pasivos: Decimal = Decimal(0)
    amortizacion_mes: Decimal = Field(default=Decimal(0), ge=0)


class MetaIn(BaseModel):
    meta: Decimal | None = None
    direccion: str = Field(pattern="^(≥|≤)$")


@app.get("/clientes/{cliente_id}/cierres")
def listar_cierres(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return sorted(r.cierres(cliente_id).values(), key=lambda c: c.mes)


@app.put("/clientes/{cliente_id}/cierres/{mes}")
def guardar_cierre(cliente_id: str, mes: date, body: CierreIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    r.guardar_cierre(cliente_id, DatosCierre(mes.replace(day=1), **body.model_dump()))
    return {"mes": mes.replace(day=1)}


@app.put("/clientes/{cliente_id}/metas/{kpi}")
def guardar_meta(cliente_id: str, kpi: str, body: MetaIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    if kpi not in KPIS:
        raise HTTPException(422, f"Indicador {kpi} inexistente")
    r.guardar_meta(cliente_id, kpi, body.meta, body.direccion)
    return {"kpi": kpi}


def _datos_mes(r: Repositorio, cliente_id: str, mes: date, ctx: dict) -> EntradaMes:
    """Arma la entrada de KPIs de un mes a partir de los registros (ver app/finanzas/tablero.py)."""
    eom = fin_de_mes(mes)
    indices, cuentas, teso, comps = ctx["indices"], ctx["cuentas"], ctx["tesoreria"], ctx["comprobantes"]
    tc = lambda m, cot: Decimal(1) if cot in ("", "ARS") else (indices.tc(m, cot) if indices else None)

    disponibilidades = Decimal(0)
    for c in cuentas.values():
        saldo = c.saldo_inicial + sum((x.importe_firmado for x in teso if x.cuenta == c.codigo and x.fecha <= eom), Decimal(0))
        t = tc(mes, c.cotizacion)
        if t is None:
            ctx["avisos"].add(f"Sin tipo de cambio {c.cotizacion} para valuar la cuenta {c.codigo}.")
            continue
        disponibilidades += saldo * t

    def ars(x) -> Decimal:
        t = tc(x.fecha.replace(day=1), cuentas[x.cuenta].cotizacion if x.cuenta in cuentas else "ARS")
        return x.importe_firmado * (t or Decimal(0))

    lineas_cf = {k: v["linea_cf"] for k, v in seeds.rubros().items()}
    operativas = {l for l, g in GRUPOS_CF.items() if g == "Operativo"}
    flujo_op = sum((ars(x) for x in teso if x.fecha.replace(day=1) == mes and lineas_cf.get(x.rubro) in operativas), Decimal(0))
    cobros = sum((ars(x) for x in teso if x.rubro == "COB01" and x.fecha <= eom), Decimal(0))
    pagos = -sum((ars(x) for x in teso if x.rubro == "PAG01" and x.fecha <= eom), Decimal(0))
    sueldos_pagados = -sum((ars(x) for x in teso if x.rubro == "PAG02" and x.fecha <= eom), Decimal(0))
    emitidos = [TDoc(c.fecha, c.total_ars) for c in comps if c.sentido == "emitido"]
    recibidos = [TDoc(c.fecha, c.total_ars) for c in comps if c.sentido == "recibido"]
    deudores = sum((p.importe for p in pendientes_fifo(emitidos, cobros, PLAZO_COBRO_PAGO_DIAS, eom)), Decimal(0))
    proveedores = sum((p.importe for p in pendientes_fifo(recibidos, pagos, PLAZO_COBRO_PAGO_DIAS, eom)), Decimal(0))
    laborales = [cl for cl in ctx["laborales"] if cl.periodo <= mes]
    rem_a_pagar = max(Decimal(0), sum((cl.remuneraciones + cl.cargas_patronales for cl in laborales), Decimal(0)) - sueldos_pagados)
    del_mes = [a for a in ctx["asientos"] if a.mes == mes]
    f931_mes = next((cl for cl in ctx["laborales"] if cl.periodo == mes), None)
    return EntradaMes(
        pyl={k: v.get(mes) for k, v in ctx["pyl"].items()}, disponibilidades=disponibilidades, flujo_operativo=flujo_op,
        deudores=deudores, proveedores=proveedores, remuneraciones_a_pagar=rem_a_pagar,
        ventas_con_iva=sum((d.total_ars for d in emitidos if d.fecha.replace(day=1) == mes), Decimal(0)),
        compras_con_iva=sum((d.total_ars for d in recibidos if d.fecha.replace(day=1) == mes), Decimal(0)),
        cmv=-sum((a.importe for a in del_mes if a.origen == "cmv"), Decimal(0)),
        mermas=-sum((a.importe for a in del_mes if a.origen == "mermas"), Decimal(0)),
        dotacion=f931_mes.empleados if f931_mes else None, cierre=ctx["cierres"].get(mes))


@app.get("/clientes/{cliente_id}/tablero")
def tablero(cliente_id: str, mes: date, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """Scorecard del mes: KPIs vs mes anterior, presupuesto y meta; serie de 12 meses; proyección a 90 días."""
    _cliente_o_404(r, cliente_id, u)
    mes = mes.replace(day=1)
    anterior = mes_anterior(mes)
    asientos, avisos, indices = _asientos(r, cliente_id)
    cierres = r.cierres(cliente_id)
    serie_meses = [m for m in sorted({a.mes for a in asientos} | {mes, anterior}) if m <= mes][-12:]
    pyl = pyl_mensual(asientos, serie_meses, {m: c.amortizacion_mes for m, c in cierres.items()})
    ctx = {"indices": indices, "cuentas": r.cuentas(cliente_id), "tesoreria": r.tesoreria(cliente_id),
           "comprobantes": r.comprobantes(cliente_id), "laborales": r.costos_laborales(cliente_id), "asientos": asientos,
           "pyl": pyl, "cierres": cierres, "avisos": set()}
    actual = _datos_mes(r, cliente_id, mes, ctx)

    # proyección a 30/60/90 días desde el corte (hoy si es el mes en curso, si no el fin del mes elegido)
    corte = min(date.today(), fin_de_mes(mes))
    emitidos = [TDoc(c.fecha, c.total_ars) for c in ctx["comprobantes"] if c.sentido == "emitido"]
    recibidos = [TDoc(c.fecha, c.total_ars) for c in ctx["comprobantes"] if c.sentido == "recibido"]
    bases = r.presupuesto(cliente_id, corte.year) | r.presupuesto(cliente_id, corte.year + 1)
    def sin_factura(m: date, excluir_personal: bool) -> Decimal:
        total = Decimal(0)
        for (rubro, mm), base in bases.items():
            info = seeds.rubros().get(rubro, {})
            if mm != m or not info.get("sin_factura") or info.get("linea_pl") == "NO P&L":
                continue
            if excluir_personal and info["linea_pl"] == "5 Personal":
                continue
            total += nominal(base, info.get("indice_ajuste") or "IPC", m, date(m.year, 1, 1), indices) * int(info.get("signo") or -1)
        return total
    m0 = corte.replace(day=1)
    proy = proyeccion_caja(
        corte, actual.disponibilidades,
        cobranzas=pendientes_fifo(emitidos, ctx_cobros(ctx, corte, "COB01"), PLAZO_COBRO_PAGO_DIAS, corte),
        pagos=pendientes_fifo(recibidos, -ctx_cobros(ctx, corte, "PAG01"), PLAZO_COBRO_PAGO_DIAS, corte),
        sueldos_devengados=actual.remuneraciones_a_pagar,
        presupuesto_sin_factura=(sin_factura(m0, True), sin_factura(mes_siguiente(m0), False), sin_factura(mes_siguiente(mes_siguiente(m0)), False)),
        pct_recupero_vencidas=PCT_RECUPERO_VENCIDAS)
    actual.saldo_90_dias = proy["tramos"][-1]["saldo"]

    # presupuesto del mes para los KPIs de resultado
    filas_ctrl = control(mes, r.presupuesto(cliente_id, mes.year), real_por_rubro(asientos, seeds.rubros()), seeds.rubros(), indices, TOLERANCIA_DEFECTO)
    suma = lambda pref: sum((f.ppto_mes * f.signo for f in filas_ctrl if f.linea_pl.split(" ")[0] in pref), Decimal(0))
    ing_p, var_p, fijos_p = suma({"1", "2", "3"}), suma({"4"}), suma({"5", "6", "7", "8"})
    ppto = {}
    if ing_p:
        ppto = {"ingresos_netos": ing_p, "margen_contribucion_pct": (ing_p + var_p) / ing_p, "ebitda": ing_p + var_p + fijos_p,
                "ebitda_pct": (ing_p + var_p + fijos_p) / ing_p}

    secciones = armar_tablero(kpis_del_mes(actual), kpis_del_mes(_datos_mes(r, cliente_id, anterior, ctx)), ppto, r.metas(cliente_id))
    if mes not in cierres:
        ctx["avisos"].add("Sin datos de cierre del mes (stock, bienes de uso, deudas): días de stock, prueba ácida, endeudamiento y Dupont no se calculan.")
    return {"mes": mes, "secciones": secciones,
            "serie": {"meses": [m.isoformat() for m in serie_meses],
                      **{k: [pyl[k].get(m) for m in serie_meses] for k in ("ingresos_netos", "margen_contribucion", "ebitda")}},
            "proyeccion": proy, "avisos": sorted(ctx["avisos"]) + avisos.lista()}


def ctx_cobros(ctx: dict, hasta: date, rubro: str) -> Decimal:
    tc = lambda m, cot: Decimal(1) if cot in ("", "ARS") else (ctx["indices"].tc(m, cot) if ctx["indices"] else None) or Decimal(0)
    return sum((x.importe_firmado * tc(x.fecha.replace(day=1), ctx["cuentas"][x.cuenta].cotizacion if x.cuenta in ctx["cuentas"] else "ARS")
                for x in ctx["tesoreria"] if x.rubro == rubro and x.fecha <= hasta), Decimal(0))


def mes_siguiente(m: date) -> date:
    return (fin_de_mes(m) + timedelta(days=1))


def _texto_excel(v: str) -> str:
    """openpyxl escribe como FÓRMULA todo texto que empieza con '=': un nombre de cliente o un código cargado por
    un usuario podría ejecutar algo al abrir el Excel. Se neutraliza con un apóstrofo (inyección de fórmulas)."""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@app.get("/clientes/{cliente_id}/tablero.xlsx")
def tablero_excel(cliente_id: str, mes: date, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    """El mismo tablero en Excel: hoja KPIs con semáforo, hoja Proyección y hoja Serie (números, no texto)."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    t = tablero(cliente_id, mes, u, r)
    nombre = r.cliente(cliente_id).nombre
    formatos = {"ars": "#,##0.00;[Red]-#,##0.00", "pct": "0.0%", "dias": "0", "x": "0.00", "num": "0"}
    colores = {"verde": "D1FADF", "amarillo": "FEF0C7", "rojo": "FEE4E2"}
    textos = {"verde": "Cumple", "amarillo": "Cerca", "rojo": "Fuera"}
    negrita = Font(bold=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "KPIs"
    ws.append([_texto_excel(f"Tablero · {nombre}"), t["mes"].strftime("%m/%Y")])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Sección", "Indicador", "Valor", "Mes anterior", "Variación", "Presupuesto", "Meta", "Dirección", "Semáforo"])
    for c in ws[3]:
        c.font = negrita
    for s in t["secciones"]:
        for k in s["kpis"]:
            ws.append([s["titulo"], k.nombre, k.valor, k.anterior, k.variacion, k.presupuesto, k.meta, k.direccion,
                       textos.get(k.semaforo or "", "")])
            fila = ws.max_row
            for col in "CDFG":
                ws[f"{col}{fila}"].number_format = formatos[k.formato]
            ws[f"E{fila}"].number_format = "0.0%"
            if k.semaforo:
                ws[f"I{fila}"].fill = PatternFill("solid", fgColor=colores[k.semaforo])
    for col, ancho in zip("ABCDEFGHI", (20, 32, 18, 18, 12, 18, 16, 10, 10)):
        ws.column_dimensions[col].width = ancho
    if t["avisos"]:
        ws.append([])
        ws.append(["Avisos"])
        ws.cell(ws.max_row, 1).font = negrita
        for a in t["avisos"]:
            ws.append([_texto_excel(a)])

    wp = wb.create_sheet("Proyección")
    wp.append(["Desde", "Hasta", "Flujo", "Saldo"])
    for tr in t["proyeccion"]["tramos"]:
        wp.append([tr["desde"], tr["hasta"], tr["flujo"], tr["saldo"]])
    wp.append(["Necesidad de financiamiento", None, None, t["proyeccion"]["necesidad_financiamiento"]])
    for fila in wp.iter_rows(min_row=2, min_col=3, max_col=4):
        for c in fila:
            c.number_format = formatos["ars"]
    for col in "ABCD":
        wp.column_dimensions[col].width = 18
    wp["A1"].font = wp["B1"].font = wp["C1"].font = wp["D1"].font = negrita

    wserie = wb.create_sheet("Serie")
    wserie.append(["Mes", "Ingresos netos", "Margen de contribución", "EBITDA"])
    for i, m in enumerate(t["serie"]["meses"]):
        wserie.append([date.fromisoformat(m), t["serie"]["ingresos_netos"][i], t["serie"]["margen_contribucion"][i], t["serie"]["ebitda"][i]])
        wserie.cell(wserie.max_row, 1).number_format = "mm/yyyy"
        for col in (2, 3, 4):
            wserie.cell(wserie.max_row, col).number_format = formatos["ars"]
    for col in "ABCD":
        wserie.column_dimensions[col].width = 22

    buf = BytesIO()
    wb.save(buf)
    archivo = f"tablero_{t['mes'].strftime('%Y-%m')}.xlsx"
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{archivo}"'})


@app.get("/clientes/{cliente_id}/lotes")
def listar_lotes(cliente_id: str, estado: str | None = None, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    return [{"id": l.id, "documento": l.documento, "cuenta": l.cuenta, "estado": l.estado, "resumen": l.resultado.resumen()}
            for l in r.lotes(cliente_id, estado)]


# ------------------------------------------------------------------ ingesta
TAMANO_MAXIMO = int(os.environ.get("TAMANO_MAXIMO_MB", "20")) * 1024 * 1024
UMBRAL_ASINCRONO = int(os.environ.get("UMBRAL_ASINCRONO_KB", "2048")) * 1024   # más grande → cola de trabajos


async def _leer_con_tope(archivo: UploadFile) -> bytes:
    """Lee por partes y corta apenas se pasa del máximo (no carga en memoria un archivo de 2 GB)."""
    partes, total = [], 0
    while trozo := await archivo.read(1024 * 1024):
        total += len(trozo)
        if total > TAMANO_MAXIMO:
            raise HTTPException(413, f"El archivo supera el máximo de {TAMANO_MAXIMO // 1024 // 1024} MB.")
        partes.append(trozo)
    return b"".join(partes)


@app.post("/clientes/{cliente_id}/documentos", status_code=201)
async def subir_documento(cliente_id: str, archivo: UploadFile = File(...), cuenta: str | None = Form(None),
                          perfil: str | None = Form(None), u: Usuario = Depends(usuario_actual),
                          r: Repositorio = Depends(repo), alm: Almacenamiento = Depends(almacen)):
    _cliente_o_404(r, cliente_id, u)
    contenido = await _leer_con_tope(archivo)
    nombre = nombre_seguro(archivo.filename)
    try:
        validar_archivo(nombre, contenido)
    except ArchivoRechazado as e:
        log.warning("archivo_rechazado", extra={"cliente_id": cliente_id, "archivo": nombre, "motivo": str(e)})
        raise HTTPException(e.status, str(e))
    sha = hashlib.sha256(contenido).hexdigest()
    if r.documento_existe(cliente_id, sha):
        raise HTTPException(409, "Este mismo archivo ya se subió para este cliente.")
    if cuenta and cuenta not in r.cuentas(cliente_id):
        raise HTTPException(422, f"La cuenta {cuenta} no existe para este cliente.")
    # el original se guarda siempre: trazabilidad y reproceso si cambian perfiles o reglas
    ruta = alm.guardar(f"clientes/{cliente_id}/{sha[:16]}-{nombre}", contenido,
                       archivo.content_type or "application/octet-stream")
    parametros = {"nombre": nombre, "ruta": ruta, "sha256": sha, "cuenta": cuenta, "perfil": perfil}
    if len(contenido) <= UMBRAL_ASINCRONO:
        try:
            return procesar_documento(r, cliente_id, nombre, contenido, sha, ruta, cuenta, perfil)
        except EnviarACola:
            parametros["ocr"] = True
    t = r.encolar(cliente_id, "procesar_documento", parametros)
    return JSONResponse(status_code=202, content={"tipo": "en_cola", "trabajo_id": t.id, "estado": "pendiente",
                                                  "motivo": "ocr" if parametros.get("ocr") else "tamano"})


# ------------------------------------------------------------------ plan de cuentas contable
class CuentaContableIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=12)
    nombre: str = Field(min_length=1, max_length=120)
    imputable: bool = True
    ajustable: bool = False
    expuesta: bool = False
    padre: str | None = None
    clase: int | None = None          # por defecto, la de la agrupadora
    comentario: str = ""


class CuentaContableCambio(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    imputable: bool | None = None
    ajustable: bool | None = None
    expuesta: bool | None = None
    comentario: str | None = None


class VinculoRubrosIn(BaseModel):
    rubros: list[str]


def _plan(r: Repositorio, cliente_id: str) -> dict:
    """El plan del cliente; la primera vez se crea con la plantilla."""
    plan = r.plan_cuentas(cliente_id)
    if not plan:
        r.iniciar_plan(cliente_id, plan_cuentas.desde_plantilla(seeds.plan_cuentas()))
        plan = r.plan_cuentas(cliente_id)
    return plan


def _rubros_usados(r: Repositorio, cliente_id: str) -> set[str]:
    asientos, _, _ = _asientos(r, cliente_id)
    return {a.rubro for a in asientos} | {m.rubro for m in r.tesoreria(cliente_id)}


@app.get("/clientes/{cliente_id}/plan-cuentas")
def ver_plan_cuentas(cliente_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    plan, vinculos = _plan(r, cliente_id), r.rubro_cuenta(cliente_id)
    en_uso = plan_cuentas.cuentas_en_uso(vinculos, _rubros_usados(r, cliente_id))
    rubros_de: dict[str, list[str]] = {}
    for rubro, cuenta in vinculos.items():
        rubros_de.setdefault(cuenta, []).append(rubro)
    cuentas = [{**c.como_dict(), "rubros": sorted(rubros_de.get(c.codigo, [])), "en_uso": c.codigo in en_uso,
                "subcuentas": sum(1 for x in plan.values() if x.padre == c.codigo)}
               for c in sorted(plan.values(), key=lambda c: c.codigo)]
    sin_cuenta = sorted(set(seeds.rubros()) - set(vinculos))
    return {"cuentas": cuentas, "rubros_sin_cuenta": sin_cuenta}


@app.post("/clientes/{cliente_id}/plan-cuentas", status_code=201)
def alta_cuenta_contable(cliente_id: str, body: CuentaContableIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    plan = _plan(r, cliente_id)
    padre = plan.get(body.padre) if body.padre else None
    clase = body.clase or (padre.clase if padre else int(body.codigo[0]) if body.codigo[0] in "12345" else 0)
    nueva = plan_cuentas.CuentaContable(body.codigo.strip(), body.nombre.strip(), body.imputable, body.ajustable,
                                        body.expuesta, clase, body.padre or None, body.comentario.strip())
    try:
        plan_cuentas.validar_alta(plan, nueva)
    except plan_cuentas.PlanInvalido as e:
        raise HTTPException(422, str(e))
    r.guardar_cuenta_contable(cliente_id, nueva)
    return nueva.como_dict()


@app.patch("/clientes/{cliente_id}/plan-cuentas/{codigo}")
def editar_cuenta_contable(cliente_id: str, codigo: str, body: CuentaContableCambio, u: Usuario = Depends(usuario_actual),
                           r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    plan = _plan(r, cliente_id)
    if codigo not in plan:
        raise HTTPException(404, f"La cuenta {codigo} no existe")
    cuenta = plan[codigo]
    if body.imputable is not None and body.imputable != cuenta.imputable:
        try:
            plan_cuentas.validar_cambio_imputable(plan, codigo, body.imputable, codigo in r.rubro_cuenta(cliente_id).values())
        except plan_cuentas.PlanInvalido as e:
            raise HTTPException(422, str(e))
    for campo, valor in body.model_dump(exclude_none=True).items():
        setattr(cuenta, campo, valor.strip() if isinstance(valor, str) else valor)
    r.guardar_cuenta_contable(cliente_id, cuenta)
    return cuenta.como_dict()


@app.delete("/clientes/{cliente_id}/plan-cuentas/{codigo}", status_code=204)
def baja_cuenta_contable(cliente_id: str, codigo: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    plan = _plan(r, cliente_id)
    en_uso = plan_cuentas.cuentas_en_uso(r.rubro_cuenta(cliente_id), _rubros_usados(r, cliente_id))
    try:
        plan_cuentas.validar_baja(plan, codigo, en_uso)
    except plan_cuentas.PlanInvalido as e:
        raise HTTPException(409 if "movimientos" in str(e) or "agrupa" in str(e) else 404, str(e))
    r.borrar_cuenta_contable(cliente_id, codigo)
    return Response(status_code=204)


@app.put("/clientes/{cliente_id}/plan-cuentas/{codigo}/rubros")
def vincular_rubros(cliente_id: str, codigo: str, body: VinculoRubrosIn, u: Usuario = Depends(usuario_actual),
                    r: Repositorio = Depends(repo)):
    """Los rubros que se imputan a esta cuenta. Un rubro va a una sola cuenta: si estaba en otra, se mueve."""
    _cliente_o_404(r, cliente_id, u)
    plan = _plan(r, cliente_id)
    cuenta = plan.get(codigo)
    if not cuenta:
        raise HTTPException(404, f"La cuenta {codigo} no existe")
    if not cuenta.imputable and body.rubros:
        raise HTTPException(422, "Solo las cuentas imputables reciben rubros; esta es agrupadora.")
    invalidos = [x for x in body.rubros if x not in seeds.rubros()]
    if invalidos:
        raise HTTPException(422, f"Rubros inexistentes: {', '.join(invalidos)}")
    for rubro, actual in r.rubro_cuenta(cliente_id).items():
        if actual == codigo and rubro not in body.rubros:
            r.vincular_rubro(cliente_id, rubro, None)
    for rubro in body.rubros:
        r.vincular_rubro(cliente_id, rubro, codigo)
    return {"cuenta": codigo, "rubros": sorted(body.rubros)}


def _documento_o_404(r: Repositorio, documento_id: str, u: Usuario) -> Documento:
    doc = r.documento(documento_id)
    if not doc or not r.puede_ver_cliente(u.id, doc.cliente_id):
        raise HTTPException(404, "Documento inexistente")
    return doc


MAX_FILAS_VISTA = 500
TIPOS_MIME = {".pdf": "application/pdf", ".csv": "text/csv; charset=utf-8", ".txt": "text/plain; charset=utf-8",
              ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12"}


@app.get("/documentos/{documento_id}/vista")
def ver_documento(documento_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo),
                  alm: Almacenamiento = Depends(almacen)):
    """Lo que el sistema lee del archivo (filas, o texto si es un PDF sin tablas), para revisarlo en pantalla."""
    doc = _documento_o_404(r, documento_id, u)
    try:
        leido = leer_archivo(doc.nombre, alm.leer(doc.storage_path))
    except FormatoNoSoportado as e:
        raise HTTPException(415, str(e))
    filas = [[("" if c is None else str(c)) for c in f] for f in leido.filas[:MAX_FILAS_VISTA]]
    return {"id": doc.id, "nombre": doc.nombre, "tipo": doc.tipo, "estado": doc.estado, "detalle": doc.detalle,
            "extension": leido.extension, "hojas": leido.hojas, "filas": filas, "total_filas": len(leido.filas),
            "texto": leido.texto[:20000] if leido.extension == ".pdf" else ""}


@app.get("/documentos/{documento_id}/archivo")
def descargar_documento(documento_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo),
                        alm: Almacenamiento = Depends(almacen)):
    """El archivo original tal como se subió (para abrirlo o guardarlo)."""
    doc = _documento_o_404(r, documento_id, u)
    ext = os.path.splitext(doc.nombre)[1].lower()
    nombre = doc.nombre.replace('"', "")
    return Response(alm.leer(doc.storage_path), media_type=TIPOS_MIME.get(ext, "application/octet-stream"),
                    headers={"Content-Disposition": f'inline; filename="{nombre}"',
                             "X-Content-Type-Options": "nosniff"})


@app.delete("/documentos/{documento_id}", status_code=204)
def eliminar_documento(documento_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo),
                       alm: Almacenamiento = Depends(almacen)):
    """Borra el documento, el archivo original y todo lo que se cargó desde él (comprobantes, F.931, ventas
    por ítem, el lote de un extracto). Un extracto que ya pasó movimientos a Tesorería no se borra."""
    doc = _documento_o_404(r, documento_id, u)
    lote = r.lote(doc.lote_id) if doc.lote_id else None
    if lote and lote.estado == "aprobado" and lote.resultado.movimientos:
        raise HTTPException(409, "Este extracto ya pasó sus movimientos a Tesorería: no se puede eliminar sin borrar esos movimientos.")
    r.borrar_documento(doc.id)
    try:
        alm.borrar(doc.storage_path)
    except Exception as e:  # noqa: BLE001 — el registro ya no está; un archivo huérfano no rompe nada
        log.warning("archivo_no_borrado", extra={"error": repr(e)})
    log.info("documento_eliminado", extra={"cliente_id": doc.cliente_id, "tipo": doc.tipo})
    return Response(status_code=204)


@app.post("/documentos/{documento_id}/reprocesar")
def reprocesar_documento(documento_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo),
                         alm: Almacenamiento = Depends(almacen)):
    """Vuelve a leer el archivo original guardado y reemplaza lo que se había cargado desde él. Sirve cuando
    mejora el lector de un formato (o se corrigió un perfil). No toca extractos ya aprobados en Tesorería."""
    doc = r.documento(documento_id)
    if not doc or not r.puede_ver_cliente(u.id, doc.cliente_id):
        raise HTTPException(404, "Documento inexistente")
    if doc.tipo == "planilla_v2":
        raise HTTPException(422, "La planilla v2 se importa una sola vez al dar de alta el cliente.")
    lote = r.lote(doc.lote_id) if doc.lote_id else None
    if lote and lote.estado == "aprobado" and lote.resultado.movimientos:
        raise HTTPException(409, "Este extracto ya pasó sus movimientos a Tesorería: no se puede reprocesar.")
    contenido = alm.leer(doc.storage_path)
    r.borrar_documento(doc.id)
    log.info("documento_reprocesado", extra={"cliente_id": doc.cliente_id, "tipo": doc.tipo})
    try:
        return procesar_documento(r, doc.cliente_id, doc.nombre, contenido, doc.sha256, doc.storage_path,
                                  lote.cuenta if lote else None, None)
    except EnviarACola:
        t = r.encolar(doc.cliente_id, "procesar_documento", {"nombre": doc.nombre, "ruta": doc.storage_path, "sha256": doc.sha256,
                                                             "cuenta": lote.cuenta if lote else None, "perfil": None, "ocr": True})
        return JSONResponse(status_code=202, content={"tipo": "en_cola", "trabajo_id": t.id, "estado": "pendiente", "motivo": "ocr"})


@app.get("/trabajos/{trabajo_id}")
def ver_trabajo(trabajo_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    t = r.trabajo(trabajo_id)
    if not t or not r.puede_ver_cliente(u.id, t.cliente_id):
        raise HTTPException(404, "Trabajo inexistente")
    return {"id": t.id, "tipo": t.tipo, "estado": t.estado, "intentos": t.intentos, "resultado": t.resultado, "error": t.error}


class EnviarACola(Exception):
    """El documento necesita OCR: es lento, lo hace el worker."""


def procesar_documento(r: Repositorio, cliente_id: str, nombre: str, contenido: bytes, sha: str, ruta: str,
                       cuenta: str | None, perfil: str | None, permitir_ocr: bool = False) -> dict:
    """Lee, detecta el tipo y registra el documento. Lo usan la subida directa y el worker de la cola."""
    try:
        leido = leer_archivo(nombre, contenido)
    except FormatoNoSoportado as e:
        raise HTTPException(415, str(e))
    if leido.extension == ".pdf" and ocr.es_escaneado(leido, ocr.contar_paginas(contenido)):
        if not permitir_ocr:
            raise EnviarACola()
        try:
            leido = ocr.leer_con_ocr(nombre, contenido, ocr.motor_disponible())
        except (ocr.SinMotorOCR, ValueError) as e:
            raise HTTPException(422, str(e))
        res = _registrar(r, cliente_id, nombre, contenido, sha, ruta, cuenta, perfil, leido)
        return res | {"estado": "con_alertas", "leido_por_ocr": True,
                      "aviso_ocr": "Leído por OCR desde una imagen: revisá fechas e importes antes de aprobar."}
    return _registrar(r, cliente_id, nombre, contenido, sha, ruta, cuenta, perfil, leido)


def _registrar(r: Repositorio, cliente_id: str, nombre: str, contenido: bytes, sha: str, ruta: str,
               cuenta: str | None, perfil: str | None, leido) -> dict:
    tipo = tipo_documento(leido)
    cuentas = r.cuentas(cliente_id)
    if tipo == "extracto" and (not cuenta or cuenta not in cuentas):
        raise HTTPException(422, "Para un extracto indicá la cuenta destino (código existente).")

    if tipo == "f931":
        dj = f931.leer_f931(leido.texto)
        estado = "procesado" if dj.completa else "con_alertas"
        doc = r.registrar_documento(Documento("", cliente_id, nombre, tipo, estado, sha, len(contenido), ruta,
                                              detalle="" if dj.completa else "Faltan: " + ", ".join(dj.faltantes)))
        if dj.completa:
            r.guardar_f931(cliente_id, doc.id, dj)   # costo laboral devengado del período
        return {"tipo": tipo, "estado": estado, "documento_id": doc.id, "f931": dj}
    if tipo == "mis_comprobantes":
        comps = comprobantes_arca.leer_mis_comprobantes(leido.filas)
        sentido = comps[0].sentido if comps else "emitido"
        doc = r.registrar_documento(Documento("", cliente_id, nombre, tipo, "procesado", sha, len(contenido), ruta,
                                              detalle=f"{len(comps)} comprobantes {sentido}s"))
        nuevos, repetidos = r.guardar_comprobantes(cliente_id, doc.id, comps)
        sin_rubro = sum(1 for c in r.comprobantes(cliente_id, "recibido", sin_rubro=True))
        return {"tipo": tipo, "estado": "con_alertas" if sentido == "recibido" and sin_rubro else "procesado",
                "documento_id": doc.id, "sentido": sentido, "comprobantes": len(comps), "nuevos": nuevos,
                "repetidos": repetidos, "recibidos_sin_rubro": sin_rubro,
                "total": sum((c.total for c in comps), Decimal(0))}

    if tipo == "detalle_ventas":
        lineas = detalle_ventas.leer_detalle_ventas(leido.filas)
        conocidos = r.items(cliente_id)
        desconocidos = sorted({l.item for l in lineas if l.item not in conocidos})
        doc = r.registrar_documento(Documento("", cliente_id, nombre, tipo, "con_alertas" if desconocidos else "procesado",
                                              sha, len(contenido), ruta, detalle=f"{len(lineas)} renglones de venta"))
        nuevas, repetidas = r.guardar_lineas_venta(cliente_id, doc.id, lineas)
        return {"tipo": tipo, "estado": "con_alertas" if desconocidos else "procesado", "documento_id": doc.id,
                "renglones": len(lineas), "nuevos": nuevas, "repetidos": repetidas, "items_desconocidos": desconocidos}

    perfiles = seeds.perfiles()
    elegido = next((p for p in perfiles if p.codigo == (perfil or cuentas[cuenta].perfil_defecto)), None)
    res = procesar_extracto(leido, cuenta, perfiles, _motor(r, cliente_id), set(seeds.rubros()),
                            r.tesoreria(cliente_id), perfil=elegido, tipo_cuenta=cuentas[cuenta].tipo)
    if not res.movimientos:
        # un extracto sin movimientos leídos casi siempre es un formato que no se entendió: no se registra
        # (se puede volver a subir el mismo archivo cuando el formato esté soportado)
        raise HTTPException(422, "No se encontró ningún movimiento en el extracto. Si es un PDF, probá descargarlo "
                                 "del home banking en Excel o CSV; si el problema sigue, avisá con el nombre del banco.")
    lote = r.guardar_lote(Lote(id=str(uuid.uuid4()), cliente_id=cliente_id, cuenta=cuenta, documento=nombre,
                               resultado=res, sha256=sha, tamano_bytes=len(contenido), storage_path=ruta))
    resumen = res.resumen()
    estado = "con_alertas" if resumen["sin_regla"] or resumen["rubro_inexistente"] or resumen["duplicados"] else "procesado"
    return {"tipo": tipo, "estado": estado, "lote_id": lote.id, "resumen": resumen}


@app.get("/lotes/{lote_id}")
def ver_lote(lote_id: str, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    return _lote_json(r, _lote_o_404(r, lote_id, u))


@app.patch("/lotes/{lote_id}/movimientos/{mov_id}")
def corregir_movimiento(lote_id: str, mov_id: int, body: CorreccionIn, u: Usuario = Depends(usuario_actual),
                        r: Repositorio = Depends(repo)):
    lote = _lote_o_404(r, lote_id, u)
    if lote.estado != "pendiente":
        raise HTTPException(409, "El lote ya fue aprobado o descartado")
    try:
        mov = lote.resultado.movimientos[mov_id]
    except IndexError:
        raise HTTPException(404, "Movimiento inexistente")
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(mov, campo, valor or None)
    if "rubro" in body.model_fields_set:
        mov.regla_id, mov.regla_texto = None, "manual" if mov.rubro else None
    reprocesar(lote.resultado, _motor(r, lote.cliente_id), set(seeds.rubros()), r.tesoreria(lote.cliente_id))
    r.actualizar_lote(lote)
    return _mov_json(mov_id, mov)


@app.post("/clientes/{cliente_id}/reglas", status_code=201)
def crear_regla(cliente_id: str, body: ReglaIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    _cliente_o_404(r, cliente_id, u)
    if body.rubro not in seeds.rubros():
        raise HTTPException(422, f"Rubro {body.rubro} inexistente")
    prioridad = (max((x.prioridad for x in r.reglas_cliente(cliente_id)), default=0) + 10)
    regla = r.agregar_regla(Regla(**body.model_dump(), prioridad=prioridad, cliente_id=cliente_id))
    # la regla nueva se aplica en el acto a todos los lotes abiertos del cliente
    motor, reclasificados = _motor(r, cliente_id), 0
    for lote in r.lotes(cliente_id, "pendiente"):
        antes = sum(1 for m in lote.resultado.movimientos if m.rubro)
        reprocesar(lote.resultado, motor, set(seeds.rubros()), r.tesoreria(cliente_id))
        reclasificados += sum(1 for m in lote.resultado.movimientos if m.rubro) - antes
        r.actualizar_lote(lote)
    return {"regla": regla, "movimientos_reclasificados": reclasificados}


@app.post("/lotes/{lote_id}/aprobar")
def aprobar_lote(lote_id: str, body: AprobacionIn, u: Usuario = Depends(usuario_actual), r: Repositorio = Depends(repo)):
    lote = _lote_o_404(r, lote_id, u)
    if lote.estado != "pendiente":
        raise HTTPException(409, "El lote ya fue aprobado o descartado")
    if not lote.resultado.movimientos:
        raise HTTPException(409, "El extracto no tiene movimientos: no hay nada para aprobar.")
    bloqueados = [i for i, m in enumerate(lote.resultado.movimientos) if m.bloqueado]
    if bloqueados:
        raise HTTPException(409, {"mensaje": "Hay movimientos sin rubro válido", "movimientos": bloqueados})
    elegidos = _a_insertar(lote.resultado, False)
    r.insertar_tesoreria(lote.cliente_id, [MovimientoTesoreria(
        cuenta=m.cuenta, fecha=m.fecha, tipo=m.tipo, importe=m.importe, rubro=m.rubro, descripcion=m.descripcion,
        referencia=m.referencia, tercero=m.tercero, comprobante=m.comprobante, medio_pago=m.medio_pago,
        unidad_negocio=m.unidad_negocio) for m in elegidos], lote_id=lote.id)
    lote.estado = "aprobado"
    r.actualizar_lote(lote)
    return {"insertados": len(elegidos), "omitidos": len(lote.resultado.movimientos) - len(elegidos),
            "conciliacion": _conciliacion(r, lote)}

