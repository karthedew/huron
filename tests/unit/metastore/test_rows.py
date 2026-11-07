"""The row helpers of the PostgreSQL adapters: inodes in a ``bigint`` and columns for ``unnest``."""

import pytest

from huron.core.metastore.rows import columns, signed_inode, unsigned_inode


@pytest.mark.parametrize(
    ("inode", "stored"),
    [
        pytest.param(None, None, id="no inode"),
        pytest.param(0, 0, id="zero"),
        pytest.param(2**63 - 1, 2**63 - 1, id="largest positive bigint"),
        pytest.param(2**63, -(2**63), id="smallest inode above bigint"),
        pytest.param(2**64 - 1, -1, id="largest inode"),
    ],
)
def test_an_inode_is_stored_in_twos_complement_and_read_back_unchanged(
    inode: int | None, stored: int | None
) -> None:
    assert signed_inode(inode) == stored
    assert unsigned_inode(stored) == inode


def test_columns_turn_rows_into_one_list_per_position() -> None:
    assert columns([(1, "a", None), (2, "b", 3)]) == [[1, 2], ["a", "b"], [None, 3]]
    assert columns([]) == []


def test_columns_refuse_rows_of_different_lengths() -> None:
    with pytest.raises(ValueError):
        columns([(1, "a"), (2,)])
