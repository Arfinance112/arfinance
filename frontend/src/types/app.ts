// Tipos de las pantallas de clientes, documentos y tesorería (espejo de backend/app/api/main.py).

export interface Yo {
  id: string;
  email: string;
  organizacion_id: string | null;
}

export interface ClienteResumen {
  id: string;
  nombre: string;
  cuit: string;
  cuentas: number;
  movimientos_tesoreria: number;
  lotes_pendientes: number;
}

export interface Cuenta {
  codigo: string;
  nombre: string;
  tipo: string;
  cotizacion: string;
  saldo_inicial: number;
  fecha_saldo_inicial: string | null;
  perfil_defecto: string | null;
}

export type EstadoDocumento = "pendiente" | "procesado" | "con_alertas" | "aprobado" | "error";

export interface Documento {
  id: string;
  nombre: string;
  tipo: "extracto" | "f931" | "mis_comprobantes" | string;
  estado: EstadoDocumento;
  tamano_bytes: number;
  lote_id: string | null;
  detalle: string;
  subido_en: string;
}

export interface Saldo {
  cuenta: string;
  nombre: string;
  tipo: string;
  cotizacion: string;
  saldo: number;
}

export interface MovimientoTesoreria {
  id: string;
  cuenta: string;
  fecha: string;
  tipo: "Ingreso" | "Egreso";
  importe: number;
  rubro: string;
  descripcion: string;
  referencia: string;
  tercero: string | null;
  comprobante: string | null;
  medio_pago: string | null;
  unidad_negocio: string | null;
  conciliado: boolean;
}

export interface FlujoMoneda {
  meses: string[];
  lineas: { linea: string; grupo: string; valores: Record<string, number>; total: number }[];
  totales: Record<string, Record<string, number>>;
}

export type Flujo = Record<string, FlujoMoneda>;

export interface Comprobante {
  id: string;
  sentido: "emitido" | "recibido";
  fecha: string;
  comprobante: string;
  cuit: string;
  contraparte: string;
  neto_ars: number;
  rubro: string | null;
}

export interface Resultados {
  meses: string[];
  filas: Record<string, Record<string, number | null>>;
  /** línea → rubro → mes ISO (o "total") → importe */
  detalle_por_linea: Record<string, Record<string, Record<string, number>>>;
  avisos: string[];
}

export interface FilaIndice {
  mes: string;
  ipc: number | null;
  cct: number | null;
  tarifa: number | null;
  tc: Record<string, number>;
}

export interface FilaPresupuesto {
  rubro: string;
  nombre: string;
  linea_pl: string;
  indice: string;
  base: Record<string, number>;
  nominal: Record<string, number>;
  total_base: number;
  total_nominal: number;
}

export interface Presupuesto {
  anio: number;
  meses: string[];
  filas: FilaPresupuesto[];
  avisos: string[];
}

export type Semaforo = "verde" | "amarillo" | "rojo" | "azul" | "sin_ppto" | "sin_datos";

export interface FilaControl {
  rubro: string;
  nombre: string;
  linea_pl: string;
  signo: number;
  tolerancia: number;
  ppto_mes: number;
  real_mes: number;
  desvio_mes: number;
  desvio_pct_mes: number | null;
  semaforo_mes: Semaforo;
  ppto_acum: number;
  real_acum: number;
  desvio_acum: number;
  desvio_pct_acum: number | null;
  semaforo_acum: Semaforo;
  nota: string;
}

export interface Control {
  mes: string;
  resumen: Partial<Record<Semaforo, number>>;
  avisos: string[];
  filas: FilaControl[];
}

export interface Item {
  codigo: string;
  descripcion: string;
  tipo: "Bien" | "Servicio";
  unidad_negocio: string;
  precio_lista: number;
  cotizacion_precio: string;
  costo_estandar: number;
  cotizacion_costo: string;
  alicuota_iva: number;
}

export interface Merma {
  id: string;
  fecha: string;
  item: string;
  cantidad: number;
  causa: string;
  turno: string;
}

export interface FilaRentabilidad {
  clave: string;
  nombre: string;
  unidad_negocio: string;
  cantidad: number;
  ventas: number;
  cmv: number;
  mermas: number;
  margen: number;
  margen_pct: number | null;
  margen_unitario: number | null;
}

export interface Rentabilidad {
  items: FilaRentabilidad[];
  unidades: FilaRentabilidad[];
  ventas: number;
  margen: number;
  margen_pct: number | null;
  costos_fijos: number;
  punto_equilibrio: number | null;
  margen_seguridad: number | null;
  avisos: string[];
}

export interface Perfil {
  codigo: string;
  nombre: string;
  tipo_origen: string;
}

// ---------------------------------------------------------------- tablero ejecutivo (fase 3)
export type FormatoKpi = "ars" | "pct" | "dias" | "x" | "num";
export interface Kpi {
  clave: string;
  nombre: string;
  seccion: string;
  formato: FormatoKpi;
  valor: number | null;
  anterior: number | null;
  presupuesto: number | null;
  meta: number | null;
  direccion: "≥" | "≤";
  semaforo: "verde" | "amarillo" | "rojo" | null;
  variacion: number | null;
}
export interface TramoProyeccion { desde: string; hasta: string; flujo: number; saldo: number }
export interface Tablero {
  mes: string;
  secciones: { titulo: string; kpis: Kpi[] }[];
  serie: { meses: string[]; ingresos_netos: (number | null)[]; margen_contribucion: (number | null)[]; ebitda: (number | null)[] };
  proyeccion: { tramos: TramoProyeccion[]; cobranzas_vencidas: number; necesidad_financiamiento: number };
  avisos: string[];
}
export interface Cierre {
  mes: string;
  stock: string;
  bienes_uso: string;
  otros_activos: string;
  deudas_financieras: string;
  deudas_fiscales: string;
  otros_pasivos: string;
  amortizacion_mes: string;
}

// ---------------------------------------------------------------- alta desde la planilla v2 (fase 4b)
export interface ImportacionPlanilla {
  simulacion: boolean;
  empresa: string;
  cuit: string;
  cuentas: number;
  items: number;
  reglas: number;
  tesoreria: number;
  ventas: number;
  renglones_venta: number;
  compras: number;
  meses_personal: number;
  mermas: number;
  celdas_presupuesto: number;
  cierres: number;
  metas: number;
  meses_indices: number;
  ejemplos_omitidos: number;
  avisos: string[];
}
