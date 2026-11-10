"""Repositorio sobre PostgreSQL (Supabase o cualquier PostgreSQL 15+). Misma interfaz que RepositorioMemoria.

El backend se conecta con un rol con permisos sobre todas las tablas y controla el acceso en la
aplicación (puede_ver_cliente) antes de cada operación; las políticas RLS del esquema protegen además
el acceso directo desde el frontend con la clave pública de Supabase.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from app.api.repositorio import MAX_INTENTOS, Cliente, Cuenta, Documento, Lote, Miembro, Trabajo
from app.finanzas.asientos import ComprobanteRegistrado, CostoLaboral
from app.finanzas.indices import FilaIndice
from app.api.repositorio import DIAS_RECUPERO
from app.finanzas.inversiones import MovInversion
from app.finanzas.items import Item, LineaCompra, LineaVenta, Merma
from app.finanzas.plan_cuentas import CuentaContable
from app.finanzas.tablero import DatosCierre
from app.ingesta.comprobantes_arca import ComprobanteArca
from app.ingesta.f931 import DeclaracionF931
from psycopg.types.json import Jsonb
from app.ingesta.modelos import Alerta, MovimientoPropuesto, MovimientoTesoreria, Pata, Perfil, Regla
from app.ingesta.pipeline import ResultadoImportacion

_VISIBLE = """EXISTS (SELECT 1 FROM miembros m WHERE m.usuario_id = %(u)s AND m.organizacion_id = c.organizacion_id
              AND (m.cliente_id IS NULL OR m.cliente_id = c.id))"""


def _timeout(url: str) -> dict:
    """Si la URL no trae connect_timeout, 10 s: sin esto una base caída deja colgado el pedido."""
    return {} if "connect_timeout" in url else {"connect_timeout": 10}


def _es_uuid(v: str | None) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


class RepositorioPostgres:
    def __init__(self, url: str):
        self.url = url

    @contextmanager
    def _con(self) -> Iterator[psycopg.Connection]:
        # una conexión por operación; el pooler de Supabase (Supavisor) hace de pool.
        # prepare_threshold=None: el pooler en modo transacción (puerto 6543) no soporta sentencias preparadas.
        with psycopg.connect(self.url, row_factory=dict_row, prepare_threshold=None, **_timeout(self.url)) as con:
            yield con

    # ------------------------------------------------------------------ acceso
    def alta_usuario(self, usuario_id: str, email: str, organizacion: str) -> str:
        """Primer ingreso: crea el usuario, su organización y lo hace admin. Devuelve la organización."""
        with self._con() as con:
            con.execute("INSERT INTO usuarios (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (usuario_id, email))
            org = con.execute("INSERT INTO organizaciones (nombre) VALUES (%s) RETURNING id", (organizacion,)).fetchone()["id"]
            con.execute("INSERT INTO miembros (usuario_id, organizacion_id, rol) VALUES (%s, %s, 'admin')", (usuario_id, org))
            return str(org)

    def organizacion_de(self, usuario_id: str) -> str | None:
        if not _es_uuid(usuario_id):
            return None
        with self._con() as con:
            f = con.execute("SELECT organizacion_id FROM miembros WHERE usuario_id = %s ORDER BY id LIMIT 1", (usuario_id,)).fetchone()
        return str(f["organizacion_id"]) if f else None

    def rol_de(self, usuario_id: str) -> str | None:
        if not _es_uuid(usuario_id):
            return None
        with self._con() as con:
            f = con.execute("SELECT rol::text AS rol FROM miembros WHERE usuario_id = %s ORDER BY id LIMIT 1", (usuario_id,)).fetchone()
        return f["rol"] if f else None

    def miembros(self, organizacion_id: str) -> list[Miembro]:
        with self._con() as con:
            filas = con.execute("""SELECT m.usuario_id, u.email, m.rol::text AS rol FROM miembros m JOIN usuarios u ON u.id = m.usuario_id
                                   WHERE m.organizacion_id = %s AND m.cliente_id IS NULL ORDER BY u.email""", (organizacion_id,)).fetchall()
        return [Miembro(str(f["usuario_id"]), f["email"], f["rol"]) for f in filas]

    def agregar_miembro(self, organizacion_id: str, usuario_id: str, email: str, rol: str) -> None:
        with self._con() as con, con.transaction():
            otra = con.execute("SELECT organizacion_id FROM miembros WHERE usuario_id = %s AND organizacion_id <> %s LIMIT 1",
                               (usuario_id, organizacion_id)).fetchone()
            if otra:
                raise ValueError("Ese usuario ya pertenece a otra organización.")
            con.execute("INSERT INTO usuarios (id, email) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email",
                        (usuario_id, email))
            con.execute("""INSERT INTO miembros (usuario_id, organizacion_id, cliente_id, rol) VALUES (%s, %s, NULL, %s)
                           ON CONFLICT (usuario_id, organizacion_id, cliente_id) DO UPDATE SET rol = EXCLUDED.rol""",
                        (usuario_id, organizacion_id, rol))

    def cambiar_rol(self, organizacion_id: str, usuario_id: str, rol: str) -> None:
        with self._con() as con:
            con.execute("UPDATE miembros SET rol = %s WHERE organizacion_id = %s AND usuario_id = %s", (rol, organizacion_id, usuario_id))

    def quitar_miembro(self, organizacion_id: str, usuario_id: str) -> None:
        with self._con() as con:
            con.execute("DELETE FROM miembros WHERE organizacion_id = %s AND usuario_id = %s", (organizacion_id, usuario_id))

    def puede_ver_cliente(self, usuario_id: str, cliente_id: str) -> bool:
        if not (_es_uuid(usuario_id) and _es_uuid(cliente_id)):
            return False
        with self._con() as con:
            return bool(con.execute(f"SELECT 1 FROM clientes c WHERE c.id = %(c)s AND {_VISIBLE}",
                                    {"c": cliente_id, "u": usuario_id}).fetchone())

    # ------------------------------------------------------------------ clientes y maestros
    def crear_cliente(self, organizacion_id: str, nombre: str, cuit: str) -> Cliente:
        with self._con() as con:
            f = con.execute("""INSERT INTO clientes (organizacion_id, nombre, cuit, inicio_ejercicio)
                               VALUES (%s, %s, %s, date_trunc('year', current_date)::date) RETURNING id, creado_en""",
                            (organizacion_id, nombre, cuit)).fetchone()
            con.execute("INSERT INTO unidades_negocio (cliente_id, codigo, nombre) VALUES (%s, 'GENERAL', 'General')", (f["id"],))
        return Cliente(str(f["id"]), nombre, cuit, organizacion_id, f["creado_en"])

    def clientes(self, usuario_id: str) -> list[Cliente]:
        if not _es_uuid(usuario_id):
            return []
        with self._con() as con:
            filas = con.execute(f"SELECT c.* FROM clientes c WHERE c.activo AND c.archivado_en IS NULL AND {_VISIBLE} ORDER BY c.nombre",
                                {"u": usuario_id}).fetchall()
        return [Cliente(str(f["id"]), f["nombre"], f["cuit"] or "", str(f["organizacion_id"]), f["creado_en"]) for f in filas]

    def cliente(self, cliente_id: str) -> Cliente | None:
        if not _es_uuid(cliente_id):
            return None
        with self._con() as con:
            f = con.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,)).fetchone()
        return Cliente(str(f["id"]), f["nombre"], f["cuit"] or "", str(f["organizacion_id"]), f["creado_en"],
                       f["archivado_en"]) if f else None

    def archivar_cliente(self, cliente_id: str) -> None:
        with self._con() as con:
            con.execute("UPDATE clientes SET archivado_en = now() WHERE id = %s", (cliente_id,))

    def restaurar_cliente(self, cliente_id: str) -> bool:
        if not _es_uuid(cliente_id):
            return False
        with self._con() as con:
            return con.execute("""UPDATE clientes SET archivado_en = NULL WHERE id = %s
                                  AND archivado_en > now() - make_interval(days => %s)""",
                               (cliente_id, DIAS_RECUPERO)).rowcount == 1

    def clientes_archivados(self, usuario_id: str) -> list[Cliente]:
        if not _es_uuid(usuario_id):
            return []
        with self._con() as con:
            filas = con.execute(f"""SELECT c.* FROM clientes c WHERE c.archivado_en > now() - make_interval(days => %(d)s)
                                    AND {_VISIBLE} ORDER BY c.archivado_en DESC""", {"u": usuario_id, "d": DIAS_RECUPERO}).fetchall()
        return [Cliente(str(f["id"]), f["nombre"], f["cuit"] or "", str(f["organizacion_id"]), f["creado_en"], f["archivado_en"])
                for f in filas]

    def movs_inversion(self, cliente_id: str) -> list:
        with self._con() as con:
            filas = con.execute("SELECT * FROM inversiones_movimientos WHERE cliente_id = %s ORDER BY fecha, creado_en",
                                (cliente_id,)).fetchall()
        return [MovInversion(f["fecha"], f["instrumento"], f["nombre"], f["tipo"], f["importe"], f["moneda"], str(f["id"]))
                for f in filas]

    def guardar_mov_inversion(self, cliente_id: str, mov) -> object:
        with self._con() as con:
            mov.id = str(con.execute("""INSERT INTO inversiones_movimientos (cliente_id, fecha, instrumento, nombre, tipo, importe, moneda)
                                         VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                                      (cliente_id, mov.fecha, mov.instrumento, mov.nombre, mov.tipo, mov.importe, mov.moneda)).fetchone()["id"])
        return mov

    def borrar_mov_inversion(self, cliente_id: str, mov_id: str) -> bool:
        if not _es_uuid(mov_id):
            return False
        with self._con() as con:
            return con.execute("DELETE FROM inversiones_movimientos WHERE id = %s AND cliente_id = %s",
                               (mov_id, cliente_id)).rowcount == 1

    def agregar_cuenta(self, cliente_id: str, cuenta: Cuenta) -> Cuenta:
        with self._con() as con:
            con.execute("""
                INSERT INTO cuentas (cliente_id, codigo, nombre, tipo, cotizacion, saldo_inicial, fecha_saldo_inicial, perfil_defecto_id)
                VALUES (%(c)s, %(codigo)s, %(nombre)s, %(tipo)s, %(cot)s, %(si)s,
                        COALESCE(%(fsi)s, (SELECT inicio_ejercicio FROM clientes WHERE id = %(c)s)),
                        (SELECT id FROM perfiles_importacion WHERE codigo = %(perfil)s AND (cliente_id = %(c)s OR cliente_id IS NULL)
                         ORDER BY cliente_id NULLS LAST LIMIT 1))
                ON CONFLICT (cliente_id, codigo) DO UPDATE SET nombre = EXCLUDED.nombre, tipo = EXCLUDED.tipo,
                    cotizacion = EXCLUDED.cotizacion, saldo_inicial = EXCLUDED.saldo_inicial,
                    fecha_saldo_inicial = EXCLUDED.fecha_saldo_inicial, perfil_defecto_id = EXCLUDED.perfil_defecto_id""",
                {"c": cliente_id, "codigo": cuenta.codigo, "nombre": cuenta.nombre, "tipo": cuenta.tipo, "cot": cuenta.cotizacion,
                 "si": cuenta.saldo_inicial, "fsi": cuenta.fecha_saldo_inicial, "perfil": cuenta.perfil_defecto})
        return cuenta

    def cuentas(self, cliente_id: str) -> dict[str, Cuenta]:
        with self._con() as con:
            filas = con.execute("""SELECT cu.*, p.codigo AS perfil FROM cuentas cu
                                   LEFT JOIN perfiles_importacion p ON p.id = cu.perfil_defecto_id
                                   WHERE cu.cliente_id = %s AND cu.activa ORDER BY cu.codigo""", (cliente_id,)).fetchall()
        return {f["codigo"]: Cuenta(f["codigo"], f["nombre"], f["tipo"], f["cotizacion"], f["saldo_inicial"],
                                    f["fecha_saldo_inicial"], f["perfil"]) for f in filas}

    def agregar_regla(self, regla: Regla) -> Regla:
        with self._con() as con:
            f = con.execute("""
                INSERT INTO reglas_clasificacion (cliente_id, prioridad, texto, cuenta_id, tipo, rubro_codigo, medio_pago, comentario)
                VALUES (%(c)s, %(p)s, %(t)s, (SELECT id FROM cuentas WHERE cliente_id = %(c)s AND codigo = %(cta)s),
                        %(tipo)s, %(r)s, %(m)s, %(com)s) RETURNING id""",
                {"c": regla.cliente_id, "p": regla.prioridad, "t": regla.texto, "cta": regla.cuenta, "tipo": regla.tipo,
                 "r": regla.rubro, "m": regla.medio_pago, "com": regla.comentario}).fetchone()
        regla.id = str(f["id"])
        return regla

    def reglas_cliente(self, cliente_id: str) -> list[Regla]:
        with self._con() as con:
            filas = con.execute("""SELECT r.*, cu.codigo AS cuenta FROM reglas_clasificacion r
                                   LEFT JOIN cuentas cu ON cu.id = r.cuenta_id
                                   WHERE r.cliente_id = %s AND r.activa ORDER BY r.prioridad""", (cliente_id,)).fetchall()
        return [Regla(texto=f["texto"], rubro=f["rubro_codigo"], prioridad=f["prioridad"], tipo=f["tipo"], cuenta=f["cuenta"],
                      medio_pago=f["medio_pago"], comentario=f["comentario"], cliente_id=cliente_id, id=str(f["id"]))
                for f in filas]

    # ------------------------------------------------------------------ ingesta
    def documento_existe(self, cliente_id: str, sha256: str) -> bool:
        with self._con() as con:
            return bool(con.execute("SELECT 1 FROM documentos WHERE cliente_id = %s AND sha256 = %s AND estado <> 'descartado'",
                                    (cliente_id, sha256)).fetchone())

    def registrar_documento(self, doc: Documento) -> Documento:
        with self._con() as con:
            f = con.execute("""INSERT INTO documentos (cliente_id, nombre, extension, tipo_detectado, storage_path, sha256, tamano_bytes, estado, error)
                               VALUES (%s, %s, lower(substring(%s from '\\.[^.]*$')), %s, %s, %s, %s, %s, %s) RETURNING id, subido_en""",
                            (doc.cliente_id, doc.nombre, doc.nombre, doc.tipo, doc.storage_path, doc.sha256, doc.tamano_bytes,
                             doc.estado, doc.detalle or None)).fetchone()
        doc.id, doc.subido_en = str(f["id"]), f["subido_en"]
        return doc

    _SELECT_DOCS = """SELECT d.*, l.id AS lote_id, l.estado AS estado_lote,
                             (SELECT count(*) FROM movimientos_staging s WHERE s.lote_id = l.id) AS movs
                      FROM documentos d LEFT JOIN lotes_importacion l ON l.documento_id = d.id"""

    @staticmethod
    def _documento(f) -> Documento:
        return Documento(str(f["id"]), str(f["cliente_id"]), f["nombre"], f["tipo_detectado"] or "",
                         "aprobado" if f["estado_lote"] == "aprobado" else f["estado"], f["sha256"], f["tamano_bytes"],
                         f["storage_path"], str(f["lote_id"]) if f["lote_id"] else None,
                         f"{f['movs']} movimientos" if f["lote_id"] else (f["error"] or ""), f["subido_en"])

    def documentos(self, cliente_id: str) -> list[Documento]:
        with self._con() as con:
            filas = con.execute(self._SELECT_DOCS + " WHERE d.cliente_id = %s ORDER BY d.subido_en DESC", (cliente_id,)).fetchall()
        return [self._documento(f) for f in filas]

    def documento(self, documento_id: str) -> Documento | None:
        if not _es_uuid(documento_id):
            return None
        with self._con() as con:
            f = con.execute(self._SELECT_DOCS + " WHERE d.id = %s", (documento_id,)).fetchone()
        return self._documento(f) if f else None

    def borrar_documento(self, documento_id: str) -> None:
        """Borra el documento y TODO lo que se cargó desde él (para reprocesarlo). El lote y su staging caen en
        cascada; la API no llama a esto si el lote ya pasó movimientos a Tesorería."""
        with self._con() as con, con.transaction():
            for tabla in ("comprobantes_arca", "t_ventas", "t_compras", "compras_por_item", "f931_declaraciones"):
                con.execute(f"DELETE FROM {tabla} WHERE documento_id = %s", (documento_id,))
            con.execute("DELETE FROM documentos WHERE id = %s", (documento_id,))

    def _insertar_staging(self, con: psycopg.Connection, lote: Lote) -> None:
        filas = [(lote.id, i, m.fila_origen, m.pata.value, m.fecha, m.tipo, m.importe, m.descripcion, m.referencia, m.rubro,
                  m.medio_pago, m.comprobante, m.regla_id if _es_uuid(m.regla_id) else None, m.regla_texto,
                  m.tercero, m.unidad_negocio, [a.value for a in m.alertas])
                 for i, m in enumerate(lote.resultado.movimientos)]
        with con.cursor() as cur:
            cur.executemany("""INSERT INTO movimientos_staging (lote_id, orden, fila_origen, pata, fecha, tipo, importe, descripcion,
                               referencia, rubro_codigo, medio_pago, comprobante, regla_id, regla_texto, tercero_codigo,
                               unidad_negocio_codigo, alertas)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", filas)

    def guardar_lote(self, lote: Lote) -> Lote:
        res = lote.resultado
        resumen = res.resumen()
        estado_doc = "con_alertas" if resumen["sin_regla"] or resumen["rubro_inexistente"] or resumen["duplicados"] else "procesado"
        with self._con() as con, con.transaction():
            doc = con.execute("""INSERT INTO documentos (cliente_id, nombre, extension, tipo_detectado, storage_path, sha256, tamano_bytes, estado)
                                 VALUES (%s, %s, lower(substring(%s from '\\.[^.]*$')), %s, %s, %s, %s, %s) RETURNING id""",
                              (lote.cliente_id, lote.documento, lote.documento, res.tipo_documento,
                               lote.storage_path or f"clientes/{lote.cliente_id}/{lote.sha256}", lote.sha256, lote.tamano_bytes, estado_doc)).fetchone()
            con.execute("""INSERT INTO lotes_importacion (id, documento_id, cliente_id, cuenta_id, perfil_id, perfil_autodetectado,
                               estado, filas_leidas, filas_descartadas, saldo_extracto, fecha_ultima)
                           VALUES (%s, %s, %s, (SELECT id FROM cuentas WHERE cliente_id = %s AND codigo = %s),
                               (SELECT id FROM perfiles_importacion WHERE codigo = %s ORDER BY cliente_id NULLS LAST LIMIT 1),
                               %s, %s, %s, %s, %s, %s)""",
                        (lote.id, doc["id"], lote.cliente_id, lote.cliente_id, lote.cuenta, res.perfil.codigo if res.perfil else None,
                         res.perfil_autodetectado, lote.estado, res.filas_leidas, res.filas_descartadas, res.saldo_extracto, res.fecha_ultima))
            self._insertar_staging(con, lote)
        return lote

    def actualizar_lote(self, lote: Lote) -> None:
        with self._con() as con, con.transaction():
            con.execute("UPDATE lotes_importacion SET estado = %s, aprobado_en = CASE WHEN %s = 'aprobado' THEN now() END WHERE id = %s",
                        (lote.estado, lote.estado, lote.id))
            con.execute("DELETE FROM movimientos_staging WHERE lote_id = %s", (lote.id,))
            self._insertar_staging(con, lote)
            if lote.estado == "aprobado":
                con.execute("UPDATE documentos SET estado = 'procesado' WHERE id = (SELECT documento_id FROM lotes_importacion WHERE id = %s)", (lote.id,))

    def _armar_lote(self, con: psycopg.Connection, f: dict) -> Lote:
        movs = con.execute("SELECT * FROM movimientos_staging WHERE lote_id = %s ORDER BY orden", (f["id"],)).fetchall()
        perfil = Perfil.desde_dict(f["perfil_config"]) if f["perfil_config"] else None
        res = ResultadoImportacion(
            tipo_documento=f["tipo_detectado"] or "extracto", perfil=perfil, perfil_autodetectado=f["perfil_autodetectado"],
            filas_leidas=f["filas_leidas"], filas_descartadas=f["filas_descartadas"], saldo_extracto=f["saldo_extracto"],
            fecha_ultima=f["fecha_ultima"],
            movimientos=[MovimientoPropuesto(
                fila_origen=m["fila_origen"], pata=Pata(m["pata"]), fecha=m["fecha"], cuenta=f["cuenta"], tipo=m["tipo"],
                importe=m["importe"], descripcion=m["descripcion"], referencia=m["referencia"] or "", rubro=m["rubro_codigo"],
                tercero=m["tercero_codigo"], unidad_negocio=m["unidad_negocio_codigo"], medio_pago=m["medio_pago"],
                comprobante=m["comprobante"], regla_id=str(m["regla_id"]) if m["regla_id"] else None,
                regla_texto=m["regla_texto"], alertas=[Alerta(a) for a in m["alertas"]]) for m in movs])
        return Lote(str(f["id"]), str(f["cliente_id"]), f["cuenta"], f["documento"], res, f["estado"],
                    f["sha256"], f["tamano_bytes"])

    _SELECT_LOTE = """SELECT l.*, cu.codigo AS cuenta, d.nombre AS documento, d.sha256, d.tamano_bytes, d.tipo_detectado,
                             p.config AS perfil_config
                      FROM lotes_importacion l JOIN cuentas cu ON cu.id = l.cuenta_id JOIN documentos d ON d.id = l.documento_id
                      LEFT JOIN perfiles_importacion p ON p.id = l.perfil_id"""

    def lote(self, lote_id: str) -> Lote | None:
        if not _es_uuid(lote_id):
            return None
        with self._con() as con:
            f = con.execute(self._SELECT_LOTE + " WHERE l.id = %s", (lote_id,)).fetchone()
            return self._armar_lote(con, f) if f else None

    def lotes(self, cliente_id: str, estado: str | None = None) -> list[Lote]:
        with self._con() as con:
            filas = con.execute(self._SELECT_LOTE + " WHERE l.cliente_id = %s AND (%s::estado_lote IS NULL OR l.estado = %s::estado_lote)",
                                (cliente_id, estado, estado)).fetchall()
            return [self._armar_lote(con, f) for f in filas]

    # ------------------------------------------------------------------ tesorería
    def tesoreria(self, cliente_id: str) -> list[MovimientoTesoreria]:
        with self._con() as con:
            filas = con.execute("""SELECT t.*, cu.codigo AS cuenta, te.codigo AS tercero, un.codigo AS un
                                   FROM t_tesoreria t JOIN cuentas cu ON cu.id = t.cuenta_id
                                   LEFT JOIN terceros te ON te.id = t.tercero_id
                                   LEFT JOIN unidades_negocio un ON un.id = t.unidad_negocio_id
                                   WHERE t.cliente_id = %s ORDER BY t.fecha, t.creado_en""", (cliente_id,)).fetchall()
        return [MovimientoTesoreria(cuenta=f["cuenta"], fecha=f["fecha"], tipo=f["tipo"], importe=f["importe"], rubro=f["rubro_codigo"],
                                    descripcion=f["descripcion"] or "", referencia=f["referencia"] or "", tercero=f["tercero"],
                                    comprobante=f["comprobante"], medio_pago=f["medio_pago"], unidad_negocio=f["un"],
                                    conciliado=f["conciliado"], id=str(f["id"])) for f in filas]

    def insertar_tesoreria(self, cliente_id: str, movimientos: list[MovimientoTesoreria], lote_id: str | None = None) -> None:
        with self._con() as con, con.transaction():
            for m in movimientos:
                un_id = None
                if m.unidad_negocio:
                    un_id = con.execute("""INSERT INTO unidades_negocio (cliente_id, codigo, nombre) VALUES (%s, %s, %s)
                                           ON CONFLICT (cliente_id, codigo) DO UPDATE SET codigo = EXCLUDED.codigo RETURNING id""",
                                        (cliente_id, m.unidad_negocio, m.unidad_negocio)).fetchone()["id"]
                f = con.execute("""INSERT INTO t_tesoreria (cliente_id, cuenta_id, fecha, tipo, importe, rubro_codigo, tercero_id,
                                       comprobante, medio_pago, unidad_negocio_id, conciliado, descripcion, referencia, lote_id)
                                   VALUES (%(c)s, (SELECT id FROM cuentas WHERE cliente_id = %(c)s AND codigo = %(cta)s), %(f)s, %(t)s,
                                       %(i)s, %(r)s, (SELECT id FROM terceros WHERE cliente_id = %(c)s AND codigo = %(ter)s),
                                       %(comp)s, %(medio)s, %(un)s, %(conc)s, %(d)s, %(ref)s, %(lote)s) RETURNING id""",
                                {"c": cliente_id, "cta": m.cuenta, "f": m.fecha, "t": m.tipo, "i": Decimal(m.importe), "r": m.rubro,
                                 "ter": m.tercero, "comp": m.comprobante, "medio": m.medio_pago, "un": un_id, "conc": m.conciliado,
                                 "d": m.descripcion, "ref": m.referencia or None, "lote": lote_id}).fetchone()
                m.id = str(f["id"])

    # ------------------------------------------------------------------ devengado (fase 2a)
    def guardar_comprobantes(self, cliente_id: str, documento_id: str, comps: list[ComprobanteArca]) -> tuple[int, int]:
        nuevos = 0
        with self._con() as con, con.transaction():
            for c in comps:
                f = con.execute("""
                    INSERT INTO comprobantes_arca (cliente_id, documento_id, sentido, fecha, tipo, comprobante, cuit, contraparte,
                        moneda, tipo_cambio, neto, iva, total, rubro_codigo)
                    VALUES (%(c)s, %(d)s, %(s)s, %(f)s, %(t)s, %(n)s, %(cuit)s, %(cp)s, %(m)s, %(tc)s, %(neto)s, %(iva)s, %(tot)s,
                        CASE WHEN %(s)s = 'recibido' THEN (SELECT rubro_codigo FROM rubros_por_tercero WHERE cliente_id = %(c)s AND cuit = %(cuit)s) END)
                    ON CONFLICT (cliente_id, sentido, tipo, comprobante, cuit) DO NOTHING RETURNING id""",
                    {"c": cliente_id, "d": documento_id or None, "s": c.sentido, "f": c.fecha, "t": c.tipo, "n": c.comprobante,
                     "cuit": c.doc_contraparte, "cp": c.contraparte, "m": c.moneda, "tc": c.tipo_cambio, "neto": c.neto,
                     "iva": c.iva, "tot": c.total}).fetchone()
                nuevos += 1 if f else 0
        return nuevos, len(comps) - nuevos

    def comprobantes(self, cliente_id: str, sentido: str | None = None, sin_rubro: bool = False) -> list[ComprobanteRegistrado]:
        with self._con() as con:
            filas = con.execute("""SELECT * FROM comprobantes_arca WHERE cliente_id = %s AND (%s::text IS NULL OR sentido = %s)
                                   AND (NOT %s OR rubro_codigo IS NULL) ORDER BY fecha, comprobante""",
                                (cliente_id, sentido, sentido, sin_rubro)).fetchall()
        return [ComprobanteRegistrado(str(f["id"]), f["sentido"], f["fecha"], f["comprobante"], f["cuit"], f["contraparte"],
                                      f["neto"] * f["tipo_cambio"], f["rubro_codigo"], f["total"] * f["tipo_cambio"],
                                      f["unidad_negocio"], f["centro_costo"], f["iva"] * f["tipo_cambio"]) for f in filas]

    def clasificar_comprobante(self, cliente_id: str, comprobante_id: str, unidad_negocio: str | None,
                               centro_costo: str | None, mismo_cuit: bool) -> int:
        if not _es_uuid(comprobante_id):
            return 0
        with self._con() as con, con.transaction():
            f = con.execute("SELECT sentido, cuit FROM comprobantes_arca WHERE id = %s AND cliente_id = %s",
                            (comprobante_id, cliente_id)).fetchone()
            if not f:
                return 0
            return con.execute("""UPDATE comprobantes_arca SET unidad_negocio = %s, centro_costo = %s
                                  WHERE cliente_id = %s AND (id = %s OR (%s AND sentido = %s AND cuit = %s))""",
                               (unidad_negocio, centro_costo, cliente_id, comprobante_id, mismo_cuit,
                                f["sentido"], f["cuit"])).rowcount

    def asignar_rubro(self, cliente_id: str, comprobante_id: str, rubro: str, recordar: bool) -> int:
        if not _es_uuid(comprobante_id):
            return 0
        with self._con() as con, con.transaction():
            f = con.execute("UPDATE comprobantes_arca SET rubro_codigo = %s WHERE id = %s AND cliente_id = %s RETURNING cuit",
                            (rubro, comprobante_id, cliente_id)).fetchone()
            if not f:
                return 0
            if not recordar:
                return 1
            con.execute("""INSERT INTO rubros_por_tercero (cliente_id, cuit, rubro_codigo) VALUES (%s, %s, %s)
                           ON CONFLICT (cliente_id, cuit) DO UPDATE SET rubro_codigo = EXCLUDED.rubro_codigo""",
                        (cliente_id, f["cuit"], rubro))
            otros = con.execute("""UPDATE comprobantes_arca SET rubro_codigo = %s WHERE cliente_id = %s AND cuit = %s
                                   AND sentido = 'recibido' AND rubro_codigo IS NULL""", (rubro, cliente_id, f["cuit"])).rowcount
            return 1 + otros

    def guardar_f931(self, cliente_id: str, documento_id: str, dj: DeclaracionF931) -> None:
        with self._con() as con:
            con.execute("""INSERT INTO f931_declaraciones (cliente_id, documento_id, periodo, cuit, empleados, importes)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT (cliente_id, periodo) DO UPDATE SET documento_id = EXCLUDED.documento_id,
                               empleados = EXCLUDED.empleados, importes = EXCLUDED.importes""",
                        (cliente_id, documento_id or None, dj.periodo, dj.cuit or "", dj.empleados,   # planilla sin CUIT
                         Jsonb({k: str(v) for k, v in dj.importes.items()})))

    def costos_laborales(self, cliente_id: str) -> list[CostoLaboral]:
        with self._con() as con:
            filas = con.execute("SELECT periodo, importes, empleados FROM f931_declaraciones WHERE cliente_id = %s ORDER BY periodo", (cliente_id,)).fetchall()
        salida = []
        for f in filas:
            imp = {k: Decimal(v) for k, v in f["importes"].items()}
            cargas = sum((imp.get(k, Decimal(0)) for k in ("contribuciones_ss", "contribuciones_os", "lrt", "scvo")), Decimal(0))
            salida.append(CostoLaboral(f["periodo"], imp.get("remuneracion_total", Decimal(0)), cargas, f["empleados"]))
        return salida

    def indices(self) -> list[FilaIndice]:
        with self._con() as con:
            meses = con.execute("""SELECT mes FROM indices_mensuales WHERE cliente_id IS NULL
                                   UNION SELECT mes FROM tipos_cambio ORDER BY mes""").fetchall()
            ind = {f["mes"]: f for f in con.execute("SELECT * FROM indices_mensuales WHERE cliente_id IS NULL").fetchall()}
            tcs: dict = {}
            for f in con.execute("SELECT * FROM tipos_cambio").fetchall():
                tcs.setdefault(f["mes"], {})[f["cotizacion"]] = f["valor"]
        return [FilaIndice(m["mes"], ind.get(m["mes"], {}).get("ipc"), ind.get(m["mes"], {}).get("cct"),
                           ind.get(m["mes"], {}).get("tarifa"), tcs.get(m["mes"], {})) for m in meses]

    def guardar_indice(self, fila: FilaIndice) -> None:
        with self._con() as con, con.transaction():
            if any(v is not None for v in (fila.ipc, fila.cct, fila.tarifa)):
                con.execute("""INSERT INTO indices_mensuales (cliente_id, mes, ipc, cct, tarifa) VALUES (NULL, %s, %s, %s, %s)
                               ON CONFLICT (cliente_id, mes) DO UPDATE SET ipc = COALESCE(EXCLUDED.ipc, indices_mensuales.ipc),
                                   cct = COALESCE(EXCLUDED.cct, indices_mensuales.cct), tarifa = COALESCE(EXCLUDED.tarifa, indices_mensuales.tarifa)""",
                            (fila.mes, fila.ipc, fila.cct, fila.tarifa))
            for cot, valor in fila.tc.items():
                con.execute("""INSERT INTO tipos_cambio (mes, cotizacion, valor) VALUES (%s, %s, %s)
                               ON CONFLICT (mes, cotizacion) DO UPDATE SET valor = EXCLUDED.valor""", (fila.mes, cot, valor))

    # ------------------------------------------------------------------ presupuesto (fase 2b)
    def presupuesto(self, cliente_id: str, anio: int) -> dict:
        with self._con() as con:
            filas = con.execute("""SELECT rubro_codigo, mes, importe_base FROM t_presupuesto
                                   WHERE cliente_id = %s AND etapa = 'oficial' AND extract(year FROM mes) = %s""",
                                (cliente_id, anio)).fetchall()
        return {(f["rubro_codigo"], f["mes"]): f["importe_base"] for f in filas}

    def guardar_presupuesto(self, cliente_id: str, filas: list) -> None:
        with self._con() as con, con.transaction():
            for rubro, mes, base in filas:
                if base is None:
                    con.execute("""UPDATE t_presupuesto SET importe_base = 0 WHERE cliente_id = %s AND rubro_codigo = %s
                                   AND mes = %s AND etapa = 'oficial'""", (cliente_id, rubro, mes))
                    con.execute("""DELETE FROM t_presupuesto WHERE cliente_id = %s AND rubro_codigo = %s AND mes = %s
                                   AND etapa = 'oficial' AND (nota IS NULL OR nota = '')""", (cliente_id, rubro, mes))
                else:
                    con.execute("""INSERT INTO t_presupuesto (cliente_id, rubro_codigo, mes, importe_base, etapa)
                                   VALUES (%s, %s, %s, %s, 'oficial')
                                   ON CONFLICT (cliente_id, rubro_codigo, mes, etapa) DO UPDATE SET importe_base = EXCLUDED.importe_base""",
                                (cliente_id, rubro, mes, base))

    def notas_desvio(self, cliente_id: str, anio: int) -> dict:
        with self._con() as con:
            filas = con.execute("""SELECT rubro_codigo, mes, nota FROM t_presupuesto WHERE cliente_id = %s AND etapa = 'oficial'
                                   AND extract(year FROM mes) = %s AND coalesce(nota, '') <> ''""", (cliente_id, anio)).fetchall()
        return {(f["rubro_codigo"], f["mes"]): f["nota"] for f in filas}

    def guardar_nota_desvio(self, cliente_id: str, rubro: str, mes, nota: str) -> None:
        with self._con() as con:
            con.execute("""INSERT INTO t_presupuesto (cliente_id, rubro_codigo, mes, importe_base, etapa, nota)
                           VALUES (%s, %s, %s, 0, 'oficial', %s)
                           ON CONFLICT (cliente_id, rubro_codigo, mes, etapa) DO UPDATE SET nota = EXCLUDED.nota""",
                        (cliente_id, rubro, mes, nota))

    # ------------------------------------------------------------------ ítems y mermas (fase 2c)
    def items(self, cliente_id: str) -> dict:
        with self._con() as con:
            filas = con.execute("""SELECT i.*, un.codigo AS un FROM items i LEFT JOIN unidades_negocio un ON un.id = i.unidad_negocio_id
                                   WHERE i.cliente_id = %s ORDER BY i.codigo""", (cliente_id,)).fetchall()
        return {f["codigo"]: Item(f["codigo"], f["descripcion"], f["tipo"], f["un"] or "GENERAL", f["precio_lista"] or Decimal(0),
                                  f["cotizacion_precio"], f["costo_estandar"], f["cotizacion_costo"], f["alicuota_iva"]) for f in filas}

    def guardar_item(self, cliente_id: str, item: Item) -> Item:
        with self._con() as con, con.transaction():
            un = con.execute("""INSERT INTO unidades_negocio (cliente_id, codigo, nombre) VALUES (%s, %s, %s)
                                ON CONFLICT (cliente_id, codigo) DO UPDATE SET codigo = EXCLUDED.codigo RETURNING id""",
                             (cliente_id, item.unidad_negocio, item.unidad_negocio)).fetchone()["id"]
            con.execute("""INSERT INTO items (cliente_id, codigo, descripcion, tipo, unidad_negocio_id, precio_lista, cotizacion_precio,
                               costo_estandar, cotizacion_costo, alicuota_iva)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (cliente_id, codigo) DO UPDATE SET descripcion = EXCLUDED.descripcion, tipo = EXCLUDED.tipo,
                               unidad_negocio_id = EXCLUDED.unidad_negocio_id, precio_lista = EXCLUDED.precio_lista,
                               cotizacion_precio = EXCLUDED.cotizacion_precio, costo_estandar = EXCLUDED.costo_estandar,
                               cotizacion_costo = EXCLUDED.cotizacion_costo, alicuota_iva = EXCLUDED.alicuota_iva""",
                        (cliente_id, item.codigo, item.descripcion, item.tipo, un, item.precio_lista, item.cotizacion_precio,
                         item.costo_estandar, item.cotizacion_costo, item.alicuota_iva))
            # ventas cargadas antes de dar de alta el ítem quedan vinculadas
            con.execute("""UPDATE t_ventas SET item_id = (SELECT id FROM items WHERE cliente_id = %s AND codigo = %s)
                           WHERE cliente_id = %s AND item_codigo = %s AND item_id IS NULL""", (cliente_id, item.codigo, cliente_id, item.codigo))
        return item

    def guardar_lineas_venta(self, cliente_id: str, documento_id: str, lineas: list) -> tuple[int, int]:
        nuevas = 0
        with self._con() as con, con.transaction():
            for l in lineas:
                f = con.execute("""INSERT INTO t_ventas (cliente_id, fecha, comprobante, item_codigo, item_id, cantidad, precio_unitario, documento_id)
                                   VALUES (%(c)s, %(f)s, %(comp)s, %(it)s, (SELECT id FROM items WHERE cliente_id = %(c)s AND codigo = %(it)s),
                                       %(q)s, %(p)s, %(d)s)
                                   ON CONFLICT (cliente_id, fecha, comprobante, item_codigo, cantidad, precio_unitario) DO NOTHING RETURNING id""",
                                {"c": cliente_id, "f": l.fecha, "comp": l.comprobante, "it": l.item, "q": l.cantidad, "p": l.precio_unitario,
                                 "d": documento_id or None}).fetchone()
                nuevas += 1 if f else 0
        return nuevas, len(lineas) - nuevas

    def lineas_venta(self, cliente_id: str) -> list:
        with self._con() as con:
            filas = con.execute("SELECT * FROM t_ventas WHERE cliente_id = %s ORDER BY fecha, comprobante", (cliente_id,)).fetchall()
        return [LineaVenta(f["fecha"], f["comprobante"], f["item_codigo"], f["cantidad"], f["precio_unitario"] or Decimal(0), str(f["id"]))
                for f in filas]

    def guardar_lineas_compra(self, cliente_id: str, documento_id: str, lineas: list) -> tuple[int, int]:
        nuevas = 0
        with self._con() as con, con.transaction():
            for l in lineas:
                f = con.execute("""INSERT INTO compras_por_item (cliente_id, fecha, comprobante, proveedor, item_codigo, cantidad,
                                       costo_unitario, documento_id)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT (cliente_id, fecha, comprobante, proveedor, item_codigo, cantidad, costo_unitario)
                                   DO NOTHING RETURNING id""",
                                (cliente_id, l.fecha, l.comprobante, l.proveedor, l.item, l.cantidad, l.costo_unitario,
                                 documento_id or None)).fetchone()
                nuevas += 1 if f else 0
        return nuevas, len(lineas) - nuevas

    def lineas_compra(self, cliente_id: str) -> list:
        with self._con() as con:
            filas = con.execute("SELECT * FROM compras_por_item WHERE cliente_id = %s ORDER BY fecha, comprobante",
                                (cliente_id,)).fetchall()
        return [LineaCompra(f["fecha"], f["comprobante"], f["proveedor"], f["item_codigo"], f["cantidad"], f["costo_unitario"],
                            str(f["id"])) for f in filas]

    def registrar_merma(self, cliente_id: str, merma) -> object:
        with self._con() as con:
            f = con.execute("""INSERT INTO t_mermas (cliente_id, fecha, item_id, cantidad, causa, turno)
                               VALUES (%s, %s, (SELECT id FROM items WHERE cliente_id = %s AND codigo = %s), %s, %s, %s) RETURNING id""",
                            (cliente_id, merma.fecha, cliente_id, merma.item, merma.cantidad, merma.causa, merma.turno)).fetchone()
        merma.id = str(f["id"])
        return merma

    def mermas(self, cliente_id: str) -> list:
        with self._con() as con:
            filas = con.execute("""SELECT m.*, i.codigo AS item FROM t_mermas m JOIN items i ON i.id = m.item_id
                                   WHERE m.cliente_id = %s ORDER BY m.fecha""", (cliente_id,)).fetchall()
        return [Merma(f["fecha"], f["item"], f["cantidad"], f["causa"], f["turno"] or "", str(f["id"])) for f in filas]

    # ------------------------------------------------------------------ tablero (fase 3)
    def cierres(self, cliente_id: str) -> dict:
        with self._con() as con:
            filas = con.execute("SELECT * FROM t_balance_cierres WHERE cliente_id = %s", (cliente_id,)).fetchall()
        return {f["mes"]: DatosCierre(f["mes"], f["stock"], f["bienes_uso"], f["otros_activos"], f["deudas_financieras"],
                                      f["deudas_fiscales"], f["otros_pasivos"], f["amortizacion_mes"]) for f in filas}

    def guardar_cierre(self, cliente_id: str, c) -> None:
        with self._con() as con:
            con.execute("""INSERT INTO t_balance_cierres (cliente_id, mes, stock, bienes_uso, otros_activos, deudas_financieras,
                               deudas_fiscales, otros_pasivos, amortizacion_mes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (cliente_id, mes) DO UPDATE SET stock = EXCLUDED.stock, bienes_uso = EXCLUDED.bienes_uso,
                               otros_activos = EXCLUDED.otros_activos, deudas_financieras = EXCLUDED.deudas_financieras,
                               deudas_fiscales = EXCLUDED.deudas_fiscales, otros_pasivos = EXCLUDED.otros_pasivos,
                               amortizacion_mes = EXCLUDED.amortizacion_mes""",
                        (cliente_id, c.mes, c.stock, c.bienes_uso, c.otros_activos, c.deudas_financieras, c.deudas_fiscales,
                         c.otros_pasivos, c.amortizacion_mes))

    def metas(self, cliente_id: str) -> dict:
        with self._con() as con:
            filas = con.execute("SELECT kpi, meta, direccion FROM metas_tablero WHERE cliente_id = %s", (cliente_id,)).fetchall()
        return {f["kpi"]: (f["meta"], f["direccion"]) for f in filas}

    def guardar_meta(self, cliente_id: str, kpi: str, meta, direccion: str) -> None:
        with self._con() as con:
            con.execute("""INSERT INTO metas_tablero (cliente_id, kpi, meta, direccion) VALUES (%s, %s, %s, %s)
                           ON CONFLICT (cliente_id, kpi) DO UPDATE SET meta = EXCLUDED.meta, direccion = EXCLUDED.direccion""",
                        (cliente_id, kpi, meta, direccion))

    # ------------------------------------------------------------ plan de cuentas
    def plan_cuentas(self, cliente_id: str) -> dict:
        with self._con() as con:
            filas = con.execute("""SELECT codigo, nombre, imputable, ajustable, expuesta, clase, padre, comentario
                                   FROM plan_cuentas WHERE cliente_id = %s""", (cliente_id,)).fetchall()
        return {f["codigo"]: CuentaContable(**f) for f in filas}

    def iniciar_plan(self, cliente_id: str, cuentas: list) -> None:
        # las agrupadoras antes que sus subcuentas (la clave foránea a padre lo exige)
        por_codigo = {c.codigo: c for c in cuentas}
        def nivel(c, n=0):
            return n if not c.padre or c.padre not in por_codigo else nivel(por_codigo[c.padre], n + 1)
        with self._con() as con, con.transaction(), con.cursor() as cur:
            cur.executemany("""INSERT INTO plan_cuentas (cliente_id, codigo, nombre, imputable, ajustable, expuesta, clase, padre, comentario)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                            [(cliente_id, c.codigo, c.nombre, c.imputable, c.ajustable, c.expuesta, c.clase, c.padre, c.comentario)
                             for c in sorted(cuentas, key=nivel)])

    def guardar_cuenta_contable(self, cliente_id: str, c) -> None:
        with self._con() as con:
            con.execute("""INSERT INTO plan_cuentas (cliente_id, codigo, nombre, imputable, ajustable, expuesta, clase, padre, comentario)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (cliente_id, codigo) DO UPDATE SET nombre = EXCLUDED.nombre, imputable = EXCLUDED.imputable,
                               ajustable = EXCLUDED.ajustable, expuesta = EXCLUDED.expuesta, comentario = EXCLUDED.comentario""",
                        (cliente_id, c.codigo, c.nombre, c.imputable, c.ajustable, c.expuesta, c.clase, c.padre, c.comentario))

    def borrar_cuenta_contable(self, cliente_id: str, codigo: str) -> None:
        with self._con() as con:
            con.execute("DELETE FROM plan_cuentas WHERE cliente_id = %s AND codigo = %s", (cliente_id, codigo))

    def rubro_cuenta(self, cliente_id: str) -> dict[str, str]:
        with self._con() as con:
            filas = con.execute("SELECT rubro, cuenta FROM rubro_cuenta WHERE cliente_id = %s", (cliente_id,)).fetchall()
        return {f["rubro"]: f["cuenta"] for f in filas}

    def vincular_rubro(self, cliente_id: str, rubro: str, cuenta: str | None) -> None:
        with self._con() as con:
            if cuenta is None:
                con.execute("DELETE FROM rubro_cuenta WHERE cliente_id = %s AND rubro = %s", (cliente_id, rubro))
            else:
                con.execute("""INSERT INTO rubro_cuenta (cliente_id, rubro, cuenta) VALUES (%s, %s, %s)
                               ON CONFLICT (cliente_id, rubro) DO UPDATE SET cuenta = EXCLUDED.cuenta""", (cliente_id, rubro, cuenta))

    # ------------------------------------------------------------ cola de trabajos (fase 4a)
    @staticmethod
    def _trabajo(f) -> Trabajo:
        return Trabajo(str(f["id"]), str(f["cliente_id"]), f["tipo"], f["parametros"], f["estado"], f["intentos"],
                       f["resultado"], f["error"], f["creado"], f["actualizado"])

    def encolar(self, cliente_id: str, tipo: str, parametros: dict) -> Trabajo:
        with self._con() as con:
            f = con.execute("INSERT INTO trabajos (id, cliente_id, tipo, parametros) VALUES (%s, %s, %s, %s) RETURNING *",
                            (str(uuid.uuid4()), cliente_id, tipo, Jsonb(parametros))).fetchone()
        return self._trabajo(f)

    def tomar_trabajo(self, worker: str) -> Trabajo | None:
        # también rescata trabajos "procesando" de un worker que murió hace más de 15 minutos
        with self._con() as con:
            f = con.execute("""
                UPDATE trabajos SET estado = 'procesando', intentos = intentos + 1, tomado_por = %s, actualizado = now()
                WHERE id = (SELECT id FROM trabajos
                            WHERE estado = 'pendiente' OR (estado = 'procesando' AND actualizado < now() - interval '15 minutes')
                            ORDER BY creado LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING *""", (worker,)).fetchone()
        return self._trabajo(f) if f else None

    def terminar_trabajo(self, trabajo_id: str, resultado: dict | None, error: str | None, reintentar: bool = False) -> None:
        with self._con() as con:
            con.execute("""
                UPDATE trabajos SET resultado = %s, error = %s, actualizado = now(),
                       estado = CASE WHEN %s::text IS NULL THEN 'hecho' WHEN %s::boolean AND intentos < %s THEN 'pendiente' ELSE 'error' END
                WHERE id = %s""",
                        (Jsonb(resultado) if resultado is not None else None, error, error, reintentar, MAX_INTENTOS, trabajo_id))

    def trabajo(self, trabajo_id: str) -> Trabajo | None:
        with self._con() as con:
            f = con.execute("SELECT * FROM trabajos WHERE id = %s", (trabajo_id,)).fetchone()
        return self._trabajo(f) if f else None

    def estado_cola(self) -> dict[str, int]:
        with self._con() as con:
            filas = con.execute("SELECT estado, count(*) AS n FROM trabajos GROUP BY estado").fetchall()
        return {"pendiente": 0, "procesando": 0, "hecho": 0, "error": 0} | {f["estado"]: f["n"] for f in filas}
