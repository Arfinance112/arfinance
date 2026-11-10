import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { importe, mes } from "../formato";
import type { Impuestos as ImpuestosT } from "../types/app";

const pct = (texto: string) => Number(texto.replace(",", ".")) / 100;

/** Estimación de IVA, IIBB y Ganancias por mes, con proyección de los próximos 3 meses. */
export function Impuestos({ clienteId }: { clienteId: string }) {
  const [datos, setDatos] = useState<ImpuestosT | null>(null);
  const [iibb, setIibb] = useState("3,5");
  const [ganancias, setGanancias] = useState("35");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const a = pct(iibb), g = pct(ganancias);
    if (Number.isNaN(a) || Number.isNaN(g)) return;
    const t = setTimeout(() => {
      api.impuestos(clienteId, a, g).then((d) => { setDatos(d); setError(null); }).catch((e) => setError(mensajeDeError(e)));
    }, 300);
    return () => clearTimeout(t);
  }, [clienteId, iibb, ganancias]);

  if (!datos) return <p className="cargando">{error ?? "Calculando impuestos…"}</p>;
  const filas = [...datos.meses, ...datos.proyeccion];
  const g = datos.ganancias;

  return (
    <div className="pila">
      {error && <p className="error" role="alert">{error}</p>}
      <div className="formulario-linea">
        <label>Alícuota IIBB (%)<input inputMode="decimal" className="input-chico" value={iibb} onChange={(e) => setIibb(e.target.value)} /></label>
        <label>Tasa Ganancias (%)<input inputMode="decimal" className="input-chico" value={ganancias} onChange={(e) => setGanancias(e.target.value)} /></label>
        <span className="sub">Estimación de gestión: no reemplaza la liquidación del contador.</span>
      </div>

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Mes</th><th className="num">Débito IVA</th><th className="num">Crédito IVA</th><th className="num">IVA a pagar</th>
              <th className="num">Saldo a favor</th><th className="num">Ventas netas</th><th className="num">IIBB</th><th className="num">Total</th></tr>
          </thead>
          <tbody>
            {filas.length === 0 && <tr><td colSpan={8} className="vacio">Subí Mis Comprobantes emitidos y recibidos para estimar los impuestos.</td></tr>}
            {filas.map((f) => (
              <tr key={f.mes} className={f.proyectado ? "fila-proyectada" : undefined}>
                <td>{mes(f.mes)}{f.proyectado && <span className="chip">proyección</span>}</td>
                <td className="num">{importe(Number(f.debito_iva))}</td>
                <td className="num">{importe(Number(f.credito_iva))}</td>
                <td className="num"><strong>{importe(Number(f.iva_a_pagar))}</strong></td>
                <td className="num">{importe(Number(f.saldo_a_favor))}</td>
                <td className="num">{importe(Number(f.ventas_netas))}</td>
                <td className="num">{importe(Number(f.iibb))}</td>
                <td className="num"><strong>{importe(Number(f.total))}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="tarjeta">
        <h3>Impuesto a las Ganancias (estimado)</h3>
        {g.meses === 0 ? <p className="sub">Todavía no hay resultado de gestión para estimarlo.</p> : (
          <dl className="cifras">
            <div><dt>Resultado antes de impuestos ({g.meses} {g.meses === 1 ? "mes" : "meses"})</dt><dd>{importe(Number(g.bai_acumulado))}</dd></div>
            <div><dt>Impuesto sobre lo acumulado</dt><dd>{importe(Number(g.impuesto_acumulado))}</dd></div>
            <div><dt>Resultado anualizado</dt><dd>{g.bai_anualizado == null ? "–" : importe(Number(g.bai_anualizado))}</dd></div>
            <div><dt>Impuesto anual estimado</dt><dd>{g.impuesto_anual_estimado == null ? "–" : importe(Number(g.impuesto_anual_estimado))}</dd></div>
          </dl>
        )}
      </div>
      <p className="sub">IVA: débito de las facturas emitidas menos crédito de las recibidas (con notas de crédito), arrastrando el saldo a favor; no
        incluye percepciones ni retenciones. IIBB: ventas netas × alícuota única (sin convenio multilateral). Ganancias: una sola tasa sobre el
        resultado de gestión; la escala real de sociedades es progresiva. La proyección usa el promedio de los últimos 3 meses.</p>
    </div>
  );
}
