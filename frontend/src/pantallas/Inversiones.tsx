import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { fecha, importe } from "../formato";
import type { Inversiones as InversionesT } from "../types/app";

const TIPOS = { aporte: "Aporte / suscripción", rescate: "Rescate", valuacion: "Valuación (cuánto vale hoy)" } as const;
const hoy = () => new Date().toISOString().slice(0, 10);

/** FCI, plazos fijos, cauciones y títulos: lo aportado, lo rescatado y cuánto vale hoy. */
export function Inversiones({ clienteId }: { clienteId: string }) {
  const [datos, setDatos] = useState<InversionesT | null>(null);
  const [form, setForm] = useState({ fecha: hoy(), instrumento: "FCI", nombre: "", tipo: "aporte", importe: "", moneda: "ARS" });
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  const cargar = () => api.inversiones(clienteId).then(setDatos);
  useEffect(() => { cargar().catch((e) => setMensaje({ ok: false, texto: mensajeDeError(e) })); }, [clienteId]);

  async function registrar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.registrarInversion(clienteId, { ...form, importe: form.importe.replace(/\./g, "").replace(",", ".") });
      setForm({ ...form, importe: "" });
      setMensaje({ ok: true, texto: "Movimiento registrado." });
      await cargar();
    } catch (err) {
      setMensaje({ ok: false, texto: mensajeDeError(err) });
    }
  }

  async function borrar(id: string) {
    if (!window.confirm("¿Borrar este movimiento? No se puede deshacer.")) return;
    try { await api.borrarInversion(clienteId, id); await cargar(); }
    catch (err) { setMensaje({ ok: false, texto: mensajeDeError(err) }); }
  }

  if (!datos) return <p className="cargando">{mensaje?.texto ?? "Cargando inversiones…"}</p>;
  const nombres = [...new Set(datos.movimientos.map((m) => m.nombre))];

  return (
    <div className="pila">
      <p role="status" aria-live="polite" className={mensaje?.ok ? "mensaje ok" : "error"}>{mensaje?.texto}</p>
      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Instrumento</th><th>Nombre</th><th>Moneda</th><th className="num">Aportado</th><th className="num">Rescatado</th>
              <th className="num">Valuación</th><th className="num">Resultado</th><th className="num">Rendimiento</th></tr>
          </thead>
          <tbody>
            {datos.posiciones.length === 0 && <tr><td colSpan={8} className="vacio">Todavía no hay inversiones cargadas.</td></tr>}
            {datos.posiciones.map((p) => (
              <tr key={`${p.instrumento}-${p.nombre}-${p.moneda}`}>
                <td>{p.instrumento}</td><td>{p.nombre}</td><td>{p.moneda}</td>
                <td className="num">{importe(Number(p.aportado))}</td>
                <td className="num">{importe(Number(p.rescatado))}</td>
                <td className="num">{p.valuacion == null ? <span className="sub">sin valuar</span>
                  : <>{importe(Number(p.valuacion))} <span className="sub">{fecha(p.fecha_valuacion!)}</span></>}</td>
                <td className={`num${Number(p.resultado ?? 0) < 0 ? " negativo" : ""}`}>{p.resultado == null ? "–" : importe(Number(p.resultado))}</td>
                <td className={`num${Number(p.rendimiento ?? 0) < 0 ? " negativo" : ""}`}>
                  {p.rendimiento == null ? "–" : `${(Number(p.rendimiento) * 100).toFixed(2)} %`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="sub">Resultado = última valuación + lo rescatado − lo aportado. Cargá una valuación cada mes (del resumen del banco o
        la sociedad gerente) para ver el rendimiento. Cada moneda se calcula por separado.</p>

      <form className="tarjeta formulario-grilla" onSubmit={registrar}>
        <h3>Registrar movimiento</h3>
        <label>Fecha<input type="date" required value={form.fecha} onChange={(e) => setForm({ ...form, fecha: e.target.value })} /></label>
        <label>Instrumento
          <select value={form.instrumento} onChange={(e) => setForm({ ...form, instrumento: e.target.value })}>
            {datos.instrumentos.map((i) => <option key={i}>{i}</option>)}
          </select>
        </label>
        <label>Nombre (fondo, banco, especie)
          <input required maxLength={80} list="lista-inversiones" value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} />
          <datalist id="lista-inversiones">{nombres.map((n) => <option key={n} value={n} />)}</datalist>
        </label>
        <label>Tipo
          <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
            {Object.entries(TIPOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Importe<input required inputMode="decimal" value={form.importe} onChange={(e) => setForm({ ...form, importe: e.target.value })} /></label>
        <label>Moneda
          <select value={form.moneda} onChange={(e) => setForm({ ...form, moneda: e.target.value })}>
            <option>ARS</option><option>USD</option>
          </select>
        </label>
        <button className="btn btn-primario">Registrar</button>
      </form>

      {datos.movimientos.length > 0 && (
        <div className="tabla-scroll">
          <table className="tabla">
            <thead><tr><th>Fecha</th><th>Instrumento</th><th>Nombre</th><th>Tipo</th><th className="num">Importe</th><th /></tr></thead>
            <tbody>
              {[...datos.movimientos].reverse().map((m) => (
                <tr key={m.id}>
                  <td>{fecha(m.fecha)}</td><td>{m.instrumento}</td><td>{m.nombre}</td><td>{TIPOS[m.tipo]}</td>
                  <td className="num">{m.moneda} {importe(Number(m.importe))}</td>
                  <td><button type="button" className="link peligro" onClick={() => void borrar(m.id)}>Borrar</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
