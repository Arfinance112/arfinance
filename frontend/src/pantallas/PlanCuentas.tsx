import { useEffect, useMemo, useState } from "react";

import { api, mensajeDeError } from "../api/client";
import type { CuentaContable } from "../types/app";
import type { Rubro } from "../types/conciliacion";

const sinAcentos = (t: string) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();

/** Plan de cuentas del cliente: árbol con buscador, alta de subcuentas, edición, baja y vínculo con los rubros. */
export function PlanCuentas({ clienteId }: { clienteId: string }) {
  const [cuentas, setCuentas] = useState<CuentaContable[] | null>(null);
  const [sinCuenta, setSinCuenta] = useState<string[]>([]);
  const [rubros, setRubros] = useState<Record<string, Rubro>>({});
  const [buscar, setBuscar] = useState("");
  const [abierta, setAbierta] = useState<string | null>(null);     // cuenta con el panel de edición abierto
  const [nueva, setNueva] = useState<{ padre: string; codigo: string; nombre: string; imputable: boolean } | null>(null);
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  const cargar = () => api.planCuentas(clienteId).then((p) => { setCuentas(p.cuentas); setSinCuenta(p.rubros_sin_cuenta); });
  useEffect(() => {
    void cargar();
    void api.rubros().then((r) => setRubros(Object.fromEntries(r.map((x) => [x.codigo, x]))));
  }, [clienteId]); // eslint-disable-line react-hooks/exhaustive-deps

  const porCodigo = useMemo(() => new Map((cuentas ?? []).map((c) => [c.codigo, c])), [cuentas]);
  const nivel = (c: CuentaContable): number => (c.padre && porCodigo.get(c.padre) ? nivel(porCodigo.get(c.padre)!) + 1 : 0);

  // al buscar, se muestran las cuentas que coinciden y sus agrupadoras (para no perder el contexto)
  const visibles = useMemo(() => {
    if (!cuentas) return [];
    const q = sinAcentos(buscar.trim());
    if (!q) return cuentas;
    const coinciden = new Set(cuentas.filter((c) => c.codigo.startsWith(q) || sinAcentos(c.nombre).includes(q)
      || c.rubros.some((r) => r.includes(q) || sinAcentos(rubros[r]?.nombre ?? "").includes(q))).map((c) => c.codigo));
    const conPadres = new Set(coinciden);
    coinciden.forEach((cod) => { let p = porCodigo.get(cod)?.padre; while (p) { conPadres.add(p); p = porCodigo.get(p)?.padre ?? null; } });
    return cuentas.filter((c) => conPadres.has(c.codigo));
  }, [cuentas, buscar, porCodigo, rubros]);

  const accion = async (f: () => Promise<unknown>, ok: string) => {
    try { await f(); setMensaje({ ok: true, texto: ok }); await cargar(); }
    catch (e) { setMensaje({ ok: false, texto: mensajeDeError(e) }); }
  };

  const proponerCodigo = (padre: CuentaContable) => {
    const hijos = (cuentas ?? []).filter((c) => c.padre === padre.codigo).map((c) => Number(c.codigo));
    const base = Number(padre.codigo);
    const paso = padre.padre ? 1 : 1000;            // bajo una raíz los rubros van de a 1000, bajo un rubro de a 1
    return String(hijos.length ? Math.max(...hijos) + paso : base + (paso === 1 ? 10 : 1000));
  };

  if (!cuentas) return <p className="cargando">Cargando el plan de cuentas…</p>;

  return (
    <div className="pila">
      <div className="formulario-linea">
        <label>Buscar
          <input type="search" value={buscar} onChange={(e) => setBuscar(e.target.value)} placeholder="Código, nombre o rubro" autoFocus />
        </label>
        <span className="sub">
          {cuentas.length} cuentas · {cuentas.filter((c) => c.imputable).length} imputables
          {sinCuenta.length > 0 && ` · ${sinCuenta.length} rubros sin cuenta contable`}
        </span>
      </div>
      {mensaje && <p role="status" className={mensaje.ok ? "mensaje ok" : "error"}>{mensaje.texto}</p>}

      <div className="tabla-scroll">
        <table className="tabla plan">
          <thead><tr><th>Código</th><th>Cuenta</th><th>Rubros vinculados</th><th /></tr></thead>
          <tbody>
            {visibles.length === 0 && <tr><td colSpan={4} className="vacio">Ninguna cuenta coincide con «{buscar}».</td></tr>}
            {visibles.map((c) => (
              <FilaCuenta key={c.codigo} c={c} nivel={nivel(c)} rubros={rubros} sinCuenta={sinCuenta}
                abierta={abierta === c.codigo} alAbrir={() => setAbierta(abierta === c.codigo ? null : c.codigo)}
                alNueva={() => setNueva({ padre: c.codigo, codigo: proponerCodigo(c), nombre: "", imputable: true })}
                alGuardar={(cambio, texto) => accion(() => api.editarCuentaContable(clienteId, c.codigo, cambio), texto)}
                alVincular={(lista) => accion(() => api.vincularRubros(clienteId, c.codigo, lista), `Rubros de ${c.codigo} actualizados.`)}
                alBorrar={() => {
                  if (window.confirm(`¿Eliminar la cuenta ${c.codigo} ${c.nombre}?`))
                    void accion(() => api.bajaCuentaContable(clienteId, c.codigo), `Cuenta ${c.codigo} eliminada.`);
                }} />
            ))}
          </tbody>
        </table>
      </div>

      {nueva && (
        <form className="tarjeta formulario-grilla" onSubmit={(e) => {
          e.preventDefault();
          void accion(() => api.altaCuentaContable(clienteId, { ...nueva, padre: nueva.padre }), `Cuenta ${nueva.codigo} creada.`)
            .then(() => setNueva(null));
        }}>
          <h3>Nueva subcuenta de {nueva.padre} {porCodigo.get(nueva.padre)?.nombre}</h3>
          <label>Código<input required inputMode="numeric" pattern="[0-9]{1,12}" value={nueva.codigo}
            onChange={(e) => setNueva({ ...nueva, codigo: e.target.value })} /></label>
          <label>Nombre<input required autoFocus value={nueva.nombre} onChange={(e) => setNueva({ ...nueva, nombre: e.target.value })} /></label>
          <label className="check"><input type="checkbox" checked={nueva.imputable} onChange={(e) => setNueva({ ...nueva, imputable: e.target.checked })} />
            Imputable (recibe movimientos). Destildá para crear una agrupadora.</label>
          <div className="acciones">
            <button className="btn btn-primario">Crear cuenta</button>
            <button type="button" className="btn btn-secundario" onClick={() => setNueva(null)}>Cancelar</button>
          </div>
        </form>
      )}
    </div>
  );
}

