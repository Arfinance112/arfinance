import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { fecha, importe, moneda } from "../formato";
import type { Item, Merma, StockItem } from "../types/app";

const COTIZACIONES = ["ARS", "USD_OFICIAL", "USD_MEP", "USD_CCL", "USD_BLUE", "USDT", "EUR_OFICIAL", "BRL_OFICIAL"];
const vacio: Item = { codigo: "", descripcion: "", tipo: "Bien", unidad_negocio: "GENERAL", precio_lista: 0, cotizacion_precio: "ARS",
  costo_estandar: 0, cotizacion_costo: "ARS", alicuota_iva: 0.21 };
const hoy = () => new Date().toISOString().slice(0, 10);

/** Maestro de productos y servicios con costo estándar, y registro de mermas por causa. */
export function Items({ clienteId }: { clienteId: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [sinAlta, setSinAlta] = useState<string[]>([]);
  const [stock, setStock] = useState<Record<string, StockItem>>({});
  const [edicion, setEdicion] = useState<Item>(vacio);
  const [mermas, setMermas] = useState<{ causas: string[]; mermas: Merma[]; por_causa: Record<string, number> } | null>(null);
  const [merma, setMerma] = useState({ fecha: hoy(), item: "", cantidad: "", causa: "", turno: "" });
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  const cargar = async () => {
    const r = await api.items(clienteId);
    setItems(r.items);
    setSinAlta(r.vendidos_sin_alta);
    setStock(r.stock ?? {});
    setMermas(await api.mermas(clienteId));
  };
  useEffect(() => {
    void cargar();
  }, [clienteId]);

  async function guardar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.guardarItem(clienteId, edicion);
      setMensaje({ ok: true, texto: `Ítem ${edicion.codigo.toUpperCase()} guardado.` });
      setEdicion(vacio);
      await cargar();
    } catch (err) {
      setMensaje({ ok: false, texto: mensajeDeError(err) });
    }
  }

  async function registrar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.registrarMerma(clienteId, { ...merma, cantidad: Number(merma.cantidad.replace(",", ".")) });
      setMerma({ ...merma, cantidad: "", turno: "" });
      setMensaje({ ok: true, texto: "Merma registrada." });
      await cargar();
    } catch (err) {
      setMensaje({ ok: false, texto: mensajeDeError(err) });
    }
  }

  const campo = <K extends keyof Item>(k: K, v: Item[K]) => setEdicion({ ...edicion, [k]: v });

  return (
    <div className="pila">
      {sinAlta.length > 0 && (
        <div className="avisos">
          Se vendieron códigos que no están en el maestro, así que todavía no tienen costo:{" "}
          {sinAlta.map((c) => (
            <button key={c} type="button" className="link" onClick={() => setEdicion({ ...vacio, codigo: c })}>{c}</button>
          )).reduce<React.ReactNode[]>((a, b, i) => (i ? [...a, ", ", b] : [b]), [])}
          . Hacé clic para darlos de alta.
        </div>
      )}
      <p role="status" aria-live="polite" className={mensaje?.ok ? "mensaje ok" : "error"}>{mensaje?.texto}</p>

      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Código</th><th>Descripción</th><th>Tipo</th><th>Unidad de negocio</th><th className="num">Precio de lista</th><th className="num">Costo estándar</th><th /></tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={7} className="vacio">Cargá los productos y servicios con su costo estándar (sin IVA).</td></tr>}
            {items.map((i) => (
              <tr key={i.codigo}>
                <td><strong>{i.codigo}</strong></td><td>{i.descripcion}</td><td>{i.tipo}</td><td>{i.unidad_negocio}</td>
                <td className="num">{moneda(i.cotizacion_precio)} {importe(Number(i.precio_lista))}</td>
                <td className="num">{moneda(i.cotizacion_costo)} {importe(Number(i.costo_estandar))}</td>
                <td><button type="button" className="link" onClick={() => setEdicion({ ...i })}>Editar</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Stock teórico y costo real</h3>
      <p className="sub">Sale del detalle de compras por ítem (subilo en Documentos: mismas columnas que el de ventas más
        "Proveedor"), menos lo vendido y las mermas. El costo real es el promedio ponderado de lo comprado; se marca
        si se aparta más de un 10 % del estándar. Estas compras no se suman al resultado: ya entran por Mis Comprobantes.</p>
      <div className="tabla-scroll">
        <table className="tabla">
          <thead>
            <tr><th>Código</th><th className="num">Comprado</th><th className="num">Vendido</th><th className="num">Mermas</th>
              <th className="num">Stock teórico</th><th className="num">Costo real ARS</th><th className="num">Estándar ARS</th><th className="num">Desvío</th></tr>
          </thead>
          <tbody>
            {Object.keys(stock).length === 0 && <tr><td colSpan={8} className="vacio">Todavía no hay compras ni ventas por ítem cargadas.</td></tr>}
            {Object.entries(stock).map(([cod, s]) => (
              <tr key={cod}>
                <td><strong>{cod}</strong>{!items.some((i) => i.codigo === cod) && <span className="chip">sin alta</span>}</td>
                <td className="num">{importe(Number(s.comprado))}</td>
                <td className="num">{importe(Number(s.vendido))}</td>
                <td className="num">{importe(Number(s.mermas))}</td>
                <td className={`num${Number(s.stock_teorico) < 0 ? " negativo" : ""}`}>{importe(Number(s.stock_teorico))}</td>
                <td className="num">{s.costo_real == null ? "–" : importe(Number(s.costo_real))}</td>
                <td className="num">{s.costo_estandar_ars == null ? "–" : importe(Number(s.costo_estandar_ars))}</td>
                <td className={`num${s.alerta ? " negativo" : ""}`}>
                  {s.desvio == null ? "–" : `${(Number(s.desvio) * 100).toFixed(1)} %`}{s.alerta && " ⚠"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="tarjeta formulario-grilla" onSubmit={guardar}>
        <h3>{items.some((i) => i.codigo === edicion.codigo) ? `Editar ${edicion.codigo}` : "Nuevo ítem"}</h3>
        <label>Código<input required value={edicion.codigo} onChange={(e) => campo("codigo", e.target.value.toUpperCase())} /></label>
        <label>Descripción<input required value={edicion.descripcion} onChange={(e) => campo("descripcion", e.target.value)} /></label>
        <label>Tipo
          <select value={edicion.tipo} onChange={(e) => campo("tipo", e.target.value as Item["tipo"])}>
            <option>Bien</option><option>Servicio</option>
          </select>
        </label>
        <label>Unidad de negocio<input required value={edicion.unidad_negocio} onChange={(e) => campo("unidad_negocio", e.target.value)} /></label>
        <label>Precio de lista<input type="number" step="0.01" min="0" value={edicion.precio_lista} onChange={(e) => campo("precio_lista", Number(e.target.value))} /></label>
        <label>Moneda del precio
          <select value={edicion.cotizacion_precio} onChange={(e) => campo("cotizacion_precio", e.target.value)}>{COTIZACIONES.map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <label>Costo estándar (sin IVA)<input type="number" step="0.01" min="0" value={edicion.costo_estandar} onChange={(e) => campo("costo_estandar", Number(e.target.value))} /></label>
        <label>Moneda del costo
          <select value={edicion.cotizacion_costo} onChange={(e) => campo("cotizacion_costo", e.target.value)}>{COTIZACIONES.map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <div className="acciones">
          <button className="btn btn-primario">Guardar ítem</button>
          <span className="sub">Si el costo está en dólares, se pasa a pesos con el tipo de cambio del mes de cada venta.</span>
        </div>
      </form>

      <section className="pila">
        <h2>Mermas y desperdicios</h2>
        {mermas && Object.keys(mermas.por_causa).length > 0 && (
          <div className="grilla-tarjetas">
            {Object.entries(mermas.por_causa).map(([causa, valor]) => (
              <div key={causa} className="tarjeta kpi"><span>{causa}</span><strong>ARS {importe(Number(valor))}</strong></div>
            ))}
          </div>
        )}
        <form className="tarjeta formulario-grilla" onSubmit={registrar}>
          <h3>Registrar merma</h3>
          <label>Fecha<input type="date" required value={merma.fecha} onChange={(e) => setMerma({ ...merma, fecha: e.target.value })} /></label>
          <label>Ítem
            <select required value={merma.item} onChange={(e) => setMerma({ ...merma, item: e.target.value })}>
              <option value="">— elegir —</option>
              {items.map((i) => <option key={i.codigo} value={i.codigo}>{i.codigo} · {i.descripcion}</option>)}
            </select>
          </label>
          <label>Cantidad<input required inputMode="decimal" value={merma.cantidad} onChange={(e) => setMerma({ ...merma, cantidad: e.target.value })} /></label>
          <label>Causa
            <select required value={merma.causa} onChange={(e) => setMerma({ ...merma, causa: e.target.value })}>
              <option value="">— elegir —</option>
              {mermas?.causas.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Turno / lote<input value={merma.turno} onChange={(e) => setMerma({ ...merma, turno: e.target.value })} /></label>
          <div className="acciones"><button className="btn btn-primario">Registrar</button></div>
        </form>
        {mermas && mermas.mermas.length > 0 && (
          <div className="tabla-scroll">
            <table className="tabla">
              <thead><tr><th>Fecha</th><th>Ítem</th><th className="num">Cantidad</th><th>Causa</th><th>Turno / lote</th></tr></thead>
              <tbody>
                {[...mermas.mermas].reverse().map((m) => (
                  <tr key={m.id}><td>{fecha(m.fecha)}</td><td>{m.item}</td><td className="num">{Number(m.cantidad)}</td><td>{m.causa}</td><td>{m.turno}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
