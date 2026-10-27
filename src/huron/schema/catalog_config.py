"""Immutable catalog configuration and exact metadata schema references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from huron.schema import validator
from huron.schema.naming import check_segment

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any


@dataclass(frozen=True, slots=True)
class SchemaRef:
    """One strictly named metadata schema at an exact positive integer version."""

    name: str
    version: int

    def __post_init__(self) -> None:
        """Reject invalid names and noninteger or nonpositive versions.

        Raises:
            ValueError: If the version is not a positive integer.
        """
        check_segment(self.name)
        if type(self.version) is not int or self.version < 1:
            raise ValueError("schema version must be a positive integer")


@dataclass(frozen=True, slots=True)
class Problem:
    """A validation failure at an RFC 6901 instance pointer."""

    where: str
    rule: str
    message: str


class ConfigError(ValueError):
    """All catalog configuration failures, ordered by their instance pointers."""

    def __init__(self, problems: Iterable[Problem]) -> None:
        """Own a nonempty, deterministically ordered collection of failures.

        Args:
            problems: Configuration validation failures.

        Raises:
            ValueError: If no failures were supplied.
        """
        self.problems = tuple(sorted(problems, key=lambda p: (p.where, p.rule, p.message)))
        if not self.problems:
            raise ValueError("configuration errors require at least one problem")
        super().__init__("; ".join(f"{p.where}: {p.message}" for p in self.problems))


def _problems(document: object) -> list[Problem]:
    instance = dict(document) if isinstance(document, Mapping) else document
    failures = [
        Problem(
            "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in e.path),
            str(e.validator),
            e.message,
        )
        for e in validator("catalog-config-v1.json").iter_errors(cast("Any", instance))
    ]
    if not isinstance(document, Mapping):
        return failures
    schema = document.get("schema")
    versions = [("/config_version", document.get("config_version"))]
    if isinstance(schema, dict):
        versions.append(("/schema/version", schema.get("version")))
    for where, value in versions:
        if isinstance(value, float) and value.is_integer():
            failures.append(
                Problem(where, "type", "expected an integer, not a floating-point value")
            )
    return failures


@dataclass(frozen=True, slots=True)
class CatalogConfig:
    """An owned catalog value with display and operator snapshot-policy annotations."""

    catalog: str
    schema: SchemaRef
    config_version: int | None = None
    title: str | None = None
    snapshot_class: str | None = None

    def __post_init__(self) -> None:
        """Validate direct construction against the same document contract.

        Raises:
            ConfigError: If any catalog field violates the contract.
        """
        document: dict[str, object] = {
            "catalog": self.catalog,
            "schema": {"name": self.schema.name, "version": self.schema.version},
        }
        for key in ("config_version", "title", "snapshot_class"):
            value = getattr(self, key)
            if value is not None:
                document[key] = value
        if problems := _problems(document):
            raise ConfigError(problems)

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> CatalogConfig:
        """Validate a document and retain only immutable owned values.

        Args:
            document: A catalog configuration or stored configuration receipt.

        Returns:
            The validated value, independent of mutable input mappings.

        Raises:
            ConfigError: If document fields violate the configuration contract.
        """
        if problems := _problems(document):
            raise ConfigError(problems)
        schema = cast("dict[str, object]", document["schema"])
        return cls(
            catalog=cast("str", document["catalog"]),
            schema=SchemaRef(cast("str", schema["name"]), cast("int", schema["version"])),
            config_version=cast("int | None", document.get("config_version")),
            title=cast("str | None", document.get("title")),
            snapshot_class=cast("str | None", document.get("snapshot_class")),
        )