function FilaCuenta({ c, nivel, rubros, sinCuenta, abierta, alAbrir, alNueva, alGuardar, alVincular, alBorrar }: {
  c: CuentaContable; nivel: number; rubros: Record<string, Rubro>; sinCuenta: string[]; abierta: boolean;
  alAbrir: () => void; alNueva: () => void; alBorrar: () => void;
  alGuardar: (cambio: Partial<CuentaContable>, texto: string) => Promise<void>;
  alVincular: (rubros: string[]) => Promise<void>;
}) {
  const [nombre, setNombre] = useState(c.nombre);
  const [agregar, setAgregar] = useState("");
  const motivoNoBorrar = c.subcuentas ? `Agrupa ${c.subcuentas} cuentas` : c.en_uso ? "Tiene movimientos" : "";
  return (
    <>
      <tr className={c.imputable ? undefined : "agrupadora"}>
        <td className="codigo">{c.codigo}</td>
        <td style={{ paddingLeft: 12 + nivel * 20 }}>
          {c.nombre}
          {c.ajustable && <span className="chip" title="Ajustable por inflación">AxI</span>}
          {c.en_uso && <span className="chip" title="Alguno de sus rubros ya tiene movimientos">con movimientos</span>}
        </td>
        <td className="rubros-celda">
          {c.rubros.map((r) => <span key={r} className="chip" title={rubros[r]?.nombre}>{r}</span>)}
        </td>
        <td className="acciones-doc">
          <button className="link" onClick={alAbrir}>{abierta ? "Cerrar" : "Editar"}</button>
          {!c.imputable && <button className="link" onClick={alNueva}>+ Subcuenta</button>}
          <button className="link peligro" disabled={!!motivoNoBorrar} title={motivoNoBorrar || "Eliminar"} onClick={alBorrar}>Eliminar</button>
        </td>
      </tr>
      {abierta && (
        <tr className="edicion">
          <td />
          <td colSpan={3}>
            <div className="formulario-linea">
              <label>Nombre<input value={nombre} onChange={(e) => setNombre(e.target.value)} /></label>
              <button className="btn btn-secundario btn-chico" disabled={!nombre.trim() || nombre === c.nombre}
                onClick={() => void alGuardar({ nombre }, `Cuenta ${c.codigo} renombrada.`)}>Guardar nombre</button>
              <label className="check"><input type="checkbox" checked={c.ajustable}
                onChange={(e) => void alGuardar({ ajustable: e.target.checked }, "Ajuste por inflación actualizado.")} />Ajustable por inflación</label>
              <label className="check"><input type="checkbox" checked={c.expuesta}
                onChange={(e) => void alGuardar({ expuesta: e.target.checked }, "Exposición a la inflación actualizada.")} />Expuesta a la inflación</label>
            </div>
            {c.imputable ? (
              <div className="formulario-linea">
                <span className="sub">Rubros que se imputan a esta cuenta:</span>
                {c.rubros.map((r) => (
                  <span key={r} className="chip">{r} · {rubros[r]?.nombre}
                    <button className="link" aria-label={`Quitar ${r}`} onClick={() => void alVincular(c.rubros.filter((x) => x !== r))}>✕</button>
                  </span>
                ))}
                <select value={agregar} onChange={(e) => setAgregar(e.target.value)} aria-label="Agregar rubro">
                  <option value="">+ agregar rubro…</option>
                  {sinCuenta.map((r) => <option key={r} value={r}>{r} · {rubros[r]?.nombre}</option>)}
                </select>
                <button className="btn btn-secundario btn-chico" disabled={!agregar}
                  onClick={() => { void alVincular([...c.rubros, agregar]); setAgregar(""); }}>Vincular</button>
              </div>
            ) : <p className="sub">Es una cuenta agrupadora: los rubros se vinculan a sus subcuentas imputables.</p>}
          </td>
        </tr>
      )}
    </>
  );
}
