---
status: accepted
---

# Metadata schemas compose by `extends`

A Raw metadata schema is an immutable, numbered version of a JSON Schema in one of two kinds. The first is
the organization's base series `org`, which extends nothing. The second is a catalog extension that
extends exactly one `org` version. Extensions never extend extensions. A catalog config names one
extension version. The server composes base, extension, and the config's identity fields and
vocabularies into a single self-contained Draft 2020-12 document. That one document validates metadata
offline in the CLI and authoritatively on the server; patterns run under RE2. We chose this over the
earlier plan's PLATFORM and CATALOG registry with a deprecation state. The spec's `extends_id` already
defines the relationship, and the catalog config is the only binding: a correction is a new version
adopted by a config publish. Consequence: a config publish that changes the schema recomputes Active
and Incomplete for that catalog's settled collections in the same transaction (DT-9, OQ-9.1 (a)).
