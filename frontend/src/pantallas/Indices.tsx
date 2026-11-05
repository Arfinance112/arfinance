import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { mes as mesCorto } from "../formato";
import type { FilaIndice } from "../types/app";

const COTIZACIONES = ["USD_OFICIAL", "USD_MEP", "USD_CCL", "USD_BLUE", "USDT", "EUR_OFICIAL", "BRL_OFICIAL"];

/** Índices (IPC, paritaria, tarifas) y tipos de cambio mensuales. Comunes a todos los clientes. */
export function Indices() {
  const [filas, setFilas] = useState<FilaIndice[]>([]);
  const [mes, setMes] = useState(new Date().toISOString().slice(0, 7));
  const [ipc, setIpc] = useState("");
  const [tc, setTc] = useState<Record<string, string>>({});
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  const cargar = () => api.indices().then(setFilas);
  useEffect(() => {
    void cargar();
  }, []);

  async function guardar(e: React.FormEvent) {
    e.preventDefault();
    const tcs = Object.fromEntries(Object.entries(tc).filter(([, v]) => v.trim()).map(([k, v]) => [k, Number(v.replace(",", "."))]));
    try {
      await api.guardarIndice(`${mes}-01`, { ipc: ipc.trim() ? Number(ipc.replace(",", ".")) / 100 : null, tc: tcs });
      setMensaje({ ok: true, texto: `Guardado ${mesCorto(`${mes}-01`)}.` });
      setIpc("");
      setTc({});
      await cargar();
    } catch (err) {
      setMensaje({ ok: false, texto: mensajeDeError(err) });
    }
  }

  return (
    <div className="pila">
      <form className="tarjeta formulario-grilla" onSubmit={guardar}>
        <h3>Cargar o corregir un mes</h3>
        <label>Mes<input type="month" required value={mes} onChange={(e) => setMes(e.target.value)} /></label>
        <label>IPC del mes (%)<input inputMode="decimal" placeholder="2,1" value={ipc} onChange={(e) => setIpc(e.target.value)} /></label>
        {COTIZACIONES.map((c) => (
          <label key={c}>{c.replace("_", " ")}
            <input inputMode="decimal" placeholder="—" value={tc[c] ?? ""} onChange={(e) => setTc({ ...tc, [c]: e.target.value })} />
          </label>
        ))}
        <div className="acciones">
          <button className="btn btn-primario">Guardar</button>
          <span className="sub">Fuentes: INDEC (IPC), BNA / BCRA (oficial), tu broker (MEP y CCL), tu exchange (USDT). Si falta un mes, se usa el último cargado.</span>
          {mensaje && <span className={mensaje.ok ? "mensaje ok" : "error"} role="status">{mensaje.texto}</span>}
        </div>
      </form>

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Mes</th><th className="num">IPC</th>{COTIZACIONES.map((c) => <th key={c} className="num">{c.replace("_", " ")}</th>)}</tr>
          </thead>
          <tbody>
            {filas.length === 0 && <tr><td colSpan={COTIZACIONES.length + 2} className="vacio">Sin índices cargados.</td></tr>}
            {[...filas].reverse().map((f) => (
              <tr key={f.mes}>
                <td>{mesCorto(f.mes)}</td>
                <td className="num">{f.ipc == null ? "–" : `${(Number(f.ipc) * 100).toFixed(1).replace(".", ",")} %`}</td>
                {COTIZACIONES.map((c) => <td key={c} className="num">{f.tc[c] ? Number(f.tc[c]).toLocaleString("es-AR") : "–"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
