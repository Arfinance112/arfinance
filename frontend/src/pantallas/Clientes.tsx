import { useEffect, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import { fecha } from "../formato";
import type { ClienteArchivado, ClienteResumen } from "../types/app";

/** Carpetas de clientes: el tablero multicliente de entrada. */
export function Clientes() {
  const [clientes, setClientes] = useState<ClienteResumen[] | null>(null);
  const [sinOrganizacion, setSinOrganizacion] = useState(false);
  const [nombre, setNombre] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [archivados, setArchivados] = useState<ClienteArchivado[]>([]);
  const [aviso, setAviso] = useState<string | null>(null);

  const cargar = async () => {
    const yo = await api.yo();
    setSinOrganizacion(!yo.organizacion_id);
    setClientes(yo.organizacion_id ? await api.clientes() : []);
    setArchivados(yo.organizacion_id ? await api.clientesArchivados() : []);
  };

  useEffect(() => {
    cargar().catch((e) => setError(mensajeDeError(e)));
  }, []);

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.crearOrganizacion(nombre);
      setNombre("");
      await cargar();
    } catch (err) {
      setError(mensajeDeError(err));
    }
  }

  async function accion(f: () => Promise<string>) {
    try { setAviso(await f()); await cargar(); }
    catch (err) { setAviso(mensajeDeError(err)); }
  }

  if (clientes === null) return <p className="cargando">{error ?? "Cargando clientes…"}</p>;

  return (
    <div className="pila">
      {sinOrganizacion ? (
        <div className="tarjeta">
          <h2>Bienvenido</h2>
          <p>Para empezar, poné el nombre de tu estudio o consultora. Vas a ser su administrador.</p>
        </div>
      ) : (
        <div className="grilla-tarjetas">
          {clientes.length === 0 && <p className="sub">Todavía no hay clientes. Creá el primero.</p>}
          {clientes.map((c) => (
            <div key={c.id} className="pila-chica">
            <a className="tarjeta tarjeta-cliente" href={`#/clientes/${c.id}/documentos`}>
              <h3>{c.nombre}</h3>
              <p className="sub">{c.cuit || "Sin CUIT"}</p>
              <dl className="cifras">
                <div><dt>Cuentas</dt><dd>{c.cuentas}</dd></div>
                <div><dt>Movimientos</dt><dd>{c.movimientos_tesoreria}</dd></div>
                <div><dt>Por conciliar</dt><dd className={c.lotes_pendientes ? "pendiente" : undefined}>{c.lotes_pendientes}</dd></div>
              </dl>
            </a>
            <button type="button" className="link peligro" onClick={() => {
              if (window.confirm(`¿Archivar ${c.nombre}? Deja de verse, pero no se borra nada: lo podés restaurar durante 30 días.`))
                void accion(async () => { await api.archivarCliente(c.id); return `${c.nombre} archivado. Lo podés restaurar abajo durante 30 días.`; });
            }}>Archivar</button>
            </div>
          ))}
        </div>
      )}

      {aviso && <p role="status" className="mensaje ok">{aviso}</p>}
      {archivados.length > 0 && (
        <details className="tarjeta">
          <summary>Archivados ({archivados.length})</summary>
          <ul className="lista-simple">
            {archivados.map((a) => (
              <li key={a.id}>
                <strong>{a.nombre}</strong> <span className="sub">archivado el {fecha(a.archivado_en)} · se puede restaurar hasta el {fecha(a.restaurable_hasta)}</span>{" "}
                <button type="button" className="link" onClick={() => void accion(async () => {
                  await api.restaurarCliente(a.id); return `${a.nombre} restaurado.`;
                })}>Restaurar</button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {sinOrganizacion ? (
        <form className="tarjeta formulario-linea" onSubmit={crear}>
          <h3>Tu organización</h3>
          <label>
            Nombre del estudio
            <input required minLength={2} value={nombre} onChange={(e) => setNombre(e.target.value)} />
          </label>
          <button className="btn btn-primario">Crear organización</button>
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      ) : (
        <div className="acciones"><a className="btn btn-primario" href="#/alta">+ Nuevo cliente</a></div>
      )}
    </div>
  );
}
