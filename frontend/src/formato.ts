const numero = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const importe = (n: number) => numero.format(n);
export const fecha = (iso: string) => iso.slice(0, 10).split("-").reverse().join("/");
export const mes = (iso: string) =>
  new Date(`${iso.slice(0, 7)}-15T12:00:00`).toLocaleDateString("es-AR", { month: "short", year: "2-digit" });
export const tamano = (b: number) => (b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`);
/** "USD_OFICIAL" → "USD"; "ARS" → "ARS". */
export const moneda = (cotizacion: string) => (!cotizacion || cotizacion === "ARS" ? "ARS" : cotizacion.split("_")[0]);
