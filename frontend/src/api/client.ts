import { tokenActual } from "../auth/sesion";
import type {
  ClienteResumen,
  Comprobante,
  Control,
  Cuenta,
  Presupuesto,
  Documento,
  FilaIndice,
  Flujo,
  Item,
  Merma,
  Rentabilidad,
  MovimientoTesoreria,
  Perfil,
  Resultados,
  Saldo,
  Tablero,
  Cierre,
  ImportacionPlanilla,
  CuentaContable,
  PlanCuentas,
  MiembroOrg,
  Rol,
  Yo,
} from "../types/app";
import type {
  Correccion,
  Lote,
  MovimientoPropuesto,
  ReglaNueva,
  ResultadoAprobacion,
  Rubro,
} from "../types/conciliacion";

/** Lo que el sistema leyó de un documento, para revisarlo en pantalla. */
export interface VistaDocumento {
  id: string; nombre: string; tipo: string; estado: string; detalle: string; extension: string;
  hojas: string[]; filas: string[][]; total_filas: number; texto: string;
}

/** Respuesta de la subida; "en_cola" = archivo grande que procesa el worker (consultar /trabajos/{id}). */
export interface ResultadoSubida { tipo: string; estado: string; lote_id?: string; trabajo_id?: string; motivo?: "ocr" | "tamano"; aviso_ocr?: string;
  nuevos?: number; repetidos?: number }

const BASE =import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, public detalle: unknown) {
    super(typeof detalle === "string" ? detalle : `Error ${status}`);
  }
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  const token = await tokenActual();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // FormData arma su propio Content-Type con el boundary
  if (init?.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const r = await fetch(`${BASE}${ruta}`, { ...init, headers });
  const cuerpo = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(r.status, (cuerpo as { detail?: unknown })?.detail ?? cuerpo);
  return cuerpo as T;
}

