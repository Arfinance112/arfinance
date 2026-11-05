import { useEffect, useMemo, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { importe, mes as mesCorto } from "../formato";
import type { Presupuesto as PresupuestoT } from "../types/app";
import type { Rubro } from "../types/conciliacion";

const numero = (texto: string) => Number(texto.replace(/\./g, "").replace(",", "."));

/** Presupuesto anual por rubro: base a precios de enero (editable) y nominal ajustado por índice. */
export function Presupuesto({ clienteId }: { clienteId: string }) {
  const [anio, setAnio] = useState(new Date().getFullYear());
  const [ppto, setPpto] = useState<PresupuestoT | null>(null);
  const [rubros, setRubros] = useState<Rubro[]>([]);
  const [vista, setVista] = useState<"base" | "nominal">("base");
  const [nuevoRubro, setNuevoRubro] = useState("");
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);
  // generador por etapas
  const [desde, setDesde] = useState(`${new Date().getFullYear()}-01`);
  const [hasta, setHasta] = useState(new Date().toISOString().slice(0, 7));
  const [volumen, setVolumen] = useState("0");
  const [objetivos, setObjetivos] = useState("");

  const cargar = () => api.presupuesto(clienteId, anio).then(setPpto);
  useEffect(() => {
    void cargar();
  }, [clienteId, anio]);
  useEffect(() => {
    void api.rubros().then((r) => setRubros(r.filter((x) => x.linea_pl !== "NO P&L")));
  }, []);

  const avisar = (ok: boolean, texto: string) => setMensaje({ ok, texto });
  const totalAnual = useMemo(
    () => (ppto ? ppto.filas.reduce((s, f) => s + Number(vista === "base" ? f.total_base : f.total_nominal) * (f.linea_pl.startsWith("1") || f.linea_pl.startsWith("2") || f.linea_pl.startsWith("3") ? 1 : -1), 0) : 0),
    [ppto, vista],
  );

  async function guardarCelda(rubro: string, mes: string, texto: string) {
    const valor = texto.trim() === "" ? null : numero(texto);
    if (valor !== null && (Number.isNaN(valor) || valor < 0)) return avisar(false, "Importe inválido: usá números positivos.");
    try {
      await api.guardarPresupuesto(clienteId, [{ rubro, mes, base: valor }]);
      await cargar();
    } catch (e) {
      avisar(false, mensajeDeError(e));
    }
  }

  async function agregarRubro() {
    if (!nuevoRubro || !ppto) return;
    // una fila nueva arranca con 0 en los 12 meses para que aparezca en la grilla
    await api.guardarPresupuesto(clienteId, ppto.meses.map((m) => ({ rubro: nuevoRubro, mes: m, base: 0 })));
    setNuevoRubro("");
    await cargar();
  }

  async function generar(e: React.FormEvent) {
    e.preventDefault();
    const meses: string[] = [];
    for (let d = new Date(`${desde}-01T12:00:00`); d <= new Date(`${hasta}-01T12:00:00`); d.setMonth(d.getMonth() + 1)) {
      meses.push(d.toISOString().slice(0, 10).replace(/-\d\d$/, "-01"));
    }
    const objs: Record<string, number> = {};
    for (const parte of objetivos.split(/[,;\n]/).map((p) => p.trim()).filter(Boolean)) {
      const [cod, pct] = parte.split(/[:=\s]+/);
      if (cod && pct) objs[cod.toUpperCase()] = numero(pct) / 100;
    }
    if (!window.confirm(`Esto reemplaza el presupuesto ${anio} por uno generado desde lo real. ¿Seguir?`)) return;
    try {
      const r = await api.generarPresupuesto(clienteId, { anio, meses_historicos: meses, ajuste_volumen: numero(volumen) / 100, objetivos: objs });
      avisar(true, `Presupuesto generado para ${r.rubros} rubros.`);
      await cargar();
    } catch (err) {
      avisar(false, mensajeDeError(err));
    }
  }

  if (!ppto) return <p className="cargando">Cargando presupuesto…</p>;
  const usados = new Set(ppto.filas.map((f) => f.rubro));

  return (
    <div className="pila">
      <div className="formulario-linea">
        <label>Año<input type="number" min={2000} max={2100} value={anio} onChange={(e) => setAnio(Number(e.target.value))} /></label>
        <nav className="filtros" aria-label="Vista">
          <button type="button" aria-pressed={vista === "base"} onClick={() => setVista("base")}>Base (precios de enero)</button>
          <button type="button" aria-pressed={vista === "nominal"} onClick={() => setVista("nominal")}>Nominal (ajustado por índice)</button>
        </nav>
        <span className="sub">Resultado presupuestado del año: ARS {importe(totalAnual)}</span>
      </div>
      {ppto.avisos.map((a) => <p key={a} className="avisos">{a}</p>)}
      <p role="status" aria-live="polite" className={mensaje?.ok ? "mensaje ok" : "error"}>{mensaje?.texto}</p>

      <div className="tabla-scroll">
        <table className="tabla flujo grilla-ppto">
          <thead>
            <tr><th>Rubro</th><th>Índice</th>{ppto.meses.map((m) => <th key={m} className="num">{mesCorto(m)}</th>)}<th className="num">Total</th></tr>
          </thead>
          <tbody>
            {ppto.filas.length === 0 && (
              <tr><td colSpan={15} className="vacio">Sin presupuesto para {anio}. Generalo desde lo real o agregá rubros a mano.</td></tr>
            )}
            {ppto.filas.map((f) => (
              <tr key={f.rubro}>
                <td><strong>{f.rubro}</strong> {f.nombre}<small className="linea">{f.linea_pl}</small></td>
                <td><span className="chip">{f.indice}</span></td>
                {ppto.meses.map((m) => (
                  <td key={m} className="num">
                    {vista === "base" ? (
                      <input
                        aria-label={`${f.rubro} ${mesCorto(m)}`}
                        className="celda-num"
                        inputMode="decimal"
                        defaultValue={Number(f.base[m]) ? importe(Number(f.base[m])) : ""}
                        key={`${f.rubro}-${m}-${f.base[m]}`}
                        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                        onBlur={(e) => {
                          const previo = Number(f.base[m]) ? importe(Number(f.base[m])) : "";
                          if (e.target.value !== previo) void guardarCelda(f.rubro, m, e.target.value);
                        }}
                      />
                    ) : (
                      importe(Number(f.nominal[m]))
                    )}
                  </td>
                ))}
                <td className="num"><strong>{importe(Number(vista === "base" ? f.total_base : f.total_nominal))}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="formulario-linea">
        <label>
          Agregar rubro
          <select value={nuevoRubro} onChange={(e) => setNuevoRubro(e.target.value)}>
            <option value="">— elegir —</option>
            {rubros.filter((r) => !usados.has(r.codigo)).map((r) => <option key={r.codigo} value={r.codigo}>{r.codigo} · {r.nombre}</option>)}
          </select>
        </label>
        <button type="button" className="btn btn-secundario" disabled={!nuevoRubro} onClick={() => void agregarRubro()}>Agregar</button>
      </div>

      <form className="tarjeta formulario-grilla" onSubmit={generar}>
        <h3>Generar desde lo real (por etapas)</h3>
        <p className="sub" style={{ gridColumn: "1 / -1", margin: 0 }}>
          1. Promedio de los meses elegidos, llevado a precios de enero. 2. Ajuste de volumen sobre los costos variables. 3. Objetivos por rubro.
        </p>
        <label>Desde<input type="month" required value={desde} onChange={(e) => setDesde(e.target.value)} /></label>
        <label>Hasta<input type="month" required value={hasta} onChange={(e) => setHasta(e.target.value)} /></label>
        <label>Ajuste de volumen (%)<input inputMode="decimal" value={volumen} onChange={(e) => setVolumen(e.target.value)} /></label>
        <label>Objetivos por rubro (%)<input placeholder="EST01 -5, COM01 -10" value={objetivos} onChange={(e) => setObjetivos(e.target.value)} /></label>
        <div className="acciones"><button className="btn btn-primario">Generar presupuesto {anio}</button></div>
      </form>
    </div>
  );
}
