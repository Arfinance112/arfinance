// Vista de conciliación: la versión web de la hoja IMP_Listo.
// Muestra los movimientos que salieron del extracto, sus alertas, permite corregir rubro y
// comprobante, crear una regla en el momento y aprobar el lote para volcarlo a Tesorería.
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "../../api/client";
import { fecha } from "../../formato";
import type { Alerta, Correccion, Lote, MovimientoPropuesto, Rubro, TipoMovimiento } from "../../types/conciliacion";
import "./ImpListo.css";

type Filtro = "todos" | "sin_regla" | "duplicados" | "sin_comprobante" | "listos";

const ETIQUETA_ALERTA: Record<Alerta, { texto: string; clase: string; ayuda: string }> = {
  SIN_REGLA: { texto: "⚠ Sin regla", clase: "alerta-bloquea", ayuda: "Asigná un rubro o creá una regla" },
  RUBRO_INEXISTENTE: { texto: "⚠ Rubro inexistente", clase: "alerta-bloquea", ayuda: "El rubro no está en el plan" },
  DUPLICADO_EXACTO: { texto: "⚠ Duplicado", clase: "alerta-duplicado", ayuda: "Misma referencia ya cargada: se omite" },
  POSIBLE_DUPLICADO: { texto: "⚠ Posible duplicado", clase: "alerta-duplicado", ayuda: "Ya hay un movimiento igual en Tesorería" },
  SIN_COMPROBANTE: { texto: "ℹ Sin comprobante", clase: "alerta-info", ayuda: "No cancelará facturas (opcional)" },
};

const pesos = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fechaCorta = (iso: string) => iso.split("-").reverse().join("/");

function coincideFiltro(m: MovimientoPropuesto, f: Filtro): boolean {
  switch (f) {
    case "sin_regla":
      return m.alertas.includes("SIN_REGLA") || m.alertas.includes("RUBRO_INEXISTENTE");
    case "duplicados":
      return m.alertas.includes("POSIBLE_DUPLICADO") || m.alertas.includes("DUPLICADO_EXACTO");
    case "sin_comprobante":
      return m.alertas.includes("SIN_COMPROBANTE");
    case "listos":
      return !m.bloqueado;
    default:
      return true;
  }
}

/** Sugerencia de texto para una regla nueva: las dos primeras palabras significativas de la descripción. */
function sugerirTexto(descripcion: string): string {
  return descripcion
    .split(/\s+/)
    .filter((p) => p.length > 2 && !/^\d+$/.test(p))
    .slice(0, 2)
    .join(" ")
    .toUpperCase();
}

interface ReglaEnEdicion {
  movId: number;
  texto: string;
  rubro: string;
  tipo: TipoMovimiento | "";
  soloEstaCuenta: boolean;
}

