"""The storage-layer workflow: each layer, who may write it, and how data moves between them.

What each layer is, who may write it, and how data is promoted between
layers, as definitions a service composes rather than behaviour it calls.

Definitions only - this module performs no I/O and holds no framework
imports. The API service composes it with ``pkg/rbac`` to answer "may this
principal write this layer of this dataset?", and the pipeline services use
:func:`validate_promotion` to refuse a derivation the workflow does not
define.

The write rule, as an invariant rather than convention:

- ``raw`` and ``bronze`` accept commits from human principals (scientists and
  engineers working through the ingest API).
- ``silver`` and ``gold`` are written **only by service accounts** running
  pipelines. Humans - admins included - shape those layers by
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
the same rule on its side, where silver and gold write authority is
synthesized for service accounts alone and no role in the vocabulary
carries it).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from huron.core.foundation.errors import DomainError


class Layer(StrEnum):
    """The four storage layers, valued as the lower-case codes paths and the API use.

    This enum is the one place the codes are spelled out; the path layout
    and the API both derive their layer names from it.
    """

    RAW = "raw"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class LayerAction(StrEnum):
    """What a principal can do to a layer, named as the suffix of the ``data.*`` capability."""

    READ = "read"
    WRITE = "write"


class LayerWorkflowError(DomainError):
    """A layer name is unknown, or a derivation or entry the workflow does not define."""

    code, status_code = "LAYER_WORKFLOW_VIOLATION", 409


class LayerWriteForbidden(DomainError):
    """A principal of this kind may never write this layer, whatever its bindings say."""

    code, status_code = "LAYER_WRITE_FORBIDDEN", 403


@dataclass(frozen=True, slots=True)
class LayerSpec:
    """The workflow's definition of one layer: provenance, writers, entry and producer.

    Attributes:
        layer: The layer this specification describes.
        description: What the layer holds, for people; not interpreted.
    """

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
    """Turn a layer code from a request or a path into a :class:`Layer`.

    The failure is a :class:`LayerWorkflowError` rather than the enum's own
    ``ValueError`` so that an unknown layer named by a client answers with
    the stable ``LAYER_WORKFLOW_VIOLATION`` code instead of a 500.

    Args:
        value: The layer code, exactly as :class:`Layer` spells it.

    Returns:
        The matching layer.

    Raises:
        LayerWorkflowError: If ``value`` is not one of the four layer codes.
    """
    try:
        return Layer(value)
    except ValueError as exc:
        raise LayerWorkflowError(f"unknown layer: {value}") from exc


def required_capability(action: LayerAction, layer: Layer) -> tuple[str, str]:
    """Return the ``(capability, layer)`` pair to pass to ``rbac.decide()``.

    Layer access is decided on a layer-scoped capability (``data.read`` or
    ``data.write``) plus the layer as a separate argument, never on a
    capability with the layer baked into its name.

    Args:
        action: Whether the principal wants to read or write.
        layer: The layer the action targets.

    Returns:
        The capability name and the layer code, in the order ``decide()``
        takes them.
    """
    return (f"data.{action.value}", layer.value)


def writable_layers_for_kind(principal_kind: str) -> tuple[Layer, ...]:
    """Return the layers a principal of this kind may ever hold a write on.

    Service accounts get silver and gold; every other kind gets the layers
    whose specification marks them ``principal_writable``. The two sets are
    disjoint by design: no kind of principal can write on both sides of the
    human/pipeline boundary.

    Args:
        principal_kind: ``"service_account"`` or ``"user"``, as
            :mod:`huron.core.security.rules` names principal kinds.

    Returns:
        The writable layers, in promotion order.
    """
    if principal_kind == "service_account":
        return (Layer.SILVER, Layer.GOLD)
    return tuple(layer for layer in LAYER_ORDER if LAYER_SPECS[layer].principal_writable)


def ensure_layer_writable(layer: Layer, principal_kind: str) -> None:
    """Refuse writes outside a principal kind's allowed layer surface.

    This is the kind half of the write rule, checked before and independently
    of any role binding: a service account may write silver and gold, and
    any other kind may write only the layers marked ``principal_writable``.
    Returning normally means only that the kind is allowed here; whether
    this particular principal holds ``data.write`` on this dataset is the
    binding layer's question.

    Args:
        layer: The layer about to be written.
        principal_kind: The kind of the principal asking, as
            :mod:`huron.core.security.rules` names kinds.

    Raises:
        LayerWriteForbidden: If principals of this kind may never write
            ``layer``.
    """
    if principal_kind == "service_account" and layer in (Layer.SILVER, Layer.GOLD):
        return
    if LAYER_SPECS[layer].principal_writable and principal_kind != "service_account":
        return
    raise LayerWriteForbidden(f"{principal_kind} principals may not write the {layer.value} layer")


def entry_layers() -> tuple[Layer, ...]:
    """Return the layers a dataset may declare as its entry point, in promotion order.

    Returns:
        Every layer whose specification accepts direct entry: raw, bronze
        and silver, never gold.
    """
    return tuple(layer for layer in LAYER_ORDER if LAYER_SPECS[layer].accepts_direct_entry)


def validate_entry(layer: Layer) -> None:
    """Refuse a direct entry into a layer that must be derived.

    Entry is how data reaches a layer without descending from a lower one:
    an ingest session at raw, or an external source landing already-shaped
    data at bronze or silver. Gold refuses it - every product version carries
    a derivation record naming pinned inputs, a transform digest and
    parameters (invariant K), so "gold with no inputs" is not a product but a
    silver dataset that has not admitted what it is.

    Args:
        layer: The layer the dataset declares as its entry point.

    Raises:
        LayerWorkflowError: If ``layer`` does not accept direct entry.
    """
    if not LAYER_SPECS[layer].accepts_direct_entry:
        raise LayerWorkflowError(
            f"{layer.value} does not accept direct entry: every {layer.value} version "
            "needs a derivation record naming its inputs. Canonical data arriving from "
            "outside the lake enters at silver."
        )


def parse_entry_layer(value: str) -> Layer:
    """Parse a dataset's declared entry layer, refusing gold.

    The two checks it composes, :func:`parse_layer` and
    :func:`validate_entry`, both report through :class:`LayerWorkflowError`,
    so a caller handles one error for an unknown name and a forbidden entry
    alike.

    Args:
        value: The layer code from the dataset's declaration.

    Returns:
        The declared layer, which accepts direct entry.
    """
    layer = parse_layer(value)
    validate_entry(layer)
    return layer


def validate_promotion(source: Layer, target: Layer) -> None:
    """Refuse a derivation the workflow does not define (e.g. raw -> gold).

    A promotion into ``target`` may read only the layers its specification
    lists in ``derived_from``. Raw lists none, since it enters the lake from
    outside; asking to promote anything into raw is refused on that ground
    before the source is even considered.

    Args:
        source: The layer the promotion reads from.
        target: The layer the promotion writes.

    Raises:
        LayerWorkflowError: If ``target`` is not produced from another layer
            at all, or is not produced from ``source``.
    """
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
