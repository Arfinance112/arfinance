// Sesión con Supabase Auth. Sin VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY la app corre en modo
// desarrollo (sin login), igual que la API sin SUPABASE_URL ni SUPABASE_JWT_SECRET.
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const claveAnonima = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

// Los enlaces de invitación y de "olvidé mi contraseña" llegan con #access_token=…&type=invite|recovery.
// Se lee ANTES de crear el cliente: supabase-js consume ese hash al iniciar.
const tipoEnlace = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("type");
export const llegoParaElegirClave = tipoEnlace === "invite" || tipoEnlace === "recovery";

export const supabase: SupabaseClient | null = url && claveAnonima ? createClient(url, claveAnonima) : null;
export const modoDesarrollo = supabase === null;

export async function tokenActual(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function ingresar(email: string, clave: string): Promise<string | null> {
  if (!supabase) return null;
  const { error } = await supabase.auth.signInWithPassword({ email, password: clave });
  if (!error) return null;
  return error.message.includes("Email not confirmed") ? "Confirmá tu email con el enlace que te llegó." : "Email o contraseña incorrectos.";
}

/** Manda el enlace para elegir una contraseña nueva. Siempre responde igual, exista o no el email (no revela cuentas). */
export async function pedirCambioDeClave(email: string): Promise<void> {
  await supabase?.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}${window.location.pathname}` });
}

export async function elegirClave(nueva: string): Promise<string | null> {
  if (!supabase) return null;
  const { error } = await supabase.auth.updateUser({ password: nueva });
  if (!error) return null;
  return error.message.toLowerCase().includes("different") ? "La contraseña nueva tiene que ser distinta de la anterior."
    : error.message.toLowerCase().includes("weak") || error.message.includes("characters") ? "La contraseña es muy débil: usá al menos 8 caracteres con letras y números."
    : "No se pudo guardar la contraseña: pedí un enlace nuevo.";
}

export async function salir(): Promise<void> {
  await supabase?.auth.signOut();
}

export function escucharSesion(cb: (s: Session | null, recuperando: boolean) => void): () => void {
  if (!supabase) return () => undefined;
  void supabase.auth.getSession().then(({ data }) => cb(data.session, false));
  const { data } = supabase.auth.onAuthStateChange((evento, s) => cb(s, evento === "PASSWORD_RECOVERY"));
  return () => data.subscription.unsubscribe();
}
