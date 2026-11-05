import type { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

import { api } from "./api/client";
import { escucharSesion, llegoParaElegirClave, modoDesarrollo, salir } from "./auth/sesion";
import { ImpListo } from "./features/conciliacion/ImpListo";
import { AltaCliente } from "./pantallas/AltaCliente";
import { Clientes } from "./pantallas/Clientes";
import { Comprobantes } from "./pantallas/Comprobantes";
import { Control } from "./pantallas/Control";
import { Presupuesto } from "./pantallas/Presupuesto";
import { Indices } from "./pantallas/Indices";
import { Items } from "./pantallas/Items";
import { Rentabilidad } from "./pantallas/Rentabilidad";
import { Resultados } from "./pantallas/Resultados";
import { Cuentas } from "./pantallas/Cuentas";
import { Documentos } from "./pantallas/Documentos";
import { Flujo } from "./pantallas/Flujo";
import { ElegirClave, Ingreso } from "./pantallas/Ingreso";
import { Tablero } from "./pantallas/Tablero";
import { Tesoreria } from "./pantallas/Tesoreria";
import { useRuta } from "./router";

const SECCIONES = [
  { clave: "tablero", texto: "Tablero" },
  { clave: "documentos", texto: "Documentos" },
  { clave: "comprobantes", texto: "Comprobantes" },
  { clave: "items", texto: "Ítems y mermas" },
  { clave: "cuentas", texto: "Cuentas" },
  { clave: "tesoreria", texto: "Tesorería" },
  { clave: "flujo", texto: "Flujo de caja" },
  { clave: "resultados", texto: "Resultados" },
  { clave: "rentabilidad", texto: "Rentabilidad" },
  { clave: "presupuesto", texto: "Presupuesto" },
  { clave: "control", texto: "Control" },
] as const;

const BANDA: Record<string, [string, string]> = {
  clientes: ["Tus clientes", "Cada carpeta tiene sus cuentas, documentos y tableros."],
  tablero: ["Tablero", "Los indicadores del mes contra la meta, el mes anterior y el presupuesto, y la caja a 90 días."],
  documentos: ["Documentos", "Subí extractos, F.931 y comprobantes. Los extractos quedan listos para conciliar."],
  cuentas: ["Cuentas", "Bancos, billeteras, cajas, procesadores y tarjetas del cliente, con su moneda."],
  tesoreria: ["Tesorería", "Saldos por cuenta y moneda, y todos los movimientos aprobados."],
  flujo: ["Flujo de caja", "Lo que entró y salió cada mes, por concepto."],
  comprobantes: ["Comprobantes", "Ventas y compras de Mis Comprobantes. Clasificá cada proveedor una sola vez."],
  resultados: ["Resultados", "Estado de resultados de gestión: margen de contribución, EBITDA y prime cost."],
  items: ["Ítems y mermas", "Productos y servicios con su costo estándar, y las pérdidas por causa."],
  rentabilidad: ["Rentabilidad", "Qué unidad de negocio y qué ítem gana o pierde, y cuánto hay que vender para no perder."],
  presupuesto: ["Presupuesto", "Base a precios de enero; cada mes se actualiza solo con el índice de su rubro."],
  control: ["Control presupuestario", "Real contra presupuesto, con semáforo y la explicación de cada desvío."],
  alta: ["Nuevo cliente", "Desde tu Planilla de Gestión Integral v2 o desde cero, en pocos pasos."],
  indices: ["Índices y tipos de cambio", "IPC y cotizaciones de cada mes, comunes a todos los clientes."],
  lote: ["Conciliación de extractos", "Revisá lo que trajo el extracto, resolvé las alertas y pasalo a Tesorería."],
};

export default function App() {
  const ruta = useRuta();
  const [sesion, setSesion] = useState<Session | null | undefined>(modoDesarrollo ? null : undefined);
  const [nombreCliente, setNombreCliente] = useState("");
  const clienteId = ruta.pantalla === "cliente" || ruta.pantalla === "lote" ? ruta.clienteId : null;

  const [eligiendoClave, setEligiendoClave] = useState(llegoParaElegirClave);
  useEffect(() => escucharSesion((s, recuperando) => {
    setSesion(s);
    if (recuperando) setEligiendoClave(true);
  }), []);
  useEffect(() => {
    setNombreCliente("");
    if (clienteId) void api.cliente(clienteId).then((c) => setNombreCliente(c.nombre)).catch(() => setNombreCliente(""));
  }, [clienteId]);

  if (!modoDesarrollo && sesion === undefined) return null;
  if (!modoDesarrollo && !sesion) return <Ingreso />;
  if (!modoDesarrollo && eligiendoClave) return <ElegirClave alTerminar={() => { setEligiendoClave(false); window.location.hash = "#/clientes"; }} />;

  const claveBanda = ruta.pantalla === "cliente" ? ruta.seccion : ruta.pantalla;
  const [titulo, bajada] = BANDA[claveBanda];

  return (
    <>
      <header className="app-header">
        <a className="app-marca" href="#/clientes">AR<span>Finance</span></a>
        {clienteId && (
          <nav className="migas" aria-label="Ubicación">
            <a href="#/clientes">Clientes</a> <span aria-hidden>›</span> <span>{nombreCliente || "…"}</span>
          </nav>
        )}
        <div className="app-header-fin">
          <a className="link" href="#/indices" aria-current={ruta.pantalla === "indices" ? "page" : undefined}>Índices</a>
          {modoDesarrollo ? <span className="chip">modo desarrollo</span> : (
            <>
              <span className="sub">{sesion?.user.email}</span>
              <button className="btn btn-secundario btn-chico" onClick={() => void salir()}>Salir</button>
            </>
          )}
        </div>
      </header>

      <section className="app-banda">
        <h1>{clienteId && nombreCliente ? `${titulo} · ${nombreCliente}` : titulo}</h1>
        <p>{bajada}</p>
      </section>

      {clienteId && (
        <nav className="pestanas" aria-label="Secciones del cliente">
          {SECCIONES.map((s) => (
            <a key={s.clave} href={`#/clientes/${clienteId}/${s.clave}`}
              aria-current={ruta.pantalla === "cliente" && ruta.seccion === s.clave ? "page" : undefined}>
              {s.texto}
            </a>
          ))}
        </nav>
      )}

      <main className="app-contenido">
        {ruta.pantalla === "clientes" && <Clientes />}
        {ruta.pantalla === "indices" && <Indices />}
        {ruta.pantalla === "alta" && <AltaCliente />}
        {ruta.pantalla === "cliente" && ruta.seccion === "tablero" && <Tablero clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "comprobantes" && <Comprobantes clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "resultados" && <Resultados clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "items" && <Items clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "rentabilidad" && <Rentabilidad clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "presupuesto" && <Presupuesto clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "control" && <Control clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "documentos" && <Documentos clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "cuentas" && <Cuentas clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "tesoreria" && <Tesoreria clienteId={ruta.clienteId} />}
        {ruta.pantalla === "cliente" && ruta.seccion === "flujo" && <Flujo clienteId={ruta.clienteId} />}
        {ruta.pantalla === "lote" && (
          <>
            <a className="link volver" href={`#/clientes/${ruta.clienteId}/documentos`}>‹ Volver a documentos</a>
            <ImpListo loteId={ruta.loteId} />
          </>
        )}
      </main>
    </>
  );
}
