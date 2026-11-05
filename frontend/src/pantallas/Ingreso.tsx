import { useState } from "react";

import { elegirClave, ingresar, pedirCambioDeClave } from "../auth/sesion";

/** Ingreso con email y contraseña, y pedido de enlace para elegir una contraseña nueva. */
export function Ingreso() {
  const [email, setEmail] = useState("");
  const [clave, setClave] = useState("");
  const [olvido, setOlvido] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  return (
    <div className="pantalla-ingreso">
      <form
        className="tarjeta ingreso-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setOcupado(true);
          if (olvido) {
            await pedirCambioDeClave(email);
            setEnviado(true);
          } else {
            setError(await ingresar(email, clave));
          }
          setOcupado(false);
        }}
      >
        <h1>{olvido ? "Elegí una contraseña nueva" : "Ingresá a ARFinance"}</h1>
        <label>
          Email
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        {!olvido && (
          <label>
            Contraseña
            <input type="password" autoComplete="current-password" required value={clave} onChange={(e) => setClave(e.target.value)} />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {enviado ? (
          <p className="sub" role="status">Si el email está registrado, te llegó un enlace para elegir la contraseña. Revisá también correo no deseado.</p>
        ) : (
          <button className="btn btn-primario" disabled={ocupado}>{olvido ? "Mandame el enlace" : "Ingresar"}</button>
        )}
        <button type="button" className="link" onClick={() => { setOlvido(!olvido); setEnviado(false); setError(null); }}>
          {olvido ? "Volver a ingresar" : "Olvidé mi contraseña"}
        </button>
      </form>
    </div>
  );
}

/** Después de un enlace de invitación o de recuperación: la sesión ya está abierta, falta la contraseña. */
export function ElegirClave({ alTerminar }: { alTerminar: () => void }) {
  const [clave, setClave] = useState("");
  const [repetida, setRepetida] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  return (
    <div className="pantalla-ingreso">
      <form
        className="tarjeta ingreso-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (clave !== repetida) return setError("Las dos contraseñas no coinciden.");
          setOcupado(true);
          const err = await elegirClave(clave);
          setOcupado(false);
          if (err) setError(err);
          else alTerminar();
        }}
      >
        <h1>Elegí tu contraseña</h1>
        <label>
          Contraseña nueva
          <input type="password" autoComplete="new-password" minLength={8} required value={clave} onChange={(e) => setClave(e.target.value)} />
        </label>
        <label>
          Repetila
          <input type="password" autoComplete="new-password" minLength={8} required value={repetida} onChange={(e) => setRepetida(e.target.value)} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn btn-primario" disabled={ocupado}>Guardar y entrar</button>
      </form>
    </div>
  );
}
