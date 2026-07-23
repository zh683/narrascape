"""Shared building blocks for typed pipeline contracts.

Contracts are the YAML artifacts stages exchange (director_contract.yaml,
film_timeline.yaml, film_supervisor.yaml, ...). The pydantic models in this
package are the canonical field-level schema; ``artifacts.py`` keeps its
lightweight top-level key / schema_version checks as a complementary gate.

Compatibility policy (hard constraint):

- ``extra="allow"`` everywhere: unknown fields from newer/older producers
  survive validation and round-trip through ``model_dump`` unchanged.
- Optional fields carry defaults so legacy artifacts keep loading.
- ``schema_version`` uses ``Literal`` anchors and stays required, matching the
  existing ``artifacts.py`` enforcement.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base for all contract models: tolerate (and preserve) unknown fields."""

    model_config = ConfigDict(extra="allow")


class ProjectRef(ContractModel):
    """`project` block present in most contract artifacts."""

    name: str = ""
    title: str = ""
