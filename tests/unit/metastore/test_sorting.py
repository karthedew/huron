"""Safe parameter binding for browse sort statements."""

import pytest

from huron.core.lake.listing import ListOrder, SortDirection, SortField
from huron.core.metastore.sorting import ListingSql
from tests.support.clock import START


@pytest.mark.parametrize("field", list(SortField))
@pytest.mark.parametrize("direction", list(SortDirection))
def test_sorting_binds_values_separately_from_its_closed_field_names(
    field: SortField, direction: SortDirection
) -> None:
    sql = ListingSql(ListOrder(field, direction), 3)
    value = START.isoformat() if field is SortField.CREATED_AT else "'; drop table catalogs;--"
    bound = START if field is SortField.CREATED_AT else value
    assert sql.values((value, "a"), 20) == (bound, "a", 20)
    assert value not in sql.clause()
    assert f"{field.value}" in sql.clause()
    assert f'collate "C" {direction.value}' in sql.clause()
    assert "limit $5" in sql.clause()
    assert sql.values(None, 20) == (None, None, 20)


def test_legacy_name_positions_bind_both_tie_breaking_values() -> None:
    assert ListingSql(ListOrder(), 4).values("alpha", 20) == ("alpha", "alpha", 20)
