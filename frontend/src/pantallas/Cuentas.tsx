import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { importe, moneda } from "../formato";
import type { Cuenta, Perfil } from "../types/app";

const TIPOS = [
  "Banco - Cuenta corriente", "Banco - Caja de ahorro", "Billetera virtual / PSP (CVU)", "Caja física (efectivo)",
  "Procesador de pagos (a liquidar)", "Broker / ALyC", "Exchange cripto", "Plazo fijo / FCI",
  "Valores a depositar (cheques / eCheq)", "Tarjeta de crédito (pasivo)",
];
const COTIZACIONES = ["ARS", "USD_OFICIAL", "USD_MEP", "USD_CCL", "USD_BLUE", "USDT", "EUR_OFICIAL", "BRL_OFICIAL"];

const vacia = { codigo: "", nombre: "", tipo: TIPOS[0], cotizacion: "ARS", saldo_inicial: 0, perfil_defecto: "" };

export function Cuentas({ clienteId }: { clienteId: string }) {
  const [cuentas, setCuentas] = useState<Cuenta[]>([]);
  const [perfiles, setPerfiles] = useState<Perfil[]>([]);
  const [nueva, setNueva] = useState(vacia);
  const [error, setError] = useState<string | null>(null);

  const cargar = () => api.cuentas(clienteId).then(setCuentas);
  useEffect(() => {
    void cargar();
    void api.perfiles().then(setPerfiles);
  }, [clienteId]);

  async function guardar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.crearCuenta(clienteId, { ...nueva, perfil_defecto: nueva.perfil_defecto || null });
      setNueva({ ...vacia, codigo: `CTA${String(cuentas.length + 2).padStart(2, "0")}` });
      setError(null);
      await cargar();
    } catch (err) {
      setError(mensajeDeError(err));
    }
  }

  return (
    <div className="pila">
      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Código</th><th>Cuenta</th><th>Tipo</th><th>Moneda / cotización</th><th className="num">Saldo inicial</th><th>Perfil de extracto</th></tr>
          </thead>
          <tbody>
            {cuentas.length === 0 && (
              <tr><td colSpan={6} className="vacio">Cargá las cuentas del cliente: bancos, billeteras, cajas, tarjetas. Son el destino de los extractos.</td></tr>
            )}
            {cuentas.map((c) => (
              <tr key={c.codigo}>
                <td>{c.codigo}</td><td>{c.nombre}</td><td>{c.tipo}</td><td>{c.cotizacion}</td>
                <td className="num">{moneda(c.cotizacion)} {importe(Number(c.saldo_inicial))}</td>
                <td>{perfiles.find((p) => p.codigo === c.perfil_defecto)?.nombre ?? "Automático"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="tarjeta formulario-grilla" onSubmit={guardar}>
        <h3>Nueva cuenta</h3>
        <label>Código<input required value={nueva.codigo} placeholder="CTA01" onChange={(e) => setNueva({ ...nueva, codigo: e.target.value.toUpperCase() })} /></label>
        <label>Nombre<input required value={nueva.nombre} placeholder="Galicia CC $" onChange={(e) => setNueva({ ...nueva, nombre: e.target.value })} /></label>
        <label>Tipo
          <select value={nueva.tipo} onChange={(e) => setNueva({ ...nueva, tipo: e.target.value })}>
            {TIPOS.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Moneda / cotización
          <select value={nueva.cotizacion} onChange={(e) => setNueva({ ...nueva, cotizacion: e.target.value })}>
            {COTIZACIONES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Saldo inicial
          <input type="number" step="0.01" value={nueva.saldo_inicial} onChange={(e) => setNueva({ ...nueva, saldo_inicial: Number(e.target.value) })} />
        </label>
        <label>Perfil de extracto
          <select value={nueva.perfil_defecto} onChange={(e) => setNueva({ ...nueva, perfil_defecto: e.target.value })}>
            <option value="">Detectar automáticamente</option>
            {perfiles.map((p) => <option key={p.codigo} value={p.codigo}>{p.nombre}</option>)}
          </select>
        </label>
        <div className="acciones">
          <button className="btn btn-primario">Agregar cuenta</button>
          {error && <span className="error" role="alert">{error}</span>}
        </div>
      </form>
    </div>
  );
}
