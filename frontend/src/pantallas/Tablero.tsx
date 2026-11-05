import { useEffect, useState } from "react";

import { api } from "../api/client";
import { importe } from "../formato";
import type { Cierre, Kpi, Tablero as TableroT } from "../types/app";

const mesActual = () => new Date().toISOString().slice(0, 7);
const coma = (n: number, dec: number) => n.toFixed(dec).replace(".", ",");

function valor(v: number | null, formato: Kpi["formato"]) {
  if (v == null) return "–";
  const n = Number(v);
  switch (formato) {
    case "ars": return `ARS ${importe(n)}`;
    case "pct": return `${coma(n * 100, 1)} %`;
    case "dias": return `${coma(n, 0)} días`;
    case "x": return `${coma(n, 2)}×`;
    default: return n.toLocaleString("es-AR");
  }
}

function variacion(k: Kpi) {
  if (k.variacion == null) return null;
  const v = Number(k.variacion);
  const texto = k.formato === "pct" ? `${v >= 0 ? "+" : ""}${coma(v * 100, 1)} pp` : `${v >= 0 ? "+" : ""}${coma(v * 100, 1)} %`;
  const bueno = k.direccion === "≥" ? v >= 0 : v <= 0;
  return <span className={bueno ? "var-buena" : "var-mala"}>{texto} vs mes anterior</span>;
}

const CAMPOS_CIERRE: [keyof Omit<Cierre, "mes">, string][] = [
  ["stock", "Stock (a costo)"], ["bienes_uso", "Bienes de uso (neto)"], ["otros_activos", "Otros activos"],
  ["deudas_financieras", "Deudas financieras"], ["deudas_fiscales", "Deudas fiscales"], ["otros_pasivos", "Otros pasivos"],
  ["amortizacion_mes", "Amortización del mes"],
];

/** Tarjeta de un indicador: valor, semáforo contra la meta (editable), mes anterior y presupuesto. */
function TarjetaKpi({ k, onMeta }: { k: Kpi; onMeta: (meta: string | null) => Promise<void> }) {
  const [editando, setEditando] = useState(false);
  const [meta, setMeta] = useState(k.meta == null ? "" : String(k.formato === "pct" ? Number(k.meta) * 100 : k.meta));
  const guardar = async () => {
    const n = meta.trim().replace(",", ".");
    await onMeta(n === "" ? null : String(k.formato === "pct" ? Number(n) / 100 : Number(n)));
    setEditando(false);
  };
  return (
    <div className={`tarjeta kpi-tablero${k.semaforo ? ` borde-${k.semaforo}` : ""}`}>
      <div className="kpi-cabeza">
        <span>{k.nombre}</span>
        {k.semaforo && <span className={`estado sem-${k.semaforo}`}>{{ verde: "Cumple", amarillo: "Cerca", rojo: "Fuera" }[k.semaforo]}</span>}
      </div>
      <strong className={k.valor != null && Number(k.valor) < 0 ? "negativo" : undefined}>{valor(k.valor, k.formato)}</strong>
      <small>{variacion(k)}</small>
      {k.presupuesto != null && <small>Presupuesto: {valor(k.presupuesto, k.formato)}</small>}
      {editando ? (
        <form className="kpi-meta" onSubmit={(e) => { e.preventDefault(); void guardar(); }}>
          <span>Meta {k.direccion}</span>
          <input aria-label={`Meta de ${k.nombre}`} value={meta} onChange={(e) => setMeta(e.target.value)} autoFocus
            placeholder={k.formato === "pct" ? "%" : "vacío = sin meta"} />
          <button className="btn btn-primario btn-chico">OK</button>
        </form>
      ) : (
        <button className="link kpi-meta" onClick={() => setEditando(true)}>
          {k.meta == null ? "Fijar meta" : `Meta ${k.direccion} ${valor(k.meta, k.formato)}`}
        </button>
      )}
    </div>
  );
}

/** Ingresos (barras) y EBITDA (línea) de los últimos 12 meses. */
function Grafico({ serie }: { serie: TableroT["serie"] }) {
  const n = serie.meses.length;
  if (n === 0) return null;
  const ing = serie.ingresos_netos.map((v) => Number(v ?? 0));
  const eb = serie.ebitda.map((v) => Number(v ?? 0));
  const max = Math.max(1, ...ing, ...eb), min = Math.min(0, ...eb);
  const W = 640, H = 200, pad = 24, ancho = (W - pad * 2) / n;
  const y = (v: number) => pad + ((max - v) / (max - min)) * (H - pad * 2);
  const etiqueta = (m: string) => new Date(m + "T00:00").toLocaleDateString("es-AR", { month: "short", year: "2-digit" });
  return (
    <figure className="tarjeta grafico">
      <figcaption>Ingresos y EBITDA, últimos {n} meses <span className="leyenda"><i className="l-ing" />Ingresos <i className="l-eb" />EBITDA</span></figcaption>
      <svg viewBox={`0 0 ${W} ${H + 16}`} role="img" aria-label="Ingresos y EBITDA por mes">
        <line x1={pad} x2={W - pad} y1={y(0)} y2={y(0)} className="eje" />
        {ing.map((v, i) => (
          <rect key={serie.meses[i]} x={pad + i * ancho + ancho * 0.2} width={ancho * 0.6} y={Math.min(y(v), y(0))} height={Math.abs(y(0) - y(v))} className="barra">
            <title>{`${etiqueta(serie.meses[i])}: ingresos ARS ${importe(v)} · EBITDA ARS ${importe(eb[i])}`}</title>
          </rect>
        ))}
        <polyline points={eb.map((v, i) => `${pad + i * ancho + ancho / 2},${y(v)}`).join(" ")} className="linea" />
        {eb.map((v, i) => <circle key={serie.meses[i]} cx={pad + i * ancho + ancho / 2} cy={y(v)} r={3} className="punto" />)}
        {serie.meses.map((m, i) => <text key={m} x={pad + i * ancho + ancho / 2} y={H + 10} textAnchor="middle">{etiqueta(m)}</text>)}
      </svg>
    </figure>
  );
}