export function ImpListo({ loteId }: { loteId: string }) {
  const [lote, setLote] = useState<Lote | null>(null);
  const [rubros, setRubros] = useState<Rubro[]>([]);
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [regla, setRegla] = useState<ReglaEnEdicion | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    setLote(await api.lote(loteId));
  }, [loteId]);

  useEffect(() => {
    void cargar();
    void api.rubros().then(setRubros);
  }, [cargar]);

  const rubroPorCodigo = useMemo(() => new Map(rubros.map((r) => [r.codigo, r])), [rubros]);
  const visibles = useMemo(
    () => (lote ? lote.movimientos.filter((m) => coincideFiltro(m, filtro)) : []),
    [lote, filtro],
  );

  const avisar = (texto: string, tipo: "ok" | "error" = "ok") => setMensaje({ tipo, texto });
  const fallo = (e: unknown) =>
    avisar(e instanceof ApiError ? JSON.stringify(e.detalle) : "No se pudo completar la operación", "error");

  async function corregir(mov: MovimientoPropuesto, cambios: Correccion) {
    try {
      await api.corregir(loteId, mov.id, cambios);
      await cargar(); // las alertas de duplicado y conciliación dependen del lote entero
    } catch (e) {
      fallo(e);
    }
  }

  async function guardarRegla() {
    if (!regla || !lote) return;
    setOcupado(true);
    try {
      const r = await api.crearRegla(lote.cliente_id, {
        texto: regla.texto.trim(),
        rubro: regla.rubro,
        tipo: regla.tipo || null,
        cuenta: regla.soloEstaCuenta ? lote.cuenta : null,
      });
      avisar(`Regla creada: ${r.movimientos_reclasificados} movimientos reclasificados.`);
      setRegla(null);
      await cargar();
    } catch (e) {
      fallo(e);
    } finally {
      setOcupado(false);
    }
  }

  async function aprobar() {
    setOcupado(true);
    try {
      const r = await api.aprobar(loteId);
      const dif = r.conciliacion.diferencia;
      avisar(
        `${r.insertados} movimientos cargados en Tesorería, ${r.omitidos} omitidos.` +
          (dif == null ? "" : dif === 0 ? " Saldo conciliado." : ` Diferencia de conciliación: $ ${pesos.format(dif)}.`),
      );
      await cargar();
    } catch (e) {
      fallo(e);
    } finally {
      setOcupado(false);
    }
  }

  if (!lote) return <p className="cargando">Cargando movimientos…</p>;

  const { resumen, conciliacion: conc } = lote;
  const editable = lote.estado === "pendiente";
  const bloqueados = lote.movimientos.filter((m) => m.bloqueado).length;
  const filtros: { clave: Filtro; texto: string; cantidad: number }[] = [
    { clave: "todos", texto: "Todos", cantidad: resumen.movimientos },
    { clave: "sin_regla", texto: "Sin regla", cantidad: resumen.sin_regla + resumen.rubro_inexistente },
    { clave: "duplicados", texto: "Duplicados", cantidad: resumen.duplicados },
    { clave: "sin_comprobante", texto: "Sin comprobante", cantidad: resumen.sin_comprobante },
    { clave: "listos", texto: "Listos", cantidad: resumen.listos },
  ];

  return (
    <section className="imp-listo" aria-labelledby="titulo-lote">
      <header className="imp-encabezado">
        <div>
          <h2 id="titulo-lote">{lote.documento}</h2>
          <p className="sub">
            Cuenta {lote.cuenta} · Perfil {lote.perfil}
            {lote.perfil_autodetectado && <span className="chip">detectado automáticamente</span>} ·{" "}
            {lote.filas_leidas} filas leídas, {lote.filas_descartadas} descartadas (títulos o totales)
          </p>
        </div>
        {conc.saldo_extracto != null && (
          <table className={`conciliacion-saldos ${conc.diferencia === 0 ? "ok" : "dif"}`}>
            <thead>
              <tr><th /><th>Según extracto</th><th>Según el sistema</th><th>Diferencia</th></tr>
            </thead>
            <tbody>
              <tr>
                <th>Saldo inicial{conc.fecha_inicial ? ` (${fecha(conc.fecha_inicial)})` : ""}</th>
                <td>$ {pesos.format(conc.saldo_inicial_extracto ?? 0)}</td>
                <td>$ {pesos.format(conc.saldo_inicial_sistema ?? 0)}</td>
                <td className={conc.diferencia_inicial ? "dif" : "ok"}>
                  {conc.diferencia_inicial ? `$ ${pesos.format(conc.diferencia_inicial)}` : "Coincide"}
                </td>
              </tr>
              <tr>
                <th>Saldo final{conc.fecha ? ` (${fecha(conc.fecha)})` : ""}</th>
                <td>$ {pesos.format(conc.saldo_extracto)}</td>
                <td>$ {pesos.format(conc.saldo_planilla_despues_de_aprobar ?? 0)}</td>
                <td className={conc.diferencia ? "dif" : "ok"}>{conc.diferencia ? `$ ${pesos.format(conc.diferencia)}` : "Conciliado"}</td>
              </tr>
            </tbody>
          </table>
        )}
        {conc.diferencia_inicial ? (
          <p className="aviso-saldos" role="status">
            El saldo inicial no coincide: revisá el saldo inicial de la cuenta {lote.cuenta} en Cuentas, o si falta cargar un extracto anterior.
          </p>
        ) : null}
      </header>

      <nav className="filtros" aria-label="Filtrar movimientos">
        {filtros.map((f) => (
          <button key={f.clave} type="button" aria-pressed={filtro === f.clave} onClick={() => setFiltro(f.clave)}>
            {f.texto} <span className="contador">{f.cantidad}</span>
          </button>
        ))}
      </nav>

      <div className="tabla-scroll">
        <table className="grilla">
          <thead>
            <tr>
              <th>Fecha</th><th>Descripción</th><th>Tipo</th><th className="num">Importe</th>
              <th>Rubro</th><th>Comprobante</th><th>Regla aplicada</th><th>Alertas</th><th />
            </tr>
          </thead>
          <tbody>
            {visibles.map((m) => (
              <tr key={m.id} className={m.bloqueado ? "fila-bloqueada" : undefined}>
                <td>{fechaCorta(m.fecha)}</td>
                <td>
                  {m.descripcion}
                  {m.referencia && <span className="ref"> · Ref {m.referencia}</span>}
                </td>
                <td className={m.tipo === "Egreso" ? "egreso" : "ingreso"}>{m.tipo}</td>
                <td className="num">{pesos.format(m.importe)}</td>
                <td>
                  <select
                    aria-label={`Rubro del movimiento ${m.descripcion}`}
                    value={m.rubro ?? ""}
                    disabled={!editable}
                    onChange={(e) => void corregir(m, { rubro: e.target.value || null })}
                  >
                    <option value="">— elegir —</option>
                    {rubros.map((r) => (
                      <option key={r.codigo} value={r.codigo}>{r.codigo} · {r.nombre}</option>
                    ))}
                  </select>
                  {m.rubro && rubroPorCodigo.get(m.rubro) && (
                    <small className="linea">{rubroPorCodigo.get(m.rubro)?.linea_pl}</small>
                  )}
                </td>
                <td>
                  <input
                    aria-label={`Comprobante del movimiento ${m.descripcion}`}
                    defaultValue={m.comprobante ?? ""}
                    placeholder="FA-0001-…"
                    disabled={!editable}
                    onBlur={(e) => {
                      if ((e.target.value || null) !== m.comprobante) void corregir(m, { comprobante: e.target.value || null });
                    }}
                  />
                </td>
                <td className="regla">{m.regla ?? "—"}</td>
                <td>
                  {m.alertas.map((a) => (
                    <span key={a} className={`alerta ${ETIQUETA_ALERTA[a].clase}`} title={ETIQUETA_ALERTA[a].ayuda}>
                      {ETIQUETA_ALERTA[a].texto}
                    </span>
                  ))}
                </td>
                <td>
                  {editable && m.pata === "principal" && (
                    <button
                      type="button"
                      className="link"
                      onClick={() =>
                        setRegla({ movId: m.id, texto: sugerirTexto(m.descripcion), rubro: m.rubro ?? "", tipo: m.tipo, soloEstaCuenta: false })
                      }
                    >
                      Crear regla
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {regla && (
        <form
          className="panel-regla"
          onSubmit={(e) => {
            e.preventDefault();
            void guardarRegla();
          }}
        >
          <h3>Nueva regla de clasificación</h3>
          <p className="sub">Se aplica ya a todos los movimientos sin rubro de los lotes abiertos de este cliente, y a los extractos que vengan.</p>
          <label>
            Si la descripción contiene
            <input required minLength={2} value={regla.texto} onChange={(e) => setRegla({ ...regla, texto: e.target.value })} />
          </label>
          <label>
            Asignar el rubro
            <select required value={regla.rubro} onChange={(e) => setRegla({ ...regla, rubro: e.target.value })}>
              <option value="">— elegir —</option>
              {rubros.map((r) => (
                <option key={r.codigo} value={r.codigo}>{r.codigo} · {r.nombre}</option>
              ))}
            </select>
          </label>
          <label>
            Solo para
            <select value={regla.tipo} onChange={(e) => setRegla({ ...regla, tipo: e.target.value as TipoMovimiento | "" })}>
              <option value="">Ingresos y egresos</option>
              <option value="Ingreso">Ingresos</option>
              <option value="Egreso">Egresos</option>
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={regla.soloEstaCuenta} onChange={(e) => setRegla({ ...regla, soloEstaCuenta: e.target.checked })} />
            Solo para la cuenta {lote.cuenta}
          </label>
          <div className="acciones">
            <button type="submit" className="btn btn-primario" disabled={ocupado}>Guardar regla</button>
            <button type="button" className="btn btn-secundario" onClick={() => setRegla(null)}>Cancelar</button>
          </div>
        </form>
      )}

      <footer className="pie">
        {editable ? (
          <>
            {resumen.duplicados > 0 && (
              <span className="aviso">
                {resumen.duplicados === 1 ? "1 movimiento duplicado no se va a cargar" : `${resumen.duplicados} movimientos duplicados no se van a cargar`}
                {" "}(ya están en Tesorería).
              </span>
            )}
            <button type="button" className="btn btn-primario" disabled={ocupado || bloqueados > 0} onClick={() => void aprobar()}>
              Aprobar y pasar a Tesorería
            </button>
            {bloqueados > 0 && (
              <span className="aviso">
                {bloqueados === 1 ? "Falta 1 rubro por asignar." : `Faltan ${bloqueados} rubros por asignar.`}
              </span>
            )}
          </>
        ) : (
          <span className="chip">Lote {lote.estado}</span>
        )}
      </footer>

      <p role="status" aria-live="polite" className={mensaje ? `mensaje ${mensaje.tipo}` : "mensaje"}>
        {mensaje?.texto}
      </p>
    </section>
  );
}
