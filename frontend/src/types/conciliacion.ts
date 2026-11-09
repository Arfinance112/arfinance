// Tipos que espejan las respuestas de la API (backend/app/api/main.py).

export type Alerta =
  | "SIN_REGLA"
  | "RUBRO_INEXISTENTE"
  | "DUPLICADO_EXACTO"
  | "POSIBLE_DUPLICADO"
  | "SIN_COMPROBANTE";

export type TipoMovimiento = "Ingreso" | "Egreso";

export interface MovimientoPropuesto {
  id: number;
  fila_origen: number;
  pata: "principal" | "comision" | "impuestos";
  fecha: string; // ISO yyyy-mm-dd
  cuenta: string;
  tipo: TipoMovimiento;
  importe: number;
  descripcion: string;
  referencia: string;
  rubro: string | null;
  tercero: string | null;
  unidad_negocio: string | null;
  medio_pago: string | null;
  comprobante: string | null;
  regla: string | null;
  alertas: Alerta[];
  bloqueado: boolean;
}

export interface ResumenLote {
  movimientos: number;
  sin_regla: number;
  rubro_inexistente: number;
  duplicados: number;
  sin_comprobante: number;
  listos: number;
}

export interface Conciliacion {
  fecha?: string;
  saldo_extracto?: number | null;
  fecha_inicial?: string;
  saldo_inicial_extracto?: number | null;
  saldo_inicial_sistema?: number;
  diferencia_inicial?: number | null;
  saldo_planilla_actual?: number;
  saldo_planilla_despues_de_aprobar?: number;
  diferencia?: number | null;
}

export interface Lote {
  id: string;
  cliente_id: string;
  cuenta: string;
  documento: string;
  estado: "pendiente" | "aprobado" | "descartado";
  perfil: string | null;
  perfil_autodetectado: boolean;
  filas_leidas: number;
  filas_descartadas: number;
  resumen: ResumenLote;
  conciliacion: Conciliacion;
  movimientos: MovimientoPropuesto[];
}

export interface Rubro {
  codigo: string;
  nombre: string;
  linea_pl: string;
  linea_cf: string;
}

export interface ReglaNueva {
  texto: string;
  rubro: string;
  tipo?: TipoMovimiento | null;
  cuenta?: string | null;
  comentario?: string | null;
}

export interface Correccion {
  rubro?: string | null;
  tercero?: string | null;
  comprobante?: string | null;
  unidad_negocio?: string | null;
}

export interface ResultadoAprobacion {
  insertados: number;
  omitidos: number;
  conciliacion: Conciliacion;
}
