import { useState } from "react";

import { api, mensajeDeError } from "../api/client";
import type { ImportacionPlanilla } from "../types/app";

/** CUIT/CUIL: dígito verificador módulo 11 (solo aviso: hay CUIT de prueba en planillas de ejemplo). */
export function cuitValido(cuit: string): boolean {
  const d = cuit.replace(/\D/g, "");
  if (d.length !== 11) return false;
  const pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
  const resto = pesos.reduce((s, p, i) => s + p * Number(d[i]), 0) % 11;
  const verificador = resto === 0 ? 0 : resto === 1 ? 9 : 11 - resto;
  return verificador === Number(d[10]);
}

const CUENTAS_HABITUALES = [
  { nombre: "Banco cuenta corriente $", tipo: "Banco - Cuenta corriente", cotizacion: "ARS" },
  { nombre: "Banco caja de ahorro $", tipo: "Banco - Caja de ahorro", cotizacion: "ARS" },
  { nombre: "Banco caja de ahorro USD", tipo: "Banco - Caja de ahorro", cotizacion: "USD_OFICIAL" },
  { nombre: "Mercado Pago", tipo: "Billetera virtual / PSP (CVU)", cotizacion: "ARS" },
  { nombre: "Caja efectivo", tipo: "Caja física (efectivo)", cotizacion: "ARS" },
  { nombre: "Tarjeta de crédito empresa", tipo: "Tarjeta de crédito (pasivo)", cotizacion: "ARS" },
];

const ROTULOS: [keyof ImportacionPlanilla, string][] = [
  ["cuentas", "Cuentas"], ["tesoreria", "Movimientos de tesorería"], ["ventas", "Comprobantes de venta"],
  ["renglones_venta", "Renglones por ítem"], ["compras", "Comprobantes de compra"], ["items", "Ítems"],
  ["meses_personal", "Meses de personal"], ["mermas", "Mermas"], ["reglas", "Reglas (las propias)"],
  ["celdas_presupuesto", "Celdas de presupuesto"], ["cierres", "Cierres de balance"], ["metas", "Metas del tablero"],
  ["meses_indices", "Meses de índices"],
];

type Paso = "inicio" | "planilla" | "datos" | "cuentas" | "listo";