/** Descarga un archivo autenticado (no se puede usar un <a href> porque el token va en el header). */
async function descargar(ruta: string, nombre: string): Promise<void> {
  const token = await tokenActual();
  const r = await fetch(`${BASE}${ruta}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: nombre });
  a.click();
  URL.revokeObjectURL(url);
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  // sesión
  yo: () => pedir<Yo>("/me"),
  crearOrganizacion: (nombre: string) => pedir<{ organizacion_id: string }>("/me/organizacion", json({ nombre })),
  // clientes y cuentas
  clientes: () => pedir<ClienteResumen[]>("/clientes"),
  crearCliente: (nombre: string, cuit: string) => pedir<{ id: string }>("/clientes", json({ nombre, cuit })),
  importarPlanilla: (archivo: File, o: { simular: boolean; omitirEjemplos: boolean; importarIndices: boolean }) => {
    const datos = new FormData();
    datos.append("archivo", archivo);
    datos.append("simular", String(o.simular));
    datos.append("omitir_ejemplos", String(o.omitirEjemplos));
    datos.append("importar_indices", String(o.importarIndices));
    return pedir<ImportacionPlanilla & { cliente_id?: string }>("/clientes/importar-planilla", { method: "POST", body: datos });
  },
  cliente: (id: string) => pedir<{ id: string; nombre: string; cuit: string }>(`/clientes/${id}`),
  cuentas: (id: string) => pedir<Cuenta[]>(`/clientes/${id}/cuentas`),
  crearCuenta: (id: string, c: Partial<Cuenta>) => pedir<Cuenta>(`/clientes/${id}/cuentas`, json(c)),
  perfiles: () => pedir<Perfil[]>("/perfiles"),
  // documentos
  documentos: (id: string) => pedir<Documento[]>(`/clientes/${id}/documentos`),
  subirDocumento: (id: string, archivo: File, cuenta?: string) => {
    const datos = new FormData();
    datos.append("archivo", archivo);
    if (cuenta) datos.append("cuenta", cuenta);
    return pedir<ResultadoSubida>(`/clientes/${id}/documentos`, { method: "POST", body: datos });
  },
  miembros: () => pedir<{ roles: Rol[]; miembros: MiembroOrg[] }>("/organizacion/miembros"),
  invitarMiembro: (email: string, rol: Rol) =>
    pedir<{ email: string; mail_enviado: boolean }>("/organizacion/miembros", json({ email, rol })),
  cambiarRol: (usuarioId: string, rol: Rol) =>
    pedir<{ rol: Rol }>(`/organizacion/miembros/${usuarioId}`, { method: "PATCH", body: JSON.stringify({ rol }) }),
  quitarMiembro: (usuarioId: string) => pedir<string>(`/organizacion/miembros/${usuarioId}`, { method: "DELETE" }),
  planCuentas: (id: string) => pedir<PlanCuentas>(`/clientes/${id}/plan-cuentas`),
  altaCuentaContable: (id: string, c: { codigo: string; nombre: string; imputable: boolean; padre: string | null; ajustable?: boolean; expuesta?: boolean }) =>
    pedir<CuentaContable>(`/clientes/${id}/plan-cuentas`, json(c)),
  editarCuentaContable: (id: string, codigo: string, cambio: Partial<Pick<CuentaContable, "nombre" | "imputable" | "ajustable" | "expuesta" | "comentario">>) =>
    pedir<CuentaContable>(`/clientes/${id}/plan-cuentas/${codigo}`, { method: "PATCH", body: JSON.stringify(cambio) }),
  bajaCuentaContable: (id: string, codigo: string) => pedir<string>(`/clientes/${id}/plan-cuentas/${codigo}`, { method: "DELETE" }),
  vincularRubros: (id: string, codigo: string, rubros: string[]) =>
    pedir<{ rubros: string[] }>(`/clientes/${id}/plan-cuentas/${codigo}/rubros`, { method: "PUT", body: JSON.stringify({ rubros }) }),
  vistaDocumento: (id: string) => pedir<VistaDocumento>(`/documentos/${id}/vista`),
  eliminarDocumento: (id: string) => pedir<string>(`/documentos/${id}`, { method: "DELETE" }),
  /** Abre el original en una pestaña nueva (va con el token de sesión, por eso no alcanza un enlace común). */
  abrirDocumento: async (id: string) => {
    const pestana = window.open("", "_blank");   // se abre ya, antes del await: si no, el navegador la bloquea
    const token = await tokenActual();
    const r = await fetch(`${BASE}/documentos/${id}/archivo`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!r.ok) { pestana?.close(); throw new ApiError(r.status, await r.text()); }
    const url = URL.createObjectURL(await r.blob());
    if (pestana) pestana.location.href = url; else window.location.href = url;
  },
  reprocesarDocumento: (id: string) => pedir<ResultadoSubida>(`/documentos/${id}/reprocesar`, { method: "POST" }),
  trabajo: (id: string) =>
    pedir<{ estado: "pendiente" | "procesando" | "hecho" | "error"; resultado: ResultadoSubida | null; error: string | null }>(`/trabajos/${id}`),
  // tesorería
  saldos: (id: string) => pedir<Saldo[]>(`/clientes/${id}/saldos`),
  tesoreria: (id: string) => pedir<MovimientoTesoreria[]>(`/clientes/${id}/tesoreria`),
  flujo: (id: string) => pedir<Flujo>(`/clientes/${id}/flujo`),
  // devengado
  comprobantes: (id: string, sentido?: string, sinRubro = false) =>
    pedir<Comprobante[]>(`/clientes/${id}/comprobantes?${new URLSearchParams({ ...(sentido ? { sentido } : {}), sin_rubro: String(sinRubro) })}`),
  asignarRubro: (id: string, comprobanteId: string, rubro: string, recordar = true) =>
    pedir<{ actualizados: number }>(`/clientes/${id}/comprobantes/${comprobanteId}`, { method: "PATCH", body: JSON.stringify({ rubro, recordar }) }),
  clasificarComprobante: (id: string, comprobanteId: string, cambios: { unidad_negocio?: string; centro_costo?: string }, mismoCuit: boolean) =>
    pedir<{ actualizados: number }>(`/clientes/${id}/comprobantes/${comprobanteId}`, { method: "PATCH", body: JSON.stringify({ ...cambios, recordar: mismoCuit }) }),
  resultados: (id: string, rubroVentas = "ING01", unidad = "", centro = "") =>
    pedir<Resultados>(`/clientes/${id}/resultados?${new URLSearchParams({ rubro_ventas: rubroVentas,
      ...(unidad ? { unidad_negocio: unidad } : {}), ...(centro ? { centro_costo: centro } : {}) })}`),
  indices: () => pedir<FilaIndice[]>("/indices"),
  guardarIndice: (mes: string, datos: { ipc?: number | null; cct?: number | null; tarifa?: number | null; tc: Record<string, number> }) =>
    pedir<{ mes: string }>(`/indices/${mes}`, { method: "PUT", body: JSON.stringify(datos) }),
  // presupuesto y control
  presupuesto: (id: string, anio: number) => pedir<Presupuesto>(`/clientes/${id}/presupuesto?anio=${anio}`),
  guardarPresupuesto: (id: string, filas: { rubro: string; mes: string; base: number | null }[]) =>
    pedir<{ guardadas: number }>(`/clientes/${id}/presupuesto`, { method: "PUT", body: JSON.stringify({ filas }) }),
  generarPresupuesto: (id: string, datos: { anio: number; meses_historicos: string[]; ajuste_volumen: number; objetivos: Record<string, number> }) =>
    pedir<{ rubros: number; base_mensual: Record<string, number> }>(`/clientes/${id}/presupuesto/generar`, json(datos)),
  control: (id: string, mes: string) => pedir<Control>(`/clientes/${id}/control?mes=${mes}`),
  guardarNota: (id: string, rubro: string, mes: string, nota: string) =>
    pedir<{ ok: boolean }>(`/clientes/${id}/control/nota`, { method: "PUT", body: JSON.stringify({ rubro, mes, nota }) }),
  // ítems, mermas y rentabilidad
  items: (id: string) => pedir<{ items: Item[]; vendidos_sin_alta: string[] }>(`/clientes/${id}/items`),
  guardarItem: (id: string, item: Item) => {
    const { codigo, ...resto } = item;
    return pedir<Item>(`/clientes/${id}/items/${encodeURIComponent(codigo)}`, { method: "PUT", body: JSON.stringify(resto) });
  },
  mermas: (id: string) => pedir<{ causas: string[]; mermas: Merma[]; por_causa: Record<string, number> }>(`/clientes/${id}/mermas`),
  registrarMerma: (id: string, m: Omit<Merma, "id">) => pedir<Merma>(`/clientes/${id}/mermas`, json(m)),
  rentabilidad: (id: string, desde: string, hasta: string) =>
    pedir<Rentabilidad>(`/clientes/${id}/rentabilidad?desde=${desde}&hasta=${hasta}`),
  // tablero ejecutivo
  tablero: (id: string, mes: string) => pedir<Tablero>(`/clientes/${id}/tablero?mes=${mes}`),
  tableroExcel: (id: string, mes: string) => descargar(`/clientes/${id}/tablero.xlsx?mes=${mes}`, `tablero_${mes.slice(0, 7)}.xlsx`),
  cierres: (id: string) => pedir<Cierre[]>(`/clientes/${id}/cierres`),
  guardarCierre: (id: string, c: Cierre) => {
    const { mes, ...resto } = c;
    return pedir<{ mes: string }>(`/clientes/${id}/cierres/${mes}`, { method: "PUT", body: JSON.stringify(resto) });
  },
  guardarMeta: (id: string, kpi: string, meta: string | null, direccion: string) =>
    pedir<{ kpi: string }>(`/clientes/${id}/metas/${kpi}`, { method: "PUT", body: JSON.stringify({ meta, direccion }) }),
  // conciliación
  lote: (id: string) => pedir<Lote>(`/lotes/${id}`),
  rubros: () => pedir<Rubro[]>("/rubros"),
  corregir: (loteId: string, movId: number, c: Correccion) =>
    pedir<MovimientoPropuesto>(`/lotes/${loteId}/movimientos/${movId}`, { method: "PATCH", body: JSON.stringify(c) }),
  crearRegla: (clienteId: string, r: ReglaNueva) =>
    pedir<{ movimientos_reclasificados: number }>(`/clientes/${clienteId}/reglas`, json(r)),
  aprobar: (loteId: string) => pedir<ResultadoAprobacion>(`/lotes/${loteId}/aprobar`, json({})),
};

export const mensajeDeError = (e: unknown): string =>
  e instanceof ApiError
    ? typeof e.detalle === "string"
      ? e.detalle
      : JSON.stringify(e.detalle)
    : "No se pudo conectar con el servidor.";
