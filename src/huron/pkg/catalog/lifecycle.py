"""Pure dataset lifecycle vocabulary.

The states a dataset moves through, and nothing else: no transitions, no
I/O, no framework import. The API stores the member name on the dataset
record and the services that retire or supersede datasets decide the
transitions, so this module can be imported by anything that needs to name
a state.
"""

from __future__ import annotations

from enum import StrEnum


class DatasetLifecycle(StrEnum):
    """Where a dataset stands in its life, as the member name it is stored under.

    Every dataset is created ``ACTIVE``. ``RETIRED`` is the state a project
    admin's retire operation moves it to; ``SUPERSEDED`` marks a dataset
    that a successor has replaced. Each member's value equals its name, so
    the stored string and the enum member read the same.
    """

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    SUPERSEDED = "SUPERSEDED"
