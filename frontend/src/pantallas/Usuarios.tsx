import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import type { MiembroOrg, Rol } from "../types/app";

export const ROLES: Record<Rol, { nombre: string; ayuda: string }> = {
  admin: { nombre: "Administrador", ayuda: "Todo, incluida la gestión de usuarios" },
  consultor: { nombre: "Consultor", ayuda: "Todo salvo gestionar usuarios" },
  carga: { nombre: "Carga", ayuda: "Sube documentos, concilia y aprueba extractos, clasifica comprobantes" },
  lectura: { nombre: "Lectura", ayuda: "Solo ve: no puede cambiar nada" },
};

/** Usuarios de la organización: invitar por email, cambiar el rol y quitar. Solo un administrador hace cambios. */
export function Usuarios() {
  const [miembros, setMiembros] = useState<MiembroOrg[] | null>(null);
  const [soyAdmin, setSoyAdmin] = useState(false);
  const [email, setEmail] = useState("");
  const [rol, setRol] = useState<Rol>("carga");
  const [ocupado, setOcupado] = useState(false);
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  const cargar = async () => {
    const [m, yo] = await Promise.all([api.miembros(), api.yo()]);
    setMiembros(m.miembros);
    setSoyAdmin(yo.rol === "admin");
  };
  useEffect(() => { cargar().catch((e) => setMensaje({ ok: false, texto: mensajeDeError(e) })); }, []);

  const accion = async (f: () => Promise<string>) => {
    setOcupado(true);
    try { setMensaje({ ok: true, texto: await f() }); await cargar(); }
    catch (e) { setMensaje({ ok: false, texto: mensajeDeError(e) }); }
    finally { setOcupado(false); }
  };

  if (!miembros) return <p className="cargando">{mensaje?.texto ?? "Cargando usuarios…"}</p>;

  return (
    <div className="pila">
      {mensaje && <p role="status" className={mensaje.ok ? "mensaje ok" : "error"}>{mensaje.texto}</p>}
      <div className="tabla-scroll">
        <table className="tabla">
          <thead><tr><th>Email</th><th>Rol</th><th>Qué puede hacer</th><th /></tr></thead>
          <tbody>
            {miembros.map((m) => (
              <tr key={m.usuario_id}>
                <td>{m.email}{m.vos && <span className="chip">vos</span>}</td>
                <td>
                  {soyAdmin ? (
                    <select value={m.rol} disabled={ocupado} aria-label={`Rol de ${m.email}`}
                      onChange={(e) => void accion(async () => {
                        await api.cambiarRol(m.usuario_id, e.target.value as Rol);
                        return `${m.email} ahora es ${ROLES[e.target.value as Rol].nombre}.`;
                      })}>
                      {(Object.keys(ROLES) as Rol[]).map((r) => <option key={r} value={r}>{ROLES[r].nombre}</option>)}
                    </select>
                  ) : ROLES[m.rol].nombre}
                </td>
                <td className="sub">{ROLES[m.rol].ayuda}</td>
                <td>
                  {soyAdmin && !m.vos && (
                    <button className="link peligro" disabled={ocupado} onClick={() => {
                      if (window.confirm(`¿Quitar a ${m.email} de la organización? Deja de ver todos los clientes.`))
                        void accion(async () => { await api.quitarMiembro(m.usuario_id); return `${m.email} ya no es miembro.`; });
                    }}>Quitar</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {soyAdmin ? (
        <form className="tarjeta formulario-linea" onSubmit={(e) => {
          e.preventDefault();
          void accion(async () => {
            const r = await api.invitarMiembro(email, rol);
            setEmail("");
            return r.mail_enviado
              ? `Invitación enviada a ${r.email}: le llega un mail para elegir su contraseña (puede tardar unos minutos o caer en no deseado).`
              : `${r.email} ya tenía cuenta: quedó sumado a la organización. Puede entrar con su contraseña.`;
          });
        }}>
          <h3>Invitar a un usuario</h3>
          <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nombre@empresa.com" /></label>
          <label>Rol
            <select value={rol} onChange={(e) => setRol(e.target.value as Rol)}>
              {(Object.keys(ROLES) as Rol[]).map((r) => <option key={r} value={r}>{ROLES[r].nombre}</option>)}
            </select>
          </label>
          <span className="sub">{ROLES[rol].ayuda}</span>
          <button className="btn btn-primario" disabled={ocupado}>Invitar</button>
        </form>
      ) : <p className="sub">Solo un administrador puede invitar usuarios o cambiar roles.</p>}
    </div>
  );
}
