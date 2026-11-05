import { Fragment, useEffect, useState } from "react";

import { api } from "../api/client";
import { importe, mes } from "../formato";
import type { Resultados as ResultadosT } from "../types/app";

// Estructura del P&L de gestión (misma que PyL_Gestion de la planilla). `linea` abre el detalle por rubro.
const ESTRUCTURA: { clave: string; texto: string; tipo?: "total" | "pct"; linea?: string }[] = [
  { clave: "ingresos_netos", texto: "Ingresos netos", tipo: "total" },
  { clave: "costo_variable", texto: "Costo variable", linea: "4 Costo variable" },
  { clave: "margen_contribucion", texto: "Margen de contribución", tipo: "total" },
  { clave: "margen_contribucion_pct", texto: "Margen de contribución %", tipo: "pct" },
  { clave: "personal", texto: "Personal", linea: "5 Personal" },
  { clave: "estructura", texto: "Estructura", linea: "6 Estructura" },
  { clave: "comercializacion", texto: "Comercialización", linea: "7 Comercialización" },
  { clave: "impuestos_fijos", texto: "Impuestos fijos y tasas", linea: "8 Impuestos fijos y tasas" },
  { clave: "ebitda", texto: "EBITDA", tipo: "total" },
  { clave: "ebitda_pct", texto: "EBITDA %", tipo: "pct" },
  { clave: "resultado_financiero", texto: "Resultado financiero", linea: "9 Resultado financiero" },
  { clave: "resultado_neto", texto: "Resultado neto", tipo: "total" },
];
const PRIME = [
  { clave: "costo_materiales", texto: "Costo de materiales" },
  { clave: "material_cost_pct", texto: "Material cost %", tipo: "pct" },
  { clave: "costo_personal", texto: "Costo de personal" },
  { clave: "people_cost_pct", texto: "People cost %", tipo: "pct" },
  { clave: "prime_cost_pct", texto: "Prime cost %", tipo: "pct" },
];

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(Number(v) * 100).toFixed(1).replace(".", ",")} %`);

/** P&L de gestión mensual en ARS, devengado. */
export function Resultados({ clienteId }: { clienteId: string }) {
  const [res, setRes] = useState<ResultadosT | null>(null);
  const [rubroVentas, setRubroVentas] = useState("ING01");
  const [abiertas, setAbiertas] = useState<Set<string>>(new Set());

  useEffect(() => {
    setRes(null);
    void api.resultados(clienteId, rubroVentas).then(setRes);
  }, [clienteId, rubroVentas]);

  if (!res) return <p className="cargando">Calculando resultados…</p>;

  const celda = (v: number | null | undefined, esPct: boolean, clave: string) => (
    <td key={clave} className={`num${!esPct && Number(v ?? 0) < 0 ? " negativo" : ""}`}>
      {esPct ? pct(v) : v ? importe(Number(v)) : "–"}
    </td>
  );
  const total = (clave: string) => res.meses.reduce((s, m) => s + Number(res.filas[clave]?.[m] ?? 0), 0);
  const alternar = (l: string) =>
    setAbiertas((a) => {
      const n = new Set(a);
      if (n.has(l)) n.delete(l); else n.add(l);
      return n;
    });

  return (
    <div className="pila">
      {res.avisos.length > 0 && (
        <ul className="avisos" role="status">
          {res.avisos.map((a) => <li key={a}>{a}</li>)}
        </ul>
      )}
      <div className="formulario-linea">
        <label>
          Las ventas de Mis Comprobantes son
          <select value={rubroVentas} onChange={(e) => setRubroVentas(e.target.value)}>
            <option value="ING01">Venta de bienes</option>
            <option value="ING02">Venta de servicios</option>
          </select>
        </label>
        <span className="sub">Importes en ARS, devengados. Hacé clic en una línea para ver el detalle por rubro.</span>
      </div>

      {res.meses.length === 0 ? (
        <div className="tarjeta">Todavía no hay datos: subí Mis Comprobantes emitidos y recibidos, el F.931, o aprobá extractos.</div>
      ) : (
        <>
          <section className="tabla-scroll">
            <table className="tabla flujo">
              <caption>Estado de resultados de gestión</caption>
              <thead>
                <tr><th>Concepto</th>{res.meses.map((m) => <th key={m} className="num">{mes(m)}</th>)}<th className="num">Total</th></tr>
              </thead>
              <tbody>
                {ESTRUCTURA.map((f) => {
                  const esPct = f.tipo === "pct";
                  const detalle = f.linea ? res.detalle_por_linea[f.linea] : undefined;
                  const abierta = f.linea ? abiertas.has(f.linea) : false;
                  const base = f.clave.replace("_pct", "");
                  return (
                    <Fragment key={f.clave}>
                      <tr className={f.tipo === "total" ? "subtotal" : esPct ? "porcentaje" : undefined}>
                        <td>
                          {detalle ? (
                            <button type="button" className="link" aria-expanded={abierta} onClick={() => alternar(f.linea!)}>
                              {abierta ? "▾" : "▸"} {f.texto}
                            </button>
                          ) : f.texto}
                        </td>
                        {res.meses.map((m) => celda(res.filas[f.clave]?.[m], esPct, m))}
                        {esPct
                          ? celda(total("ingresos_netos") ? total(base) / total("ingresos_netos") : null, true, "t")
                          : celda(total(f.clave), false, "t")}
                      </tr>
                      {abierta && detalle && Object.entries(detalle).map(([rubro, serie]) => (
                        <tr key={rubro} className="detalle-rubro">
                          <td className="sangria">{rubro}</td>
                          {res.meses.map((m) => celda(serie[m], false, m))}
                          {celda(serie.total, false, "t")}
                        </tr>
                      ))}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section className="tabla-scroll">
            <table className="tabla flujo">
              <caption>Prime cost</caption>
              <thead>
                <tr><th>Indicador</th>{res.meses.map((m) => <th key={m} className="num">{mes(m)}</th>)}</tr>
              </thead>
              <tbody>
                {PRIME.map((f) => (
                  <tr key={f.clave} className={f.clave === "prime_cost_pct" ? "subtotal" : undefined}>
                    <td>{f.texto}</td>
                    {res.meses.map((m) => celda(res.filas[f.clave]?.[m], f.tipo === "pct", m))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
