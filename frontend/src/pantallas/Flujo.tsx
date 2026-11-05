import { Fragment, useEffect, useState } from "react";

import { api } from "../api/client";
import { importe, mes } from "../formato";
import type { Flujo as FlujoT } from "../types/app";

const GRUPOS = ["Operativo", "Inversión", "Financiación", "Interno"];

/** Cash flow real por mes (método directo), una tabla por moneda. */
export function Flujo({ clienteId }: { clienteId: string }) {
  const [flujo, setFlujo] = useState<FlujoT | null>(null);
  useEffect(() => {
    void api.flujo(clienteId).then(setFlujo);
  }, [clienteId]);

  if (!flujo) return <p className="cargando">Calculando…</p>;
  const monedas = Object.keys(flujo).sort((a, b) => (a === "ARS" ? -1 : b === "ARS" ? 1 : a.localeCompare(b)));
  if (monedas.length === 0) return <div className="tarjeta">Todavía no hay movimientos aprobados en Tesorería.</div>;
  const celda = (v: number | undefined, clave = "total") => (
    <td key={clave} className={`num${(v ?? 0) < 0 ? " negativo" : ""}`}>{v ? importe(Number(v)) : "–"}</td>
  );

  return (
    <div className="pila">
      <p className="sub">Caja real por mes según Tesorería, en la moneda de cada cuenta. La versión consolidada en pesos y dólares llega con la carga de índices y tipos de cambio.</p>
      {monedas.map((mon) => {
        const f = flujo[mon];
        return (
          <section key={mon} className="tabla-scroll">
            <table className="tabla flujo">
              <caption>Flujo de caja en {mon}</caption>
              <thead>
                <tr><th>Concepto</th>{f.meses.map((m) => <th key={m} className="num">{mes(m)}</th>)}<th className="num">Total</th></tr>
              </thead>
              <tbody>
                {GRUPOS.filter((g) => f.lineas.some((l) => l.grupo === g)).map((g) => (
                  <Fragment key={g}>
                    {f.lineas.filter((l) => l.grupo === g).map((l) => (
                      <tr key={l.linea}><td className="sangria">{l.linea}</td>{f.meses.map((m) => celda(l.valores[m], m))}{celda(l.total)}</tr>
                    ))}
                    <tr className="subtotal">
                      <td>Flujo {g.toLowerCase()}</td>
                      {f.meses.map((m) => celda(f.totales[g]?.[m], m))}
                      {celda(f.meses.reduce((s, m) => s + Number(f.totales[g]?.[m] ?? 0), 0))}
                    </tr>
                  </Fragment>
                ))}
                <tr className="total">
                  <td>Variación neta de caja</td>
                  {f.meses.map((m) => celda(f.totales["Variación neta"]?.[m], m))}
                  {celda(f.meses.reduce((s, m) => s + Number(f.totales["Variación neta"]?.[m] ?? 0), 0))}
                </tr>
              </tbody>
            </table>
          </section>
        );
      })}
    </div>
  );
}
