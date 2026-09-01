"""The layer workflow: who writes where, and what derives from what."""

from __future__ import annotations

import pytest

from huron.pkg.catalog.layers import (
    Layer,
    LayerAction,
    LayerWorkflowError,
    LayerWriteForbidden,
    ensure_layer_writable,
    entry_layers,
    parse_entry_layer,
    parse_layer,
    required_capability,
    validate_entry,
    validate_promotion,
    writable_layers_for_kind,
)

pytestmark = pytest.mark.unit


def test_humans_write_raw_and_bronze_only() -> None:
    ensure_layer_writable(Layer.RAW, "user")
    ensure_layer_writable(Layer.BRONZE, "user")
    for layer in (Layer.SILVER, Layer.GOLD):
        with pytest.raises(LayerWriteForbidden):
            ensure_layer_writable(layer, "user")
    for layer in (Layer.SILVER, Layer.GOLD):
        ensure_layer_writable(layer, "service_account")
    for layer in (Layer.RAW, Layer.BRONZE):
        with pytest.raises(LayerWriteForbidden):
            ensure_layer_writable(layer, "service_account")
    assert writable_layers_for_kind("user") == (Layer.RAW, Layer.BRONZE)
    assert writable_layers_for_kind("service_account") == (Layer.SILVER, Layer.GOLD)


def test_promotions_follow_the_workflow() -> None:
    validate_promotion(Layer.RAW, Layer.BRONZE)
    validate_promotion(Layer.BRONZE, Layer.SILVER)
    validate_promotion(Layer.SILVER, Layer.GOLD)
    with pytest.raises(LayerWorkflowError):
        validate_promotion(Layer.RAW, Layer.GOLD)
    with pytest.raises(LayerWorkflowError):
        validate_promotion(Layer.BRONZE, Layer.RAW)


def test_entry_is_allowed_everywhere_except_gold() -> None:
    """Data already in a layer's form may enter there without a lower layer.

    The write rule and the entry rule are orthogonal: silver refuses human
    writers but accepts direct entry, because entry says where data came
    from and the write rule says who may commit it.
    """
    assert entry_layers() == (Layer.RAW, Layer.BRONZE, Layer.SILVER)
    for layer in entry_layers():
        validate_entry(layer)
    with pytest.raises(LayerWorkflowError):
        validate_entry(Layer.GOLD)


def test_parse_entry_layer_refuses_gold_by_name() -> None:
    assert parse_entry_layer("silver") is Layer.SILVER
    with pytest.raises(LayerWorkflowError):
        parse_entry_layer("gold")
    with pytest.raises(LayerWorkflowError):
        parse_entry_layer("platinum")


def test_entry_does_not_loosen_the_promotion_rule() -> None:
    """A silver dataset may be entered directly, but never *derived* from raw."""
    validate_entry(Layer.SILVER)
    with pytest.raises(LayerWorkflowError):
        validate_promotion(Layer.RAW, Layer.SILVER)


def test_capability_pairs_and_parsing() -> None:
    assert required_capability(LayerAction.WRITE, Layer.SILVER) == ("data.write", "silver")
    assert required_capability(LayerAction.READ, Layer.RAW) == ("data.read", "raw")
    assert parse_layer("gold") is Layer.GOLD
    with pytest.raises(LayerWorkflowError):
        parse_layer("platinum")
