import { useCallback, useEffect, useRef, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { fecha, tamano } from "../formato";
import type { Cuenta, Documento } from "../types/app";
import { ImportadorGenerico } from "./ImportadorGenerico";
import { VistaDocumento } from "./VistaDocumento";

const ESTADO: Record<string, { texto: string; clase: string }> = {
  pendiente: { texto: "Pendiente", clase: "estado-pendiente" },
  procesado: { texto: "Listo para aprobar", clase: "estado-procesado" },
  con_alertas: { texto: "Con alertas", clase: "estado-alerta" },
  aprobado: { texto: "Aprobado", clase: "estado-aprobado" },
  error: { texto: "Error", clase: "estado-error" },
};
const TIPO: Record<string, string> = {
  extracto: "Extracto", f931: "F.931", mis_comprobantes: "Mis Comprobantes", detalle_ventas: "Detalle de ventas", detalle_compras: "Detalle de compras",
  planilla_v2: "Planilla v2",
};
/** Solo los extractos se aprueban (pasan a Tesorería); el resto queda cargado al subirlo. */
const estadoDe = (estado: string, tipo: string) =>
  estado === "procesado" && tipo !== "extracto" ? { texto: "Cargado", clase: "estado-aprobado" } : ESTADO[estado];
/** Un extracto que ya pasó movimientos a Tesorería no se relee (los duplicaría); la planilla se importa una vez. */
const puedeReprocesar = (d: Documento) =>
  d.tipo !== "planilla_v2" && !(d.estado === "aprobado" && !/^0 /.test(d.detalle ?? ""));
/** Mismo criterio que el servidor: un extracto con movimientos ya en Tesorería no se elimina. */
const puedeEliminar = (d: Documento) => !(d.estado === "aprobado" && !/^0 /.test(d.detalle ?? ""));
const ACEPTADOS = ".xlsx,.xlsm,.csv,.txt,.pdf";

interface Subida {
  nombre: string;
  estado: "subiendo" | "ok" | "aviso" | "error";
  mensaje?: string;
}

/** Carga drag-and-drop + estado de cada archivo subido. */
export function Documentos({ clienteId }: { clienteId: string }) {
  const [docs, setDocs] = useState<Documento[]>([]);
  const [cuentas, setCuentas] = useState<Cuenta[]>([]);
  const [cuenta, setCuenta] = useState("");
  const [arrastrando, setArrastrando] = useState(false);
  const [subidas, setSubidas] = useState<Subida[]>([]);
  const entrada = useRef<HTMLInputElement>(null);

  const cargar = () => api.documentos(clienteId).then(setDocs);
  const [reprocesando, setReprocesando] = useState<string | null>(null);
  const [viendo, setViendo] = useState<Documento | null>(null);
  const cerrarVista = useCallback(() => setViendo(null), []);

  async function eliminar(d: Documento) {
    const queSeBorra = d.tipo === "extracto" ? "el extracto y su conciliación pendiente"
      : d.tipo === "mis_comprobantes" ? "el archivo y todos los comprobantes que se cargaron desde él"
      : d.tipo === "f931" ? "el archivo y el costo laboral de ese período"
      : "el archivo y lo que se cargó desde él";
    if (!window.confirm(`¿Eliminar «${d.nombre}»?\n\nSe borra ${queSeBorra}. No se puede deshacer.`)) return;
    setReprocesando(d.id);
    try {
      await api.eliminarDocumento(d.id);
      setSubidas((s) => [{ nombre: d.nombre, estado: "ok", mensaje: "Eliminado" }, ...s]);
    } catch (e) {
      setSubidas((s) => [{ nombre: d.nombre, estado: "error", mensaje: mensajeDeError(e) }, ...s]);
    } finally {
      setReprocesando(null);
      await cargar();
    }
  }

  async function reprocesar(d: Documento) {
    setReprocesando(d.id);
    try {
      const r = await api.reprocesarDocumento(d.id);
      setSubidas((s) => [{ nombre: d.nombre, estado: "ok", mensaje: `Releído · ${TIPO[r.tipo] ?? r.tipo} · ${estadoDe(r.estado, r.tipo)?.texto ?? r.estado}` }, ...s]);
    } catch (e) {
      setSubidas((s) => [{ nombre: d.nombre, estado: "error", mensaje: mensajeDeError(e) }, ...s]);
    } finally {
      setReprocesando(null);
      await cargar();
    }
  }
  useEffect(() => {
    void cargar();
    void api.cuentas(clienteId).then((c) => {
      setCuentas(c);
      setCuenta((actual) => actual || c[0]?.codigo || "");
    });
  }, [clienteId]);

  async function subir(archivos: FileList | File[]) {
    for (const archivo of Array.from(archivos)) {
      setSubidas((s) => [{ nombre: archivo.name, estado: "subiendo" }, ...s]);
      const marcar = (cambio: Partial<Subida>) =>
        setSubidas((s) => s.map((x) => (x.nombre === archivo.name && x.estado === "subiendo" ? { ...x, ...cambio } : x)));
      try {
        let r = await api.subirDocumento(clienteId, archivo, cuenta || undefined);
        if (r.tipo === "en_cola" && r.trabajo_id) {
          // archivo grande: lo procesa el worker; se consulta hasta que termina (máx. 3 minutos)
          marcar({ mensaje: r.motivo === "ocr" ? "PDF escaneado: leyendo con OCR…" : "Archivo grande: procesando en segundo plano…" });
          const limite = Date.now() + 180_000;
          for (;;) {
            await new Promise((ok) => setTimeout(ok, 1500));
            const t = await api.trabajo(r.trabajo_id);
            if (t.estado === "hecho" && t.resultado) { r = t.resultado; break; }
            if (t.estado === "error") throw new Error(t.error ?? "No se pudo procesar el archivo");
            if (Date.now() > limite) throw new Error("Sigue en proceso: revisá la lista de documentos en unos minutos.");
          }
        }
        const repetidos = r.repetidos ?? 0;
        const avisoDup = !repetidos ? "" : r.tipo === "mis_comprobantes"
          ? ` · ⚠ ${repetidos} ${repetidos === 1 ? "comprobante ya estaba cargado" : "comprobantes ya estaban cargados"} (mismo CUIT, tipo, punto de venta y número): no se duplicaron`
          : ` · ⚠ ${repetidos} renglones ya estaban cargados: no se duplicaron`;
        marcar({ estado: repetidos ? "aviso" : "ok",
                 mensaje: `${TIPO[r.tipo] ?? r.tipo} · ${estadoDe(r.estado, r.tipo)?.texto ?? r.estado}${r.aviso_ocr ? ` · ${r.aviso_ocr}` : ""}${avisoDup}` });
      } catch (e) {
        marcar({ estado: "error", mensaje: mensajeDeError(e) });
      }
    }
    await cargar();
  }

  return (
    <div className="pila">
      <div
        className={`zona-carga${arrastrando ? " activa" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => entrada.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && entrada.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setArrastrando(true);
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastrando(false);
          void subir(e.dataTransfer.files);
        }}
      >
        <strong>Arrastrá acá los archivos del cliente</strong>
        <span>o hacé clic para elegirlos · Excel, CSV o PDF · extractos de bancos y billeteras, F.931, Mis Comprobantes</span>
        <input ref={entrada} type="file" multiple accept={ACEPTADOS} hidden onChange={(e) => e.target.files && void subir(e.target.files)} />
      </div>

      <div className="formulario-linea">
        <label>
          Los extractos van a la cuenta
          <select value={cuenta} onChange={(e) => setCuenta(e.target.value)}>
            {cuentas.length === 0 && <option value="">— primero cargá una cuenta —</option>}
            {cuentas.map((c) => <option key={c.codigo} value={c.codigo}>{c.codigo} · {c.nombre}</option>)}
          </select>
        </label>
        <span className="sub">F.931 y Mis Comprobantes se reconocen solos; no necesitan cuenta.</span>
      </div>

      {subidas.length > 0 && (
        <ul className="subidas" aria-live="polite">
          {subidas.map((s, i) => (
            <li key={`${s.nombre}-${i}`} className={`subida-${s.estado}`}>
              <span>{s.nombre}</span>
              <span>{s.estado === "subiendo" ? "Procesando…" : s.mensaje}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Archivo</th><th>Tipo</th><th>Estado</th><th>Detalle</th><th>Subido</th><th className="num">Tamaño</th><th /></tr>
          </thead>
          <tbody>
            {docs.length === 0 && <tr><td colSpan={7} className="vacio">Todavía no se subieron archivos.</td></tr>}
            {docs.map((d) => (
              <tr key={d.id}>
                <td>{d.nombre}</td>
                <td>{TIPO[d.tipo] ?? d.tipo}</td>
                <td><span className={`estado ${estadoDe(d.estado, d.tipo)?.clase ?? ""}`}>{estadoDe(d.estado, d.tipo)?.texto ?? d.estado}</span></td>
                <td className="sub">{d.detalle}</td>
                <td>{fecha(d.subido_en)}</td>
                <td className="num">{tamano(d.tamano_bytes)}</td>
                <td className="acciones-doc">
                  {d.lote_id && (
                    <a className="link" href={`#/clientes/${clienteId}/lotes/${d.lote_id}`}>
                      {d.estado === "aprobado" ? "Ver" : "Conciliar"}
                    </a>
                  )}
                  <button className="link" onClick={() => setViendo(d)}>Ver</button>
                  {puedeEliminar(d) && (
                    <button className="link peligro" disabled={reprocesando === d.id} onClick={() => void eliminar(d)}>Eliminar</button>
                  )}
                  {puedeReprocesar(d) && (
                    <button className="link" disabled={reprocesando === d.id} onClick={() => void reprocesar(d)}
                      title="Vuelve a leer el archivo original con el lector actual y reemplaza lo cargado desde él">
                      {reprocesando === d.id ? "Releyendo…" : "Reprocesar"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {viendo && <VistaDocumento id={viendo.id} alCerrar={cerrarVista} />}
      <ImportadorGenerico clienteId={clienteId} alTerminar={() => void cargar()} />
    </div>
  );
}
