import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { fecha, importe, moneda } from "../formato";
import type { MovimientoTesoreria, Saldo } from "../types/app";

/** Saldos por cuenta y moneda + grilla de Tesorería con filtros. */
export function Tesoreria({ clienteId }: { clienteId: string }) {
  const [saldos, setSaldos] = useState<Saldo[]>([]);
  const [movs, setMovs] = useState<MovimientoTesoreria[]>([]);
  const [cuenta, setCuenta] = useState("");
  const [buscar, setBuscar] = useState("");
  const [rubro, setRubro] = useState("");
  const [tipo, setTipo] = useState("");
  const [nombres, setNombres] = useState<Record<string, string>>({});

  useEffect(() => {
    void api.saldos(clienteId).then(setSaldos);
    void api.tesoreria(clienteId).then(setMovs);
    void api.rubros().then((r) => setNombres(Object.fromEntries(r.map((x) => [x.codigo, x.nombre]))));
  }, [clienteId]);

  // solo los rubros que aparecen en los movimientos, para no llenar la lista de opciones vacías
  const rubrosUsados = useMemo(() => [...new Set(movs.map((m) => m.rubro))].sort(), [movs]);

  const porMoneda = useMemo(() => {
    const t = new Map<string, number>();
    saldos.forEach((s) => t.set(moneda(s.cotizacion), (t.get(moneda(s.cotizacion)) ?? 0) + Number(s.saldo)));
    return [...t.entries()];
  }, [saldos]);

  const visibles = useMemo(() => {
    const q = buscar.trim().toUpperCase();
    return movs
      .filter((m) => (!cuenta || m.cuenta === cuenta) && (!rubro || m.rubro === rubro) && (!tipo || m.tipo === tipo)
        && (!q || `${m.descripcion} ${m.rubro} ${nombres[m.rubro] ?? ""} ${m.comprobante ?? ""}`.toUpperCase().includes(q)))
      .sort((a, b) => b.fecha.localeCompare(a.fecha));
  }, [movs, cuenta, rubro, tipo, buscar, nombres]);
  const totales = useMemo(() => visibles.reduce((t, m) => {
    if (m.tipo === "Ingreso") t.ingresos += Number(m.importe); else t.egresos += Number(m.importe);
    return t;
  }, { ingresos: 0, egresos: 0 }), [visibles]);

  const monedaDe = (codigo: string) => moneda(saldos.find((s) => s.cuenta === codigo)?.cotizacion ?? "ARS");

  return (
    <div className="pila">
      <div className="grilla-tarjetas">
        {porMoneda.map(([mon, total]) => (
          <div key={mon} className="tarjeta kpi kpi-destacado">
            <span>Total en {mon}</span>
            <strong>{mon} {importe(total)}</strong>
          </div>
        ))}
        {saldos.map((s) => (
          <button key={s.cuenta} type="button" className={`tarjeta kpi${cuenta === s.cuenta ? " seleccionada" : ""}`}
            aria-pressed={cuenta === s.cuenta} onClick={() => setCuenta(cuenta === s.cuenta ? "" : s.cuenta)}>
            <span>{s.nombre}</span>
            <strong className={Number(s.saldo) < 0 ? "negativo" : undefined}>{moneda(s.cotizacion)} {importe(Number(s.saldo))}</strong>
            <small>{s.tipo}</small>
          </button>
        ))}
      </div>

      <div className="formulario-linea">
        <label>
          Buscar
          <input type="search" value={buscar} placeholder="Descripción, rubro o comprobante" onChange={(e) => setBuscar(e.target.value)} />
        </label>
        <label>
          Cuenta
          <select value={cuenta} onChange={(e) => setCuenta(e.target.value)}>
            <option value="">Todas</option>
            {saldos.map((s) => <option key={s.cuenta} value={s.cuenta}>{s.cuenta} · {s.nombre}</option>)}
          </select>
        </label>
        <label>
          Rubro
          <select value={rubro} onChange={(e) => setRubro(e.target.value)}>
            <option value="">Todos</option>
            {rubrosUsados.map((r) => <option key={r} value={r}>{r} · {nombres[r] ?? ""}</option>)}
          </select>
        </label>
        <label>
          Tipo
          <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
            <option value="">Ingresos y egresos</option>
            <option value="Ingreso">Solo ingresos</option>
            <option value="Egreso">Solo egresos</option>
          </select>
        </label>
        {(cuenta || rubro || tipo || buscar) && (
          <button type="button" className="link" onClick={() => { setCuenta(""); setRubro(""); setTipo(""); setBuscar(""); }}>Limpiar filtros</button>
        )}
        <span className="sub">{visibles.length} movimientos · ingresos {importe(totales.ingresos)} · egresos {importe(totales.egresos)}</span>
      </div>

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Fecha</th><th>Cuenta</th><th>Descripción</th><th>Rubro</th><th>Comprobante</th><th className="num">Ingreso</th><th className="num">Egreso</th></tr>
          </thead>
          <tbody>
            {visibles.length === 0 && <tr><td colSpan={7} className="vacio">Sin movimientos. Se cargan al aprobar un extracto conciliado.</td></tr>}
            {visibles.map((m) => (
              <tr key={m.id}>
                <td>{fecha(m.fecha)}</td>
                <td>{m.cuenta}</td>
                <td>{m.descripcion}</td>
                <td title={nombres[m.rubro]}>{m.rubro}{nombres[m.rubro] ? ` · ${nombres[m.rubro]}` : ""}</td>
                <td>{m.comprobante ?? ""}</td>
                <td className="num ingreso">{m.tipo === "Ingreso" ? `${monedaDe(m.cuenta)} ${importe(Number(m.importe))}` : ""}</td>
                <td className="num egreso">{m.tipo === "Egreso" ? `${monedaDe(m.cuenta)} ${importe(Number(m.importe))}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
