import { useEffect, useMemo, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { fecha, importe } from "../formato";
import type { Comprobante } from "../types/app";
import type { Rubro } from "../types/conciliacion";

/** Comprobantes de ARCA. Las compras sin rubro se asignan por proveedor: una vez y para siempre. */
export function Comprobantes({ clienteId }: { clienteId: string }) {
  const [comps, setComps] = useState<Comprobante[]>([]);
  const [rubros, setRubros] = useState<Rubro[]>([]);
  const [sentido, setSentido] = useState<"recibido" | "emitido">("recibido");
  const [soloSinRubro, setSoloSinRubro] = useState(true);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const cargar = () => api.comprobantes(clienteId, sentido, sentido === "recibido" && soloSinRubro).then(setComps);
  useEffect(() => {
    void cargar();
  }, [clienteId, sentido, soloSinRubro]);
  useEffect(() => {
    void api.rubros().then((r) => setRubros(r.filter((x) => x.linea_pl !== "NO P&L" || x.codigo.startsWith("INV"))));
  }, []);

  const [buscar, setBuscar] = useState("");
  // busca en proveedor/cliente, CUIT, número de comprobante y rubro, sin distinguir mayúsculas ni acentos
  const sinAcentos = (t: string) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  const visibles = useMemo(() => {
    const q = sinAcentos(buscar.trim());
    return q ? comps.filter((c) => sinAcentos(`${c.contraparte} ${c.cuit} ${c.comprobante} ${c.rubro ?? ""}`).includes(q)) : comps;
  }, [comps, buscar]);
  const total = useMemo(() => visibles.reduce((s, c) => s + Number(c.neto_ars), 0), [visibles]);

  async function asignar(c: Comprobante, rubro: string) {
    try {
      const r = await api.asignarRubro(clienteId, c.id, rubro);
      setMensaje(r.actualizados > 1
        ? `${c.contraparte}: rubro asignado a ${r.actualizados} comprobantes y recordado para los próximos.`
        : `${c.contraparte}: rubro asignado y recordado para los próximos.`);
      await cargar();
    } catch (e) {
      setMensaje(mensajeDeError(e));
    }
  }

  return (
    <div className="pila">
      <div className="formulario-linea">
        <nav className="filtros" aria-label="Tipo de comprobante">
          <button type="button" aria-pressed={sentido === "recibido"} onClick={() => setSentido("recibido")}>Recibidos (compras)</button>
          <button type="button" aria-pressed={sentido === "emitido"} onClick={() => setSentido("emitido")}>Emitidos (ventas)</button>
        </nav>
        {sentido === "recibido" && (
          <label className="check">
            <input type="checkbox" checked={soloSinRubro} onChange={(e) => setSoloSinRubro(e.target.checked)} />
            Solo los que falta clasificar
          </label>
        )}
        <label>
          Buscar
          <input type="search" value={buscar} onChange={(e) => setBuscar(e.target.value)}
            placeholder={sentido === "recibido" ? "Proveedor, CUIT, número o rubro" : "Cliente, CUIT o número"} />
        </label>
        <span className="sub">{visibles.length}{buscar ? ` de ${comps.length}` : ""} comprobantes · neto ARS {importe(total)}</span>
      </div>
      <p role="status" aria-live="polite" className="mensaje ok">{mensaje}</p>

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Fecha</th><th>Comprobante</th><th>{sentido === "recibido" ? "Proveedor" : "Cliente"}</th><th>CUIT</th><th className="num">Neto ARS</th>{sentido === "recibido" && <th>Rubro</th>}</tr>
          </thead>
          <tbody>
            {visibles.length === 0 && (
              <tr><td colSpan={6} className="vacio">
                {buscar ? "Ningún comprobante coincide con la búsqueda."
                  : sentido === "recibido" && soloSinRubro ? "Todas las compras están clasificadas." : "No hay comprobantes. Subí Mis Comprobantes en Documentos."}
              </td></tr>
            )}
            {visibles.map((c) => (
              <tr key={c.id}>
                <td>{fecha(c.fecha)}</td>
                <td>{c.comprobante}</td>
                <td>{c.contraparte}</td>
                <td>{c.cuit}</td>
                <td className={`num${Number(c.neto_ars) < 0 ? " negativo" : ""}`}>{importe(Number(c.neto_ars))}</td>
                {sentido === "recibido" && (
                  <td>
                    <select aria-label={`Rubro de ${c.contraparte}`} value={c.rubro ?? ""} onChange={(e) => e.target.value && void asignar(c, e.target.value)}>
                      <option value="">— elegir —</option>
                      {rubros.map((r) => <option key={r.codigo} value={r.codigo}>{r.codigo} · {r.nombre}</option>)}
                    </select>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
