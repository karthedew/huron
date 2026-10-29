# Synchronous commits carrying a base version

Status: accepted (2026-10-29)

## Context

Concurrent pushes to one collection must not lose updates, and the service cannot see the share.

## Decision

A commit is one request applied in one transaction, carrying the collection version the push was based on; a stale base version is refused.

## Consequences

No background workers or idempotency keys. Users run huron pull after a conflict. A lost response is recovered by re-reading the collection.