/** Asistente de alta de un cliente: desde la planilla v2 o desde cero. */
export function AltaCliente() {
  const [paso, setPaso] = useState<Paso>("inicio");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  // planilla
  const [archivo, setArchivo] = useState<File | null>(null);
  const [omitirEjemplos, setOmitirEjemplos] = useState(true);
  const [importarIndices, setImportarIndices] = useState(false);
  const [previa, setPrevia] = useState<ImportacionPlanilla | null>(null);
  // desde cero
  const [nombre, setNombre] = useState("");
  const [cuit, setCuit] = useState("");
  const [clienteId, setClienteId] = useState<string | null>(null);
  const [cuentas, setCuentas] = useState<string[]>([]);

  const correr = async (f: () => Promise<void>) => {
    setError(null);
    setOcupado(true);
    try { await f(); } catch (e) { setError(mensajeDeError(e)); } finally { setOcupado(false); }
  };

  const verPrevia = (f: File | null, omitir: boolean) => {
    setArchivo(f);
    setPrevia(null);
    if (f) void correr(async () => setPrevia(await api.importarPlanilla(f, { simular: true, omitirEjemplos: omitir, importarIndices })));
  };

  const confirmarPlanilla = () => correr(async () => {
    if (!archivo) return;
    const r = await api.importarPlanilla(archivo, { simular: false, omitirEjemplos, importarIndices });
    window.location.hash = `#/clientes/${r.cliente_id}/tablero`;
  });

  const crearCliente = (e: React.FormEvent) => {
    e.preventDefault();
    void correr(async () => {
      const c = await api.crearCliente(nombre.trim(), cuit.trim());
      setClienteId(c.id);
      setPaso("cuentas");
    });
  };

  const agregarCuenta = (i: number) => correr(async () => {
    if (!clienteId) return;
    const base = CUENTAS_HABITUALES[i];
    const codigo = `CTA${String(cuentas.length + 1).padStart(2, "0")}`;
    await api.crearCuenta(clienteId, { codigo, ...base, saldo_inicial: 0, perfil_defecto: null });
    setCuentas([...cuentas, `${codigo} · ${base.nombre}`]);
  });

  return (
    <div className="pila alta">
      <ol className="pasos" aria-label="Pasos del alta">
        {(paso === "planilla" ? ["Cómo empezar", "Planilla"] : ["Cómo empezar", "Datos", "Cuentas", "Listo"]).map((t, i) => {
          const actual = paso === "planilla" ? 1 : { inicio: 0, datos: 1, cuentas: 2, listo: 3, planilla: 1 }[paso];
          return <li key={t} className={i === actual ? "actual" : i < actual ? "hecho" : undefined}>{t}</li>;
        })}
      </ol>

      {paso === "inicio" && (
        <div className="grilla-tarjetas">
          <button className="tarjeta opcion" onClick={() => setPaso("planilla")}>
            <strong>Ya uso la Planilla de Gestión Integral v2</strong>
            <span>Subila y traemos cuentas, tesorería, ventas, compras, personal, ítems, presupuesto, cierres y metas. Primero ves qué encontramos.</span>
          </button>
          <button className="tarjeta opcion" onClick={() => setPaso("datos")}>
            <strong>Empezar de cero</strong>
            <span>Razón social, CUIT y las cuentas del cliente. Después subís extractos, Mis Comprobantes y F.931.</span>
          </button>
        </div>
      )}

      {paso === "planilla" && (
        <div className="tarjeta pila">
          <label className="campo-archivo">Planilla (.xlsx)
            <input type="file" accept=".xlsx,.xlsm" onChange={(e) => verPrevia(e.target.files?.[0] ?? null, omitirEjemplos)} />
          </label>
          <label className="check"><input type="checkbox" checked={omitirEjemplos}
            onChange={(e) => { setOmitirEjemplos(e.target.checked); verPrevia(archivo, e.target.checked); }} />
            Omitir las filas de ejemplo de la plantilla (Observaciones con «EJEMPLO»)</label>
          <label className="check"><input type="checkbox" checked={importarIndices} onChange={(e) => setImportarIndices(e.target.checked)} />
            Importar índices y tipos de cambio (son comunes a todos los clientes; solo se agregan meses que falten)</label>
          {ocupado && <p className="cargando">Leyendo la planilla…</p>}
          {previa && (
            <>
              <h3>{previa.empresa || "Sin nombre en CONFIG"} <span className="sub">{previa.cuit}</span></h3>
              <dl className="resumen-importacion">
                {ROTULOS.map(([k, t]) => <div key={k}><dt>{t}</dt><dd>{Number(previa[k]).toLocaleString("es-AR")}</dd></div>)}
              </dl>
              {previa.avisos.length > 0 && <ul className="avisos">{previa.avisos.map((a) => <li key={a}>{a}</li>)}</ul>}
              <div className="acciones">
                <button className="btn btn-primario" disabled={ocupado} onClick={() => void confirmarPlanilla()}>Crear el cliente con estos datos</button>
                <button className="btn btn-secundario" onClick={() => setPaso("inicio")}>Volver</button>
              </div>
            </>
          )}
        </div>
      )}

      {paso === "datos" && (
        <form className="tarjeta formulario-grilla" onSubmit={crearCliente}>
          <label>Razón social<input required minLength={2} value={nombre} onChange={(e) => setNombre(e.target.value)} autoFocus /></label>
          <label>CUIT<input value={cuit} placeholder="30-12345678-9" onChange={(e) => setCuit(e.target.value)} />
            {cuit && !cuitValido(cuit) && <small className="aviso-campo">El dígito verificador no coincide: revisalo.</small>}
          </label>
          <div className="acciones">
            <button className="btn btn-primario" disabled={ocupado}>Crear y seguir</button>
            <button type="button" className="btn btn-secundario" onClick={() => setPaso("inicio")}>Volver</button>
          </div>
        </form>
      )}

      {paso === "cuentas" && (
        <div className="tarjeta pila">
          <p>Agregá las cuentas habituales con un clic (después podés editarlas o sumar otras en <strong>Cuentas</strong>).</p>
          <div className="chips">
            {CUENTAS_HABITUALES.map((c, i) => (
              <button key={c.nombre} className="btn btn-secundario btn-chico" disabled={ocupado} onClick={() => void agregarCuenta(i)}>+ {c.nombre}</button>
            ))}
          </div>
          {cuentas.length > 0 && <ul>{cuentas.map((c) => <li key={c}>{c}</li>)}</ul>}
          <div className="acciones"><button className="btn btn-primario" onClick={() => setPaso("listo")}>Seguir</button></div>
        </div>
      )}

      {paso === "listo" && clienteId && (
        <div className="tarjeta pila">
          <h3>Listo: {nombre} ya está creado</h3>
          <p>Para que el tablero tenga datos, en este orden:</p>
          <ol className="proximos">
            <li><a className="link" href={`#/clientes/${clienteId}/documentos`}>Subí los extractos</a> de cada cuenta y conciliá.</li>
            <li><a className="link" href={`#/clientes/${clienteId}/documentos`}>Subí Mis Comprobantes</a> emitidos y recibidos (ARCA) y el F.931.</li>
            <li><a className="link" href={`#/clientes/${clienteId}/comprobantes`}>Asigná rubro</a> a cada proveedor nuevo (una sola vez).</li>
            <li><a className="link" href={`#/clientes/${clienteId}/items`}>Cargá los ítems</a> con su costo si vende productos.</li>
            <li><a className="link" href={`#/clientes/${clienteId}/presupuesto`}>Generá el presupuesto</a> desde lo real.</li>
          </ol>
          <div className="acciones"><a className="btn btn-primario" href={`#/clientes/${clienteId}/documentos`}>Ir a Documentos</a></div>
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
