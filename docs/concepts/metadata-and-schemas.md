# Metadata and schemas

Each collection has metadata: one JSON object that describes the files of the collection. A schema
tells which fields the metadata must have and which values they can hold. The schema registry
keeps the schemas, and each catalog uses one of them. A collection can add a schema override to the
schema of its catalog. The service validates the metadata against the result, and the result sets
the state of the collection. This page tells how the registry, the overrides, the validation, the
CLI commands, the `metadata.json` sidecar and the search use the metadata.

## From the registry to the metadata

The service keeps the metadata in its PostgreSQL database. The database is the source of truth.
The schema that validates the metadata of one collection comes from these parts:

```text
  huron-base v1            platform schema, seeded by the service
        ▲
        │ extends
  helio-obs v2             organization schema (optional)
        ▲
        │ assigned to
  catalog heliophysics     one schema for each catalog
        │
        │ composed with the override of the collection (optional)
        ▼
  schema of the collection ──validates──▶ metadata of the collection
```

In this figure, `helio-obs` is an example name. `extends` and the override use the same
composition rules ([How extends composes schemas](#how-extends-composes-schemas)). The service composes the chain
from `huron-base` down to the collection.

## The schema registry

A registry entry is one version of a named schema. Each entry has these parts:

- a name, which follows the naming rules of catalogs, namespaces and collections.
- a version, which the service sets. It is one more than the highest version of that name in that
  scope. The first version is 1.
- a scope: the platform, or one organization.
- the ID of the entry that it extends. Only the platform schema `huron-base` extends nothing.
- the schema document.

The service never changes an entry after it publishes it. To change a schema, publish a new
version. A new version changes no catalog ([Assigning a schema to a catalog](#assigning-a-schema-to-a-catalog)).

| Action | Command | Role |
| --- | --- | --- |
| Publish a platform schema | `huron adm publish schema platform <name> <file> --extends <id>` | Platform Admin |
| Publish an organization schema | `huron adm publish schema <org> <name> <file> --extends <id>` | Org Admin |
| List the schemas | `huron get schemas [org]` | See below |
| Show one entry | `huron describe schema <id>` | See below |
| Show the composed document | `huron describe schema <id> --resolved` | See below |

`huron get schemas` without an organization lists the platform schemas. Each user with a login can
see the platform schemas. The schemas of an organization are visible to the users who can see
that organization. The listing sorts the entries by name, with the newest version of each name
first. Its columns are `ID`, `NAME`, `VERSION`, `SCOPE` and `EXTENDS`.

`--extends` takes the ID of an entry. To find the ID of `huron-base`, run `huron get schemas`. A
successful publish prints `published <name> v<version> (<id>)`.

## The allowed subset of JSON Schema

A schema document uses a subset of JSON Schema 2020-12. The root of the document can have only
these keywords:

- `type`, which is necessary and must be `object`.
- `properties`, `required`, `title`, `description` and `$schema`.
- `additionalProperties`, as `true` or `false`.

Each property must have a `type`: `string`, `number`, `integer`, `boolean`, `array` or `object`.
A property can also have these keywords:

- `title`, `description` and `default`.
- `enum`, `const`, `minimum` and `maximum`.
- `minLength`, `maxLength` and `pattern`. A pattern must be a valid RE2 expression.
- `format`, with one of the values `date`, `date-time`, `email` and `uri`.
- `items`, `minItems`, `maxItems` and `uniqueItems`, for an array.
- `properties`, `required` and `additionalProperties`, for an object. Here
  `additionalProperties` can also be a property.

The subset has no `$ref`, no conditionals and no `patternProperties`. The service refuses a
document outside the subset with `SCHEMA_INVALID`, and `context.problems` lists each problem.

## How extends composes schemas

Each schema except `huron-base` extends one other entry. Thus each organization schema extends
`huron-base`, directly or through other entries. An organization schema can extend a platform
schema or a schema of the same organization. Composition puts the child on top of the parent with
these rules:

1. The properties merge. When the child defines a property that the parent also defines, the
   definition of the child replaces the full definition of the parent.
2. `required` holds the required fields of the parent and of the child. Thus a child cannot make
   a required field optional.
3. The `title`, `description` and `additionalProperties` of the child replace those of the
   parent. When the child does not have one of them, the value of the parent stays.
4. The child cannot change the `type` of a property that the parent requires. The child can change
   the type of a property that the parent does not require.

Rule 1 has a consequence. To keep a constraint of the parent on a property that the child
redefines, write the constraint again in the child.

For example, a parent defines `title` as a string with `minLength: 1` and `maxLength: 200`.
A child that sets only `type: string` and `maxLength: 80` removes the minimum length constraint.
To keep a nonempty title, the child must also set `minLength: 1`. Composition replaces a property
definition as a whole, rather than combining its individual constraints.

The service refuses a schema that breaks rule 4 with `SCHEMA_INCOMPATIBLE`. It also refuses a
schema without a parent with that code. It refuses a parent of another organization with
`SCHEMA_SCOPE`.

`huron-base` v1 requires two fields and offers seven more:

| Field | Type | Required |
| --- | --- | --- |
| `title` | string, 1 to 200 characters | yes |
| `description` | string, at least 1 character | yes |
| `keywords` | array of unique strings | no |
| `contacts` | array of objects with `name` (necessary) and `email` | no |
| `instrument`, `campaign` | string | no |
| `start_time`, `end_time` | string in the `date-time` format | no |
| `labels` | object of string values | no |

`huron-base` allows fields that it does not define (`additionalProperties` is `true`).

## Assigning a schema to a catalog

Each catalog uses exactly one registry entry, at one version. `huron create catalog --schema <id>`
sets that entry. Without `--schema`, the catalog uses the newest version of `huron-base`.
`huron describe catalog` shows the name, version and ID of the schema of the catalog.

A new version of a schema changes no catalog. To use a new version, a Catalog Admin, or a role
above it, assigns it:

```bash
huron adm assign schema <schema_id>                     # the current catalog
huron adm assign schema <schema_id> --catalog geoscience
```

The entry must be a platform schema or a schema of the organization of the catalog. Otherwise the
service refuses it with `SCHEMA_SCOPE`.

The assignment re-validates the collections of the catalog in the same transaction:

1. The service reads each active and incomplete collection of the catalog. Draft collections stay
   as they are.
2. It validates the metadata of each collection against the new schema of the catalog, composed
   with the override of the collection.
3. A collection that passes becomes active. A collection that fails becomes incomplete.
4. When the state of a collection changes, its version increases by 1. The audit log records
   `collection.mark_active` or `collection.mark_incomplete`.

The CLI prints the counts, for example
`heliophysics now uses helio-obs v2: 40 active, 3 incomplete, 5 changed`. A working copy of a
changed collection is then behind the service. Its next push stops with `BASE_VERSION_CONFLICT`
([When someone else changed the collection](../user-guide.md#when-someone-else-changed-the-collection)).

With a lake, the service then writes the `metadata.json` of each active and incomplete collection
whose document changed. Thus each file names the new schema
([The metadata.json sidecar](#the-metadatajson-sidecar)). When that disk work fails, the
assignment stays, and `huron adm check` reports `sidecar_stale`.

## Collection schema overrides

A schema override is a schema document that one collection carries. It is not a registry entry.
The service composes it on top of the schema of the catalog, with the rules of
[How extends composes schemas](#how-extends-composes-schemas). An override uses the same subset of
JSON Schema, so its root must have `"type": "object"`. This override adds a required field:

```json
{
  "type": "object",
  "properties": {
    "run_number": { "type": "integer", "minimum": 1 }
  },
  "required": ["run_number"]
}
```

A Contributor sets and clears the override of a collection:

```bash
huron set override extra-fields.json      # the current collection
huron unset override solar-wind.run7
```

`huron set override` validates the document against the subset before it sends a request. A
document outside the subset stops the command with exit code 7. When the working copy has a
metadata draft, the CLI sends the draft and the override in one request. The service validates
them together, and the CLI deletes the metadata draft after the change.

`huron unset override` clears the override. The service then validates the metadata against the
schema of the catalog alone.

A later assignment can give a catalog schema that the override contradicts. Then the metadata has
one problem with the rule `schema_incompatible`, and the collection becomes incomplete.

## Collection states and validation

Huron uses the word draft for two different things:

- A draft collection is a collection in the state `draft`. The service holds it, but it has no
  directory on the share.
- A metadata draft is the file `metadata.draft.json` in your working copy, under
  `~/.local/state/huron/collections/<collection-id>/` (or `$XDG_STATE_HOME/huron`). Only the CLI
  on your machine reads it.

The state of a collection controls how the service treats invalid metadata:

| State | Directory | Metadata that does not satisfy the schema |
| --- | --- | --- |
| `draft` | no | The service accepts it and returns the problems. Activation refuses it. |
| `active` | yes | The service refuses it with `METADATA_INVALID`. |
| `incomplete` | yes | The service refuses it with `METADATA_INVALID`. |

```text
          activate             re-validation fails
  draft ───────────▶ active ─────────────────────▶ incomplete
                       ▲                                │
                       └────────────────────────────────┘
               re-validation passes, or a valid change
```

When the service creates a draft collection, it does not validate the metadata against the schema.
It only makes sure of three things. The metadata is a JSON object, JSON can hold each value, and
the metadata is at most 1 MiB. Activation then requires metadata without problems.

A collection becomes incomplete only when a schema assignment re-validates it. A metadata change
that satisfies the schema makes an incomplete collection active again. An incomplete collection
still accepts pushes, and `huron adm check` reports it as `incomplete`.

Each problem has a `path` (a JSON pointer into the metadata), a `message` and a `rule`. The rule
is the JSON Schema keyword that failed, or one of `json`, `size`, `type` and
`schema_incompatible`. The CLI prints at most 20 problems, one on each line, as
`<path>: <message>`.

## The walkthrough

The walkthrough asks for the metadata one field at a time. `huron create collection` runs it
unless you give `--metadata <file>`. `huron edit meta` runs it unless you give `--file <file>`.
The walkthrough reads the schema of the collection from the service and asks in this order:

1. Each required field, in the order of `required`.
2. Each optional field, in alphabetical order. For each one, it asks `Set <field>? (optional)`.

The question shows the `title` of the property, or its name, and its `description`. The type of
the property sets the form of the answer:

| Property | Answer |
| --- | --- |
| with `enum` | Choose one value from the list. |
| `boolean` | Yes or no. |
| `object` with `properties` | The walkthrough asks for each field of the object. |
| `object` without `properties`, such as `labels` | `key=value` pairs, separated by commas. |
| `array` of objects, such as `contacts` | Add one entry at a time. |
| `array` of other values, such as `keywords` | Values separated by commas. |
| `integer` or `number` | A number. |
| other | Text. |

The walkthrough validates each text answer against its property. It asks again until the answer
satisfies the property. Values that you already have show as defaults. The walkthrough keeps the
fields that the schema does not describe.

The walkthrough asks questions in a terminal. In a script, give the metadata in a JSON file with
`huron create collection --metadata` or `huron edit meta --file`.

## Editing, validating and publishing metadata

These commands use the current collection, or the collection that you name. They need the
Contributor role, or a role above it.

```bash
huron get meta                        # published metadata, draft, override
huron edit meta                       # walkthrough, then save the draft
huron edit meta --file metadata.json  # the file becomes the draft
huron validate meta
huron publish meta
```

Do these steps to change the metadata of a collection:

1. Run `huron edit meta`. The walkthrough starts from your metadata draft, or from the published
   metadata when you have no draft. With `--from-scratch`, it starts from an empty document.
2. Or run `huron edit meta --file <doc.json>`. The CLI asks nothing. The JSON object in the file
   becomes the metadata draft as it is. You cannot use `--file` with `--from-scratch`.
3. Read the result line. Both forms save the metadata draft, also with problems, and print
   ``Draft saved with N problems. To publish it, run `huron publish meta` ``.
4. Run `huron validate meta`. The CLI validates the metadata draft against the schema of the
   collection and sends no change. Without a metadata draft, it validates the published metadata.
5. Run `huron publish meta`. The CLI sends the metadata draft as a merge patch.

`huron validate meta` prints `The metadata is valid`, or it stops with exit code 7 and lists the
problems. The CLI uses the schema that it reads from the service and the same validator as the
service.

`huron publish meta` needs a metadata draft. Without one, it stops with exit code 2 and the hint
`run huron edit meta`. When the collection has a directory, the service writes `metadata.json`
again after the change. After a successful publish, the CLI does these steps:

1. It records the new version in the working copy, when the working copy had the version that the
   CLI read before the publish.
2. It deletes the metadata draft.
3. It prints `published <identifier> at version <N>`.

The patch turns the published metadata into your metadata draft. Thus a field that someone else
published after you started your draft gets the value of your draft. When your draft does not
have that field, the publish deletes it. To compare the two documents
before you publish, run `huron get meta`.

## The merge patch and the version

The CLI sends each metadata change as `PATCH /api/v1/collections/{id}` with the body
`{metadata?, schema_override?}`. The `metadata` member is a JSON merge patch (RFC 7396):

- A member with the value `null` deletes that field.
- A member with an object value merges into the object of that field, one member at a time.
- A member with any other value replaces the value of the field. An array replaces the full array.

```text
  published  {"title": "Run 7", "labels": {"site": "a", "shift": "night"}}
  patch      {"labels": {"site": "b", "shift": null}, "campaign": "PSP"}
  result     {"title": "Run 7", "labels": {"site": "b"}, "campaign": "PSP"}
```

The `schema_override` member is not a merge patch. A document replaces the override, and `null`
clears it. When a request has both members, the service validates the new metadata against the new
override.

A collection has one version, which starts at 1. Each change to the collection increases it by 1.
The changes are metadata, override, activation, commits and state changes from a schema
assignment. The service sends the version in the `ETag` header, as in `"4"`.

Metadata changes, override changes, activation and deletion use the `If-Match` header.
These requests must send exactly one quoted version:

| `If-Match` | Answer of the service |
| --- | --- |
| missing, or not one quoted version | 428 `PRECONDITION_REQUIRED` |
| an older version | 412 `VERSION_CONFLICT`. `context.current_version` gives the current version. |
| the current version | the change |

The CLI shows `VERSION_CONFLICT` with exit code 6 and the hint `run huron pull`.
`huron publish meta` sends the version that it read just before the patch. Thus it gets
`VERSION_CONFLICT` only when another change arrives between that read and the patch. A commit
uses the `base_version` in its body instead of `If-Match`. A stale `base_version` gives
409 `BASE_VERSION_CONFLICT`. Both checks compare against the same collection version.

## The metadata.json sidecar

The service writes a `metadata.json` file into the directory of each active and incomplete
collection. The file keeps the metadata on the share, apart from the service. The service writes
it at these times:

- After activation, by `huron create collection` and `huron activate collection`.
- After each change by `huron publish meta`, `huron set override` and `huron unset override`.
- After a schema assignment of the catalog, when the document of the collection changed.
- At `huron adm repair`, when the file on the share is not the document of the service.

The service writes the bytes that `GET /api/v1/collections/{id}/metadata.json` returns. It writes
the file only when its bytes differ. The file is canonical JSON (RFC 8785) with a
newline at the end, and it holds these members:

| Member | Content |
| --- | --- |
| `huron` | The format of the file, now `1`. |
| `identifier`, `organization`, `catalog` | Where the collection is. |
| `schema` | The `id`, `name` and `version` of the schema of the catalog. |
| `schema_override` | The override of the collection, or `null`. |
| `metadata` | The published metadata. |
| `created_by`, `created_at` | Who created the collection, and when. |

The file does not hold the version or the file count. Thus a push does not make it stale. A
change to the metadata, the override or the schema of the catalog makes it stale. A draft
collection has no `metadata.json`, and the API answers 409 `STATE_CONFLICT` for one.

Editing the sidecar does not update the metadata in the service. To change the published metadata,
use `huron edit meta` and `huron publish meta`. The sidecar is a copy for readers of the share.

`huron adm check` compares the file with the bytes of the service. When the file is missing or
different, it reports the warning `sidecar_stale`
([Reading `huron adm check`](../operator.md#reading-huron-adm-check)).

## Labels and search

`huron-base` defines `labels`, an object whose values are strings. Search can match each label
exactly. In the walkthrough, you give labels as `site=a, shift=night`.

```bash
huron search -q parker                    # identifier, title, description
huron search -l site=a -l shift=night     # both labels must match
huron search --state incomplete
huron --catalog geoscience search -q run  # another catalog
```

`huron search` searches the current catalog and applies these rules:

- `-q` matches text in the identifier, the `title` or the `description`. Case does not matter. The
  API accepts at most 200 characters.
- Each `-l key=value` must match one member of `labels` exactly. A collection must match every
  label that you give. The API also accepts `key:value`.
- `--state` selects the states. Without it, search shows active and incomplete collections.
- Only users who can create collections in the catalog see draft collections. For other users,
  `--state draft` finds nothing.

The results come in the order of their identifiers, one page at a time. Search reads no other
metadata field. For example, search does not read `instrument` or `keywords`.

## Exact large integers

Huron keeps integers of any size with their exact digits, in metadata and in schema documents. A
value such as `9223372036854775808` (2^63) stays exact. RFC 8785 accepts integers only up to
2^53. Huron writes each integer with its decimal digits, also past that limit.

The service refuses values that JSON cannot hold, with the rule `json`:

- NaN and infinity.
- A string that holds a lone surrogate.
- An integer with too many digits for the service to write.

In metadata, the code is `METADATA_INVALID`. In a schema document, it is `SCHEMA_INVALID`.

PostgreSQL can return a large floating-point number as an integer. For example, `-1e31` can come
back as `-10000000000000000000000000000000`. The walkthrough reads an `integer` field with all its
digits, and a `number` field as a floating-point number. The schema view of the web app shows large
integers with their exact digits.

## Related pages

- [Editing metadata](../user-guide.md#editing-metadata) and
  [Creating a collection](../user-guide.md#creating-a-collection) in the user guide.
- [Glossary](../user-guide.md#glossary) of the user guide.
- CLI reference: [`huron edit meta`](/docs/reference/cli/edit/#huron-edit-meta),
  [`huron validate meta`](/docs/reference/cli/validate/#huron-validate-meta),
  [`huron publish meta`](/docs/reference/cli/publish/#huron-publish-meta),
  [`huron set override`](/docs/reference/cli/set/#huron-set-override),
  [`huron unset override`](/docs/reference/cli/unset/#huron-unset-override),
  [`huron search`](/docs/reference/cli/search/),
  [`huron adm publish schema`](/docs/reference/cli/adm/#huron-adm-publish-schema),
  [`huron adm assign schema`](/docs/reference/cli/adm/#huron-adm-assign-schema).
- [Reading `huron adm check`](../operator.md#reading-huron-adm-check) for operators.
- [API error codes](../api-errors.md).
- [How search works](search.md).
- [The metadata.json sidecar](raw-ingest.md#the-metadatajson-sidecar) in How raw ingest works.
