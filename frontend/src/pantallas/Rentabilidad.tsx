import { useEffect, useState } from "react";

import { api } from "../api/client";
import { importe } from "../formato";
import type { FilaRentabilidad, Rentabilidad as RentabilidadT } from "../types/app";

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(Number(v) * 100).toFixed(1).replace(".", ",")} %`);
const inicioMes = () => new Date().toISOString().slice(0, 8) + "01";
const hoy = () => new Date().toISOString().slice(0, 10);

function diagnostico(f: FilaRentabilidad, promedio: number | null) {
  if (f.margen_pct == null) return null;
  if (Number(f.margen_pct) < 0) return <span className="estado sem-rojo">Vende a pérdida</span>;
  if (promedio != null && Number(f.margen_pct) < promedio) return <span className="estado sem-amarillo">Debajo del promedio</span>;
  return <span className="estado sem-verde">Sobre el promedio</span>;
}

/** Margen por unidad de negocio e ítem, punto de equilibrio con la mezcla real y margen de seguridad. */
export function Rentabilidad({ clienteId }: { clienteId: string }) {
  const [desde, setDesde] = useState(inicioMes());
  const [hasta, setHasta] = useState(hoy());
  const [r, setR] = useState<RentabilidadT | null>(null);

  useEffect(() => {
    setR(null);
    void api.rentabilidad(clienteId, desde, hasta).then(setR);
  }, [clienteId, desde, hasta]);

  const tabla = (filas: FilaRentabilidad[], titulo: string, conUnidad: boolean) => (
    <section className="tabla-scroll">
      <table className="tabla">
        <caption>{titulo}</caption>
        <thead>
          <tr>
            <th>{conUnidad ? "Ítem" : "Unidad de negocio"}</th>{conUnidad && <th>Unidad</th>}
            <th className="num">Cantidad</th><th className="num">Ventas</th><th className="num">Costo</th><th className="num">Mermas</th>
            <th className="num">Margen</th><th className="num">Margen %</th>{conUnidad && <th className="num">Margen unitario</th>}<th>Diagnóstico</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((f) => (
            <tr key={f.clave}>
              <td><strong>{f.clave}</strong>{conUnidad && ` ${f.nombre}`}</td>{conUnidad && <td>{f.unidad_negocio}</td>}
              <td className="num">{Number(f.cantidad).toLocaleString("es-AR")}</td>
              <td className="num">{importe(Number(f.ventas))}</td>
              <td className="num">{importe(Number(f.cmv))}</td>
              <td className="num">{importe(Number(f.mermas))}</td>
              <td className={`num${Number(f.margen) < 0 ? " negativo" : ""}`}>{importe(Number(f.margen))}</td>
              <td className="num">{pct(f.margen_pct)}</td>
              {conUnidad && <td className="num">{f.margen_unitario == null ? "–" : importe(Number(f.margen_unitario))}</td>}
              <td>{diagnostico(f, r?.margen_pct == null ? null : Number(r.margen_pct))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );

  return (
    <div className="pila">
      <div className="formulario-linea">
        <label>Desde<input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} /></label>
        <label>Hasta<input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} /></label>
        <span className="sub">Sale del detalle de ventas por ítem, a costo estándar. Subilo en Documentos.</span>
      </div>
      {!r ? <p className="cargando">Calculando…</p> : (
        <>
          {r.avisos.length > 0 && <ul className="avisos">{r.avisos.map((a) => <li key={a}>{a}</li>)}</ul>}
          <div className="grilla-tarjetas">
            <div className="tarjeta kpi kpi-destacado"><span>Margen de contribución</span><strong>{pct(r.margen_pct)}</strong></div>
            <div className="tarjeta kpi"><span>Ventas del período</span><strong>ARS {importe(Number(r.ventas))}</strong></div>
            <div className="tarjeta kpi"><span>Costos fijos del período</span><strong>ARS {importe(Number(r.costos_fijos))}</strong></div>
            <div className="tarjeta kpi"><span>Punto de equilibrio</span><strong>{r.punto_equilibrio == null ? "Sin margen" : `ARS ${importe(Number(r.punto_equilibrio))}`}</strong></div>
            <div className="tarjeta kpi">
              <span>Margen de seguridad</span>
              <strong className={r.margen_seguridad != null && Number(r.margen_seguridad) < 0 ? "negativo" : undefined}>{pct(r.margen_seguridad)}</strong>
              <small>{r.margen_seguridad == null ? "" : Number(r.margen_seguridad) < 0 ? "Por debajo del equilibrio" : "Cuánto pueden caer las ventas sin perder"}</small>
            </div>
          </div>
          {r.items.length === 0 ? (
            <div className="tarjeta">No hay ventas por ítem en el período.</div>
          ) : (
            <>
              {tabla(r.unidades, "Por unidad de negocio", false)}
              {tabla(r.items, "Por ítem (de menor a mayor margen)", true)}
            </>
          )}
        </>
      )}
    </div>
  );
}
