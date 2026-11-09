// Enrutador mínimo por hash (#/clientes/123/documentos). Sin dependencias: alcanza para la fase 1b.
import { useEffect, useState } from "react";

export const SECCIONES_CLIENTE = [
  "tablero", "documentos", "comprobantes", "plan", "items", "cuentas", "tesoreria", "flujo", "resultados", "rentabilidad", "presupuesto", "control",
] as const;
export type Seccion = (typeof SECCIONES_CLIENTE)[number];

export type Ruta =
  | { pantalla: "clientes" }
  | { pantalla: "indices" }
  | { pantalla: "alta" }
  | { pantalla: "usuarios" }
  | { pantalla: "cliente"; clienteId: string; seccion: Seccion }
  | { pantalla: "lote"; clienteId: string; loteId: string };

export function leerRuta(hash: string): Ruta {
  const p = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (p[0] === "indices") return { pantalla: "indices" };
  if (p[0] === "alta") return { pantalla: "alta" };
  if (p[0] === "usuarios") return { pantalla: "usuarios" };
  if (p[0] === "clientes" && p[1]) {
    if (p[2] === "lotes" && p[3]) return { pantalla: "lote", clienteId: p[1], loteId: p[3] };
    const seccion = SECCIONES_CLIENTE.find((s) => s === p[2]) ?? "documentos";
    return { pantalla: "cliente", clienteId: p[1], seccion };
  }
  return { pantalla: "clientes" };
}

export const ir = (ruta: string) => {
  window.location.hash = ruta;
};

export function useRuta(): Ruta {
  const [ruta, setRuta] = useState(() => leerRuta(window.location.hash));
  useEffect(() => {
    const alCambiar = () => setRuta(leerRuta(window.location.hash));
    window.addEventListener("hashchange", alCambiar);
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);
  return ruta;
}
