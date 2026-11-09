"""Plan de cuentas contable de cada cliente y sus reglas.

Cada cliente arranca con la plantilla (db/seeds/plan_cuentas.json) y la puede editar. Las cuentas agrupadoras
(no imputables) ordenan el árbol; los movimientos se imputan a cuentas imputables a través de los rubros de
gestión: cada rubro apunta a una cuenta del plan. Por eso una cuenta "tiene movimientos" cuando alguno de sus
rubros ya se usó en Tesorería, comprobantes, F.931, ventas o mermas del cliente.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

CLASES = {1: "Activo", 2: "Pasivo", 3: "Patrimonio neto", 4: "Resultado", 5: "Orden"}


class PlanInvalido(ValueError):
    pass


@dataclass
class CuentaContable:
    codigo: str
    nombre: str
    imputable: bool = True
    ajustable: bool = False
    expuesta: bool = False
    clase: int = 1
    padre: str | None = None
    comentario: str = ""

    @property
    def clase_nombre(self) -> str:
        return CLASES.get(self.clase, str(self.clase))

    def como_dict(self) -> dict:
        return {**asdict(self), "clase_nombre": self.clase_nombre}


def desde_plantilla(filas: list[dict]) -> list[CuentaContable]:
    campos = CuentaContable.__dataclass_fields__
    return [CuentaContable(**{k: v for k, v in f.items() if k in campos}) for f in filas]


def validar_alta(plan: dict[str, CuentaContable], nueva: CuentaContable) -> None:
    if not re.fullmatch(r"\d{1,12}", nueva.codigo):
        raise PlanInvalido("El código tiene que ser numérico, de hasta 12 dígitos.")
    if nueva.codigo in plan:
        raise PlanInvalido(f"Ya existe la cuenta {nueva.codigo} ({plan[nueva.codigo].nombre}).")
    if not nueva.nombre.strip():
        raise PlanInvalido("La cuenta necesita un nombre.")
    if nueva.clase not in CLASES:
        raise PlanInvalido("Clase inválida: 1 Activo, 2 Pasivo, 3 Patrimonio neto, 4 Resultado, 5 Orden.")
    if nueva.padre is not None:
        padre = plan.get(nueva.padre)
        if not padre:
            raise PlanInvalido(f"La cuenta agrupadora {nueva.padre} no existe.")
        if padre.imputable:
            raise PlanInvalido(f"{padre.codigo} {padre.nombre} es imputable: solo una cuenta agrupadora puede tener subcuentas.")
        if padre.clase != nueva.clase:
            raise PlanInvalido(f"La cuenta tiene que ser de la misma clase que su agrupadora ({padre.clase_nombre}).")


def validar_baja(plan: dict[str, CuentaContable], codigo: str, en_uso: set[str]) -> None:
    if codigo not in plan:
        raise PlanInvalido(f"La cuenta {codigo} no existe.")
    hijas = [c.codigo for c in plan.values() if c.padre == codigo]
    if hijas:
        raise PlanInvalido(f"No se puede eliminar: agrupa {len(hijas)} cuentas ({', '.join(sorted(hijas)[:4])}…). Eliminá primero esas.")
    if codigo in en_uso:
        raise PlanInvalido("No se puede eliminar: tiene movimientos (alguno de sus rubros ya se usó). Podés renombrarla.")


def validar_cambio_imputable(plan: dict[str, CuentaContable], codigo: str, imputable: bool, con_rubros: bool) -> None:
    if imputable and any(c.padre == codigo for c in plan.values()):
        raise PlanInvalido("Tiene subcuentas: una cuenta agrupadora no puede pasar a imputable.")
    if not imputable and con_rubros:
        raise PlanInvalido("Tiene rubros vinculados: desvinculalos antes de pasarla a agrupadora.")


def cuentas_en_uso(rubro_cuenta: dict[str, str], rubros_usados: set[str]) -> set[str]:
    return {cuenta for rubro, cuenta in rubro_cuenta.items() if rubro in rubros_usados}
