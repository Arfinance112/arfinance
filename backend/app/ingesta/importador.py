"""Importador genérico: cualquier planilla o CSV, eligiendo qué columna es cada dato.

El archivo se transforma a las columnas canónicas del destino y después lo procesa el mismo lector que el
formato conocido (así valen las mismas reglas: duplicados, ítems sin alta, reproceso, borrado).
"""
from __future__ import annotations

from app.core.numeros import parse_fecha, parse_numero
from app.ingesta.reglas import normalizar

# destino → [(campo, etiqueta canónica, obligatorio, alias para sugerir)]
DESTINOS: dict[str, dict] = {
    "ventas_item": {"nombre": "Detalle de ventas por ítem", "campos": [
        ("fecha", "Fecha", True, ["FECHA", "FECHA DE VENTA", "FECHA EMISION"]),
        ("comprobante", "Comprobante", False, ["COMPROBANTE", "FACTURA", "TICKET", "NUMERO", "NRO"]),
        ("item", "Código", True, ["CODIGO", "ITEM", "SKU", "PRODUCTO", "ARTICULO"]),
        ("cantidad", "Cantidad", True, ["CANTIDAD", "CANT", "UNIDADES"]),
        ("precio", "Precio unitario", True, ["PRECIO UNITARIO", "PRECIO", "PRECIO NETO", "PUNIT"]),
    ]},
    "compras_item": {"nombre": "Detalle de compras por ítem", "campos": [
        ("fecha", "Fecha", True, ["FECHA", "FECHA COMPRA", "FECHA EMISION"]),
        ("comprobante", "Comprobante", False, ["COMPROBANTE", "FACTURA", "NUMERO", "NRO"]),
        ("proveedor", "Proveedor", True, ["PROVEEDOR", "RAZON SOCIAL", "CUIT"]),
        ("item", "Código", True, ["CODIGO", "ITEM", "SKU", "PRODUCTO", "ARTICULO", "INSUMO"]),
        ("cantidad", "Cantidad", True, ["CANTIDAD", "CANT", "UNIDADES"]),
        ("precio", "Costo unitario", True, ["COSTO UNITARIO", "COSTO", "PRECIO UNITARIO", "PRECIO"]),
    ]},
    "inversiones": {"nombre": "Movimientos de inversiones", "campos": [
        ("fecha", "Fecha", True, ["FECHA", "FECHA OPERACION", "FECHA CONCERTACION"]),
        ("instrumento", "Instrumento", False, ["INSTRUMENTO", "TIPO INSTRUMENTO", "CLASE"]),
        ("nombre", "Nombre", True, ["FONDO", "NOMBRE", "ESPECIE", "DESCRIPCION"]),
        ("tipo", "Tipo de movimiento", True, ["TIPO", "OPERACION", "MOVIMIENTO"]),
        ("importe", "Importe", True, ["IMPORTE", "MONTO", "VALOR", "TOTAL"]),
        ("moneda", "Moneda", False, ["MONEDA"]),
    ]},
}
MAX_MUESTRA = 15


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def fila_encabezado_probable(filas: list[list]) -> int:
    """La primera de las 15 primeras filas con al menos 2 celdas de texto (no números)."""
    for i, f in enumerate(filas[:15]):
        textos = [c for c in f if _texto(c) and not _texto(c).replace(".", "").replace(",", "").replace("-", "").isdigit()]
        if len(textos) >= 2:
            return i
    return 0


def sugerir(encabezado: list, destino: str) -> dict[str, int]:
    norm = [normalizar(_texto(c)).replace(".", "") for c in encabezado]
    sal: dict[str, int] = {}
    for campo, _, _, alias in DESTINOS[destino]["campos"]:
        for a in alias:
            idx = next((i for i, n in enumerate(norm) if n == a and i not in sal.values()), None)
            if idx is None:
                idx = next((i for i, n in enumerate(norm) if a in n and i not in sal.values()), None)
            if idx is not None:
                sal[campo] = idx
                break
    return sal


