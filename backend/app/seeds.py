"""Carga de los maestros exportados de la planilla (db/seeds/*.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.ingesta.modelos import Perfil, Regla

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"


def _json(nombre: str):
    return json.loads((SEEDS / f"{nombre}.json").read_text(encoding="utf-8"))


@lru_cache
def rubros() -> dict[str, dict]:
    return {r["codigo"]: r for r in _json("rubros")}


@lru_cache
def perfiles() -> list[Perfil]:
    return [Perfil.desde_dict(p) for p in _json("perfiles")]


@lru_cache
def reglas_globales() -> list[Regla]:
    return [Regla.desde_dict({**r, "id": f"G{r['prioridad']:05d}"}) for r in _json("reglas")]


@lru_cache
def entidades() -> list[dict]:
    return _json("entidades")
