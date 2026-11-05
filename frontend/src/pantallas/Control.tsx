import { useEffect, useState } from "react";

import { api } from "../api/client";
import { importe } from "../formato";
import type { Control as ControlT, Semaforo } from "../types/app";

const SEMAFORO: Record<Semaforo, { texto: string; clase: string }> = {
  rojo: { texto: "Crítico", clase: "sem-rojo" },
  amarillo: { texto: "Alerta", clase: "sem-amarillo" },
  azul: { texto: "Favorable", clase: "sem-azul" },
  verde: { texto: "En rango", clase: "sem-verde" },
  sin_ppto: { texto: "Sin presupuesto", clase: "sem-gris" },
  sin_datos: { texto: "Sin datos", clase: "sem-gris" },
};
const pct = (v: number | null) => (v == null ? "–" : `${v > 0 ? "+" : ""}${(Number(v) * 100).toFixed(1).replace(".", ",")} %`);

/** Real vs presupuesto del mes y acumulado del año, con semáforo y explicación de cada desvío. */
export function Control({ clienteId }: { clienteId: string }) {
  const [mes, setMes] = useState(new Date().toISOString().slice(0, 7));
  const [datos, setDatos] = useState<ControlT | null>(null);
  const [soloAlertas, setSoloAlertas] = useState(false);

  useEffect(() => {
    setDatos(null);
    void api.control(clienteId, `${mes}-01`).then(setDatos);
  }, [clienteId, mes]);

  if (!datos) return <p className="cargando">Comparando…</p>;
  const filas = datos.filas.filter((f) => !soloAlertas || f.semaforo_mes === "rojo" || f.semaforo_mes === "amarillo");
  const chip = (s: Semaforo) => <span className={`estado ${SEMAFORO[s].clase}`}>{SEMAFORO[s].texto}</span>;

  return (
    <div className="pila">
      <div className="formulario-linea">
        <label>Mes<input type="month" value={mes} onChange={(e) => setMes(e.target.value)} /></label>
        <div className="grilla-semaforos">
          {(["rojo", "amarillo", "azul", "verde", "sin_ppto"] as Semaforo[]).map((s) => (
            <span key={s} className="semaforo-cuenta">{chip(s)} <strong>{datos.resumen[s] ?? 0}</strong></span>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={soloAlertas} onChange={(e) => setSoloAlertas(e.target.checked)} />Solo críticos y alertas</label>
      </div>
      {datos.avisos.length > 0 && <ul className="avisos">{datos.avisos.map((a) => <li key={a}>{a}</li>)}</ul>}

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr>
              <th>Rubro</th><th className="num">Presupuesto</th><th className="num">Real</th><th className="num">Desvío</th>
              <th>Mes</th><th className="num">Acum. ppto</th><th className="num">Acum. real</th><th className="num">Desvío acum.</th><th>Acum.</th>
              <th>Explicación del desvío</th>
            </tr>
          </thead>
          <tbody>
            {filas.length === 0 && <tr><td colSpan={10} className="vacio">No hay rubros para mostrar en este mes.</td></tr>}
            {filas.map((f) => (
              <tr key={f.rubro}>
                <td><strong>{f.rubro}</strong> {f.nombre}<small className="linea">{f.linea_pl} · tolerancia {Math.round(Number(f.tolerancia) * 100)} %</small></td>
                <td className="num">{importe(Number(f.ppto_mes))}</td>
                <td className="num">{importe(Number(f.real_mes))}</td>
                <td className="num">{pct(f.desvio_pct_mes)}</td>
                <td>{chip(f.semaforo_mes)}</td>
                <td className="num">{importe(Number(f.ppto_acum))}</td>
                <td className="num">{importe(Number(f.real_acum))}</td>
                <td className="num">{pct(f.desvio_pct_acum)}</td>
                <td>{chip(f.semaforo_acum)}</td>
                <td>
                  <input
                    aria-label={`Explicación del desvío de ${f.rubro}`}
                    className="celda-nota"
                    placeholder={f.semaforo_mes === "rojo" ? "Explicá este desvío" : ""}
                    defaultValue={f.nota}
                    key={`${f.rubro}-${datos.mes}`}
                    onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                    onBlur={(e) => {
                      if (e.target.value !== f.nota) void api.guardarNota(clienteId, f.rubro, `${mes}-01`, e.target.value);
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
