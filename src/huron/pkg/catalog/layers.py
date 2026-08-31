"""The storage-layer workflow: what each layer is, who may write it, and how
data is promoted between layers.

Definitions only - this module performs no I/O and holds no framework
imports. The API service composes it with ``pkg/rbac`` to answer "may this
principal write this layer of this dataset?", and the pipeline services use
:func:`validate_promotion` to refuse a derivation the workflow does not
define.

The write rule, as an invariant rather than convention:

- ``raw`` and ``bronze`` accept commits from human principals (scientists and
  engineers working through the ingest API).
- ``silver`` and ``gold`` are written **only by service accounts** running
  pipelines. Humans - data stewards included - shape those layers by
  configuring the pipeline, never by holding the write themselves.

The entry rule is separate from, and orthogonal to, the write rule. A layer's
``derived_from`` says what a *promotion* into it may read; it does not say that
a promotion is the only way in. Data that is already in a layer's form when it
reaches Huron - a streaming feed, an instrument, published reference data -
enters that layer directly, with an external-provenance block in place of the
lower-layer references (``design/layer-silver.html`` section 4). Raw, bronze
and silver accept such an entry; **gold never does**, because invariant K
requires a derivation record on every product version. A dataset that entered
at silver has no raw and no bronze and never will.

:func:`ensure_layer_writable` enforces the kind half of that rule
independently of role bindings, so even a mis-seeded binding cannot let a
user commit to silver or gold (defense in depth; the binding layer enforces
the same rule through the ``pipeline`` role).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import DomainError


class Layer(StrEnum):
    RAW = "raw"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class LayerAction(StrEnum):
    READ = "read"
    WRITE = "write"


class LayerWorkflowError(DomainError):
    code, status_code = "LAYER_WORKFLOW_VIOLATION", 409


class LayerWriteForbidden(DomainError):
    code, status_code = "LAYER_WRITE_FORBIDDEN", 403


@dataclass(frozen=True, slots=True)
class LayerSpec:
    layer: Layer
    #: Layers a promotion into this layer may read from. Empty for raw:
    #: raw enters the lake from outside, through ingest.
    derived_from: tuple[Layer, ...]
    #: Whether human principals may hold ``data.write`` here. False means
    #: service accounts only.
    principal_writable: bool
    #: Whether data may enter the lake at this layer without descending from
    #: a lower one. False for gold alone: a product version without a
    #: derivation record is not a product (invariant K).
    accepts_direct_entry: bool
    #: The deployable that produces this layer (documentation, not dispatch).
    produced_by: str
    description: str


LAYER_SPECS: dict[Layer, LayerSpec] = {
    Layer.RAW: LayerSpec(
        layer=Layer.RAW,
        derived_from=(),
        principal_writable=True,
        accepts_direct_entry=True,
        produced_by="prepare",
        description="Authoritative files as deposited, committed atomically.",
    ),
    Layer.BRONZE: LayerSpec(
        layer=Layer.BRONZE,
        derived_from=(Layer.RAW,),
        principal_writable=True,
        accepts_direct_entry=True,
        produced_by="bronze_builder",
        description="Faithful per-dataset extraction of raw into arrays.",
    ),
    Layer.SILVER: LayerSpec(
        layer=Layer.SILVER,
        derived_from=(Layer.BRONZE,),
        principal_writable=False,
        accepts_direct_entry=True,
        produced_by="canonicalizer",
        description=(
            "Canonical, contract-validated arrays, per dataset. Pipeline-only. "
            "The contract defines silver, not the descent: data that arrives "
            "already canonical enters here directly."
        ),
    ),
    Layer.GOLD: LayerSpec(
        layer=Layer.GOLD,
        derived_from=(Layer.SILVER, Layer.BRONZE),
        principal_writable=False,
        accepts_direct_entry=False,
        produced_by="product_runner",
        description="Published analysis products. Pipeline-only.",
    ),
}

#: Promotion order for display and iteration.
LAYER_ORDER: tuple[Layer, ...] = (Layer.RAW, Layer.BRONZE, Layer.SILVER, Layer.GOLD)


def parse_layer(value: str) -> Layer:
    try:
        return Layer(value)
    except ValueError as exc:
        raise LayerWorkflowError(f"unknown layer: {value}") from exc


def required_capability(action: LayerAction, layer: Layer) -> tuple[str, str]:
    """The ``(capability, layer)`` pair to pass to ``rbac.decide()``."""
    return (f"data.{action.value}", layer.value)


def writable_layers_for_kind(principal_kind: str) -> tuple[Layer, ...]:
    """Layers a principal of this kind may ever hold a write on."""
    if principal_kind == "service_account":
        return LAYER_ORDER
    return tuple(layer for layer in LAYER_ORDER if LAYER_SPECS[layer].principal_writable)


def ensure_layer_writable(layer: Layer, principal_kind: str) -> None:
    """Refuse a human write to a pipeline-only layer, whatever the bindings say."""
    if LAYER_SPECS[layer].principal_writable or principal_kind == "service_account":
        return
    raise LayerWriteForbidden(f"layer {layer.value} is written only by pipeline service accounts")


def entry_layers() -> tuple[Layer, ...]:
    """Layers a dataset may declare as its entry point, in promotion order."""
    return tuple(layer for layer in LAYER_ORDER if LAYER_SPECS[layer].accepts_direct_entry)


def validate_entry(layer: Layer) -> None:
    """Refuse a direct entry into a layer that must be derived.

    Entry is how data reaches a layer without descending from a lower one:
    an ingest session at raw, or an external source landing already-shaped
    data at bronze or silver. Gold refuses it - every product version carries
    a derivation record naming pinned inputs, a transform digest and
    parameters (invariant K), so "gold with no inputs" is not a product but a
    silver dataset that has not admitted what it is.
    """
    if not LAYER_SPECS[layer].accepts_direct_entry:
        raise LayerWorkflowError(
            f"{layer.value} does not accept direct entry: every {layer.value} version "
            "needs a derivation record naming its inputs. Canonical data arriving from "
            "outside the lake enters at silver."
        )


def parse_entry_layer(value: str) -> Layer:
    """Parse a dataset's declared entry layer, refusing gold."""
    layer = parse_layer(value)
    validate_entry(layer)
    return layer


def validate_promotion(source: Layer, target: Layer) -> None:
    """Refuse a derivation the workflow does not define (e.g. raw -> gold)."""
    allowed = LAYER_SPECS[target].derived_from
    if not allowed:
        raise LayerWorkflowError(f"{target.value} is not produced from another layer")
    if source not in allowed:
        raise LayerWorkflowError(
            f"{target.value} is derived from "
            f"{', '.join(item.value for item in allowed)}, not {source.value}"
        )


__all__ = [
    "LAYER_ORDER",
    "LAYER_SPECS",
    "Layer",
    "LayerAction",
    "LayerSpec",
    "LayerWorkflowError",
    "LayerWriteForbidden",
    "ensure_layer_writable",
    "entry_layers",
    "parse_entry_layer",
    "parse_layer",
    "required_capability",
    "validate_entry",
    "validate_promotion",
    "writable_layers_for_kind",
]
