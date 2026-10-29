# User guide

## Logging in

```bash
huron config set api_url https://huron.apps.example.org
huron config set issuer https://login.example.org/realms/company
huron login            # device code by default; --browser on a desktop
huron whoami           # your groups and the roles they hold
```

Tokens are kept in `~/.local/state/huron/tokens.json` (mode 0600) and renewed automatically.

## Finding things

```bash
huron catalog list
huron catalog use heliophysics          # identifiers below are relative to it
huron namespace list
huron collection list solar-wind
huron search -q "parker" -l site=a
huron collection describe solar-wind.run7
huron files solar-wind.run7
```

Readers read files straight from the share, for example
`/projects/huron/helio/heliophysics/solar-wind/run7/`.

## Creating a collection

```bash
huron collection create solar-wind.run7
```

Huron reserves the name, walks you through every required metadata field of the catalog's schema
(and offers the optional ones), creates the directory with the right permissions, activates the
collection, writes `metadata.json` beside your files and checks the collection out. Use
`--metadata file.json` to skip the walkthrough, or `--draft` to stop before activation and run
`huron collection activate` later.

## Adding and removing files

```bash
huron add data/*.h5
huron add results/ --recursive
huron add notes.txt --as docs/notes.txt
huron rm old.h5
huron status
huron push -m "first run"
```

`push` copies each file onto the share, then records the batch in one commit. If the push is
interrupted, run it again; files already copied are not copied twice.

## When someone else changed the collection

Every commit carries the version you checked out. If someone published metadata or pushed files
since, the push is refused:

```text
error: … is at version 6, your copy at 5 [BASE_VERSION_CONFLICT]
hint: run: huron pull
```

Run `huron pull`, then `huron push` again. Your staged files are kept.

## Editing metadata

```bash
huron meta edit          # walk through the fields again
huron meta validate
huron meta publish       # sends the change and rewrites metadata.json
huron meta override set extra-fields.json   # add fields required for this collection only
huron meta override clear
```

## Deleting

`huron collection delete solar-wind.run7` removes every recorded file, the collection and its
directory. Its creator or a catalog admin may delete it. Files nobody recorded stop the delete so
nothing of yours is lost.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | failure (including findings from `huron check`) |
| 2 | usage: wrong arguments, nothing checked out, no catalog selected |
| 3 | not logged in |
| 4 | forbidden |
| 5 | not found |
| 6 | conflict: stale version, not empty, name taken |
| 7 | validation: metadata, schema or names |
| 8 | the share is missing, unmarked or not writable |
| 130 | cancelled |

Errors print `error: <message> [<code>]` and often a `hint:`; codes are listed in
[api-errors.md](api-errors.md).
