# A schema registry, catalog assignment and collection overrides

Status: accepted (2026-10-29)

## Context

Science domains need their own required metadata, and some collections need more.

## Decision

Versioned JSON Schema documents extend huron-base; a catalog is assigned one entry; a collection may compose an override on top. Assigning a schema re-validates the catalog's collections.

## Consequences

Search across a catalog can rely on its schema's fields. Overrides can only add or tighten, never drop a required field.