def vista(filas: list[list], fila_encabezado: int | None = None) -> dict:
    i = fila_encabezado_probable(filas) if fila_encabezado is None else fila_encabezado
    if not filas or i >= len(filas):
        raise ValueError("El archivo no tiene filas para importar.")
    enc = [_texto(c) or f"Columna {n + 1}" for n, c in enumerate(filas[i])]
    return {"fila_encabezado": i, "columnas": enc, "total_filas": max(len(filas) - i - 1, 0),
            "muestra": [[_texto(c) for c in f] for f in filas[i + 1:i + 1 + MAX_MUESTRA]],
            "destinos": {k: {"nombre": d["nombre"], "campos": [{"campo": c, "etiqueta": e, "obligatorio": o} for c, e, o, _ in d["campos"]],
                             "sugerido": sugerir(filas[i], k)} for k, d in DESTINOS.items()}}


def validar_mapeo(destino: str, mapeo: dict[str, int], columnas: int) -> None:
    if destino not in DESTINOS:
        raise ValueError("Destino inválido: " + ", ".join(DESTINOS))
    campos = {c: o for c, _, o, _ in DESTINOS[destino]["campos"]}
    faltan = [c for c, o in campos.items() if o and c not in mapeo]
    if faltan:
        raise ValueError("Falta elegir la columna de: " + ", ".join(e for c, e, _, _ in DESTINOS[destino]["campos"] if c in faltan))
    if any(c not in campos for c in mapeo):
        raise ValueError("Hay campos que no corresponden al destino")
    if any(not 0 <= v < columnas for v in mapeo.values()):
        raise ValueError("Columna fuera del archivo")


def a_canonico(filas: list[list], destino: str, mapeo: dict[str, int], fila_encabezado: int) -> list[list[str]]:
    """Encabezado canónico + datos en ese orden, listos para el lector del formato conocido."""
    campos = [(c, e) for c, e, _, _ in DESTINOS[destino]["campos"] if c in mapeo]
    sal = [[e for _, e in campos]]
    for f in filas[fila_encabezado + 1:]:
        fila = [_texto(f[mapeo[c]]) if mapeo[c] < len(f) else "" for c, _ in campos]
        if any(fila):
            sal.append(fila)
    return sal


_TIPOS_INV = {"aporte": ["APORTE", "SUSCRIPCION", "SUSCRIP", "COMPRA", "CONSTITUCION", "DEPOSITO"],
              "rescate": ["RESCATE", "VENTA", "RETIRO", "VENCIMIENTO", "CANCELACION"],
              "valuacion": ["VALUACION", "SALDO", "TENENCIA", "VALOR"]}
_INSTRUMENTOS = {"FCI": ["FCI", "FONDO"], "Plazo fijo": ["PLAZO FIJO", "PF"], "Caución": ["CAUCION"], "Acciones": ["ACCION"],
                 "Bonos": ["BONO", "ON", "OBLIGACION"], "Cedears": ["CEDEAR"]}


def inversiones_desde(canonico: list[list[str]]) -> tuple[list[dict], list[str]]:
    """Convierte las filas canónicas de inversiones; devuelve (movimientos, errores por fila)."""
    enc = canonico[0]
    movs, errores = [], []
    for n, f in enumerate(canonico[1:], start=2):
        v = dict(zip(enc, f))
        fecha = parse_fecha(v.get("Fecha"))
        tipo_txt = normalizar(v.get("Tipo de movimiento", ""))
        tipo = next((t for t, al in _TIPOS_INV.items() if any(a in tipo_txt for a in al)), None)
        inst_txt = normalizar(v.get("Instrumento", "")) or normalizar(v.get("Nombre", ""))
        inst = next((i for i, al in _INSTRUMENTOS.items() if any(a in inst_txt.split() or a in inst_txt for a in al)), "Otro")
        try:
            importe = abs(parse_numero(v.get("Importe")))
        except Exception:
            importe = None
        moneda = "USD" if "USD" in normalizar(v.get("Moneda", "")) or "DOLAR" in normalizar(v.get("Moneda", "")) else "ARS"
        nombre = (v.get("Nombre") or "").strip()[:80]
        if not fecha or not tipo or importe is None or not nombre:
            errores.append(f"Fila {n}: falta fecha, tipo (aporte/rescate/valuación), nombre o importe válido.")
            continue
        movs.append({"fecha": fecha, "instrumento": inst, "nombre": nombre, "tipo": tipo, "importe": importe, "moneda": moneda})
    return movs, errores
