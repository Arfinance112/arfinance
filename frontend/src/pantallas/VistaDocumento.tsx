import { useEffect, useState } from "react";

import { api, mensajeDeError, type VistaDocumento as Vista } from "../api/client";

/** Detalle de un documento: lo que el sistema leyó (tabla o texto) y acceso al archivo original. */
export function VistaDocumento({ id, alCerrar }: { id: string; alCerrar: () => void }) {
  const [vista, setVista] = useState<Vista | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [buscar, setBuscar] = useState("");

  useEffect(() => {
    void api.vistaDocumento(id).then(setVista).catch((e) => setError(mensajeDeError(e)));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && alCerrar();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [id, alCerrar]);

  const q = buscar.trim().toUpperCase();
  const filas = vista ? (q ? vista.filas.filter((f, i) => i === 0 || f.join(" ").toUpperCase().includes(q)) : vista.filas) : [];
  const anchas = filas.length > 0 && filas.some((f) => f.length > 1);

  return (
    <div className="modal-fondo" role="presentation" onClick={alCerrar}>
      <section className="modal tarjeta" role="dialog" aria-modal="true" aria-labelledby="vista-titulo" onClick={(e) => e.stopPropagation()}>
        <header className="modal-cabeza">
          <div>
            <h2 id="vista-titulo">{vista?.nombre ?? "Documento"}</h2>
            {vista && <p className="sub">{vista.detalle} · {vista.total_filas} filas leídas{vista.total_filas > vista.filas.length ? ` (se muestran ${vista.filas.length})` : ""}</p>}
          </div>
          <div className="acciones">
            <button className="btn btn-secundario btn-chico" onClick={() => void api.abrirDocumento(id).catch((e) => setError(mensajeDeError(e)))}>
              Abrir el original
            </button>
            <button className="btn btn-secundario btn-chico" aria-label="Cerrar" onClick={alCerrar}>✕</button>
          </div>
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        {!vista && !error && <p className="cargando">Leyendo el archivo…</p>}
        {vista && (
          <>
            <label className="vista-buscar">Buscar en el archivo
              <input type="search" value={buscar} onChange={(e) => setBuscar(e.target.value)} placeholder="Texto, importe, fecha…" />
            </label>
            {anchas ? (
              <div className="tabla-scroll modal-cuerpo">
                <table className="tabla tabla-compacta">
                  <tbody>
                    {filas.map((f, i) => (
                      <tr key={i} className={i === 0 ? "fila-encabezado" : undefined}>
                        {f.map((c, j) => <td key={j}>{c}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <pre className="modal-cuerpo vista-texto">{vista.texto || filas.map((f) => f.join(" ")).join("\n") || "El archivo no tiene texto legible (puede ser una imagen escaneada)."}</pre>
            )}
          </>
        )}
      </section>
    </div>
  );
}
