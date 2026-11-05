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

  useEffect(() => {
    void api.saldos(clienteId).then(setSaldos);
    void api.tesoreria(clienteId).then(setMovs);
  }, [clienteId]);

  const porMoneda = useMemo(() => {
    const t = new Map<string, number>();
    saldos.forEach((s) => t.set(moneda(s.cotizacion), (t.get(moneda(s.cotizacion)) ?? 0) + Number(s.saldo)));
    return [...t.entries()];
  }, [saldos]);

  const visibles = useMemo(() => {
    const q = buscar.trim().toUpperCase();
    return movs
      .filter((m) => (!cuenta || m.cuenta === cuenta) && (!q || `${m.descripcion} ${m.rubro} ${m.comprobante ?? ""}`.toUpperCase().includes(q)))
      .sort((a, b) => b.fecha.localeCompare(a.fecha));
  }, [movs, cuenta, buscar]);

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
        <span className="sub">{visibles.length} movimientos{cuenta ? ` en ${cuenta}` : ""}</span>
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
                <td>{m.rubro}</td>
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