/** Tablero ejecutivo: KPIs del mes contra meta, mes anterior y presupuesto; proyección de caja y datos de cierre. */
export function Tablero({ clienteId }: { clienteId: string }) {
  const [mes, setMes] = useState(mesActual());
  const [t, setT] = useState<TableroT | null>(null);
  const [cierre, setCierre] = useState<Cierre | null>(null);
  const [verCierre, setVerCierre] = useState(false);
  const [aviso, setAviso] = useState("");

  const cargar = async () => {
    const [tab, cierres] = await Promise.all([api.tablero(clienteId, `${mes}-01`), api.cierres(clienteId)]);
    setT(tab);
    const vacio = Object.fromEntries(CAMPOS_CIERRE.map(([c]) => [c, "0"])) as Omit<Cierre, "mes">;
    setCierre(cierres.find((c) => c.mes.startsWith(mes)) ?? { mes: `${mes}-01`, ...vacio });
  };
  useEffect(() => { setT(null); void cargar(); }, [clienteId, mes]); // eslint-disable-line react-hooks/exhaustive-deps

  const guardarCierre = async () => {
    if (!cierre) return;
    try {
      await api.guardarCierre(clienteId, { ...cierre, mes: `${mes}-01` });
      setAviso("Datos de cierre guardados.");
      setVerCierre(false);
      await cargar();
    } catch (e) {
      setAviso(e instanceof Error ? e.message : "No se pudo guardar");
    }
  };

  return (
    <div className="pila">
      <div className="formulario-linea">
        <label>Mes<input type="month" value={mes} onChange={(e) => e.target.value && setMes(e.target.value)} /></label>
        <button className="btn btn-secundario" disabled={!t}
          onClick={() => void api.tableroExcel(clienteId, `${mes}-01`).catch((e: Error) => setAviso(e.message))}>Exportar a Excel</button>
        <button className="btn btn-secundario" disabled={!t} onClick={() => window.print()}>Exportar a PDF</button>
        <button className="btn btn-secundario" onClick={() => setVerCierre(!verCierre)}>{verCierre ? "Cerrar" : "Datos de cierre del mes"}</button>
        {aviso && <span className="sub">{aviso}</span>}
      </div>

      {verCierre && cierre && (
        <form className="tarjeta form-cierre" onSubmit={(e) => { e.preventDefault(); void guardarCierre(); }}>
          <p className="sub">Saldos a fin de mes en ARS que no salen de los registros. Habilitan días de stock, prueba ácida, endeudamiento y Dupont.</p>
          <div className="grilla-campos">
            {CAMPOS_CIERRE.map(([c, rotulo]) => (
              <label key={c}>{rotulo}
                <input inputMode="decimal" value={cierre[c]} onChange={(e) => setCierre({ ...cierre, [c]: e.target.value.replace(",", ".") })} />
              </label>
            ))}
          </div>
          <button className="btn btn-primario">Guardar cierre</button>
        </form>
      )}

      {!t ? <p className="cargando">Calculando…</p> : (
        <>
          {t.avisos.length > 0 && <ul className="avisos">{t.avisos.map((a) => <li key={a}>{a}</li>)}</ul>}
          <Grafico serie={t.serie} />

          <section className="tarjeta">
            <h2 className="titulo-seccion">Proyección de caja</h2>
            <div className="tramos">
              {t.proyeccion.tramos.map((tr, i) => (
                <div key={tr.desde} className="tramo">
                  <span>{["0 a 30", "31 a 60", "61 a 90"][i]} días</span>
                  <small>Flujo {importe(Number(tr.flujo))}</small>
                  <strong className={Number(tr.saldo) < 0 ? "negativo" : undefined}>ARS {importe(Number(tr.saldo))}</strong>
                </div>
              ))}
              {Number(t.proyeccion.necesidad_financiamiento) > 0 && (
                <div className="tramo alerta"><span>Necesidad de financiamiento</span><strong>ARS {importe(Number(t.proyeccion.necesidad_financiamiento))}</strong></div>
              )}
            </div>
            <p className="sub">Cobranzas y pagos pendientes de facturas a 30 días, sueldos devengados y gastos presupuestados sin factura. Cobranzas vencidas: ARS {importe(Number(t.proyeccion.cobranzas_vencidas))} (se estima recuperar la mitad).</p>
          </section>

          {t.secciones.map((s) => (
            <section key={s.titulo}>
              <h2 className="titulo-seccion">{s.titulo}</h2>
              <div className="grilla-tarjetas">
                {s.kpis.map((k) => (
                  <TarjetaKpi key={`${k.clave}-${k.meta}`} k={k}
                    onMeta={async (meta) => { await api.guardarMeta(clienteId, k.clave, meta, k.direccion); await cargar(); }} />
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
