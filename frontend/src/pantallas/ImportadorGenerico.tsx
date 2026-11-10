import { useState } from "react";

import { api, mensajeDeError } from "../api/client";
import type { VistaImportacion } from "../types/app";

/** Cualquier planilla o CSV: se ve el contenido y se elige qué columna es cada dato. */
export function ImportadorGenerico({ clienteId, alTerminar }: { clienteId: string; alTerminar: () => void }) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [vista, setVista] = useState<VistaImportacion | null>(null);
  const [destino, setDestino] = useState("ventas_item");
  const [mapeo, setMapeo] = useState<Record<string, number | "">>({});
  const [ocupado, setOcupado] = useState(false);
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  async function ver(f: File, fila?: number) {
    setOcupado(true); setMensaje(null);
    try {
      const v = await api.vistaImportacion(clienteId, f, fila);
      setVista(v);
      setMapeo(v.destinos[destino].sugerido);
    } catch (e) { setMensaje({ ok: false, texto: mensajeDeError(e) }); setVista(null); }
    finally { setOcupado(false); }
  }

  async function importar() {
    if (!archivo || !vista) return;
    setOcupado(true);
    try {
      const r = await api.importarConMapeo(clienteId, archivo, destino, mapeo, vista.fila_encabezado);
      const texto = r.tipo === "inversiones"
        ? `${r.importados} movimientos de inversiones importados${r.con_errores ? `; ${r.con_errores} filas no se pudieron leer: ${r.errores.join(" ")}` : "."}`
        : `${r.nuevos} renglones importados${r.repetidos ? ` (${r.repetidos} ya estaban)` : ""}${r.items_desconocidos?.length ? `. Códigos sin alta en Ítems: ${r.items_desconocidos.join(", ")}` : "."}`;
      setMensaje({ ok: true, texto });
      alTerminar();
    } catch (e) { setMensaje({ ok: false, texto: mensajeDeError(e) }); }
    finally { setOcupado(false); }
  }

  const campos = vista?.destinos[destino];

  return (
    <div className="tarjeta pila">
      <h3>Importar otro formato</h3>
      <p className="sub">Para planillas que la app no reconoce sola: elegís el archivo, decís qué es cada columna y se importa
        como ventas por ítem, compras por ítem o inversiones.</p>
      <label>Archivo (Excel o CSV)
        <input type="file" accept=".xlsx,.xlsm,.csv,.txt" onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          setArchivo(f);
          if (f) void ver(f);
        }} />
      </label>

      {vista && campos && (
        <>
          <div className="formulario-linea">
            <label>Los títulos están en la fila
              <input type="number" min={1} className="input-chico" value={vista.fila_encabezado + 1}
                onChange={(e) => archivo && Number(e.target.value) >= 1 && void ver(archivo, Number(e.target.value) - 1)} />
            </label>
            <label>Importar como
              <select value={destino} onChange={(e) => { setDestino(e.target.value); setMapeo(vista.destinos[e.target.value].sugerido); }}>
                {Object.entries(vista.destinos).map(([k, d]) => <option key={k} value={k}>{d.nombre}</option>)}
              </select>
            </label>
            <span className="sub">{vista.total_filas} filas de datos</span>
          </div>

          <div className="formulario-grilla">
            {campos.campos.map((c) => (
              <label key={c.campo}>{c.etiqueta}{c.obligatorio ? " *" : ""}
                <select value={mapeo[c.campo] ?? ""} onChange={(e) => setMapeo({ ...mapeo, [c.campo]: e.target.value === "" ? "" : Number(e.target.value) })}>
                  <option value="">{c.obligatorio ? "— elegir columna —" : "— no tiene —"}</option>
                  {vista.columnas.map((col, i) => <option key={i} value={i}>{col}</option>)}
                </select>
              </label>
            ))}
          </div>

          <div className="tabla-scroll">
            <table className="tabla">
              <thead><tr>{vista.columnas.map((col, i) => {
                const usado = campos.campos.find((c) => mapeo[c.campo] === i);
                return <th key={i}>{col}{usado && <span className="chip">{usado.etiqueta}</span>}</th>;
              })}</tr></thead>
              <tbody>{vista.muestra.map((f, n) => <tr key={n}>{vista.columnas.map((_, i) => <td key={i}>{f[i] ?? ""}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <div className="acciones">
            <button className="btn btn-primario" disabled={ocupado} onClick={() => void importar()}>Importar</button>
          </div>
        </>
      )}
      {mensaje && <p role="status" className={mensaje.ok ? "mensaje ok" : "error"}>{mensaje.texto}</p>}
    </div>
  );
}
