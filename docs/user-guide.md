# User guide

## Logging in

```bash
huron config set api_url https://huron.apps.example.org
huron config set issuer https://login.example.org/realms/company
huron login            # device code by default; --browser on a desktop
huron whoami           # your groups and the roles they hold
```

Tokens are kept in `~/.local/state/huron/tokens.json` (mode 0600) and renewed automatically.

## Finding your way

Huron works like `oc`: one catalog is current, as one project is current in OpenShift, and
identifiers are relative to it. One organization is current too, and catalogs are listed and
created in it. `huron --help` groups the commands by what they are for:

| Panel | Commands | For |
| --- | --- | --- |
| Catalog | `org`, `catalog`, `get`, `describe`, `tree`, `search`, `checkout` | finding your way, searching and checking a collection out |
| Collection | `status`, `add`, `rm`, `pull`, `push`, `edit`, `validate`, `publish`, `activate` | working on the checked-out collection |
| Manage | `create`, `delete`, `set`, `unset` | creating, deleting and configuring organizations, catalogs, namespaces and collections |
| Administration | `adm` | roles, directory ACLs, drift checks and schemas |
| Settings | `login`, `logout`, `whoami`, `config` | who you are and how the CLI is set up |

```bash
huron org                          # the organizations you can see; * marks the current one
                                   # (deleting it with huron delete org clears it)
huron org helio                    # make helio current (clears a current catalog of another org)
huron catalog                      # the current organization's catalogs, * on the current one,
                                   # and which collection is checked out
huron catalog heliophysics         # make heliophysics current, and its organization too
huron get catalogs                 # the current organization's catalogs, as a plain listing
huron get catalogs -A              # every organization's catalogs (--org <name> for another one)
huron tree                         # its namespaces, with every collection as a leaf
huron get collections              # every collection in the catalog
huron get collections solar-wind   # only those directly in solar-wind
huron checkout                     # pick a collection namespace by namespace
huron status                       # what is checked out and what is staged
```

`huron tree` prints each collection's full identifier, so you can copy it into
`huron checkout <identifier>`, even while another catalog is current: an identifier that names
nothing in the current catalog is looked up as written. Without an identifier, `huron checkout` asks you to choose, level by
level: a namespace (shown as `name/`), a collection in it, or `..` to go back up. It needs a terminal;
in a script, name the collection.

## Finding things

```bash
huron get namespaces                    # the top level of the current catalog
huron get namespaces solar-wind         # its children
huron search -q "parker" -l site=a      # searches the current catalog
huron describe collection solar-wind.run7
huron get files solar-wind.run7
huron get log solar-wind.run7
```

Put `--catalog <name>` before the command, as in `huron --catalog <name> get collections`, to work
in another catalog without switching; `huron catalog` and `huron status` then show that catalog's
organization, and the saved one is left alone.

## Who has access

Roles belong to LDAP groups, never to people. `huron whoami` shows your groups and the roles they
hold; `huron get grants` shows who holds which role in a catalog:

```bash
huron get grants                        # the current catalog
huron get grants --catalog geoscience   # another one
huron get grants --org helio            # the organization-wide groups of each role
```

For a catalog it prints one row per role and group, with the group's `SOURCE`: `platform` for the
platform admins, `organization <org>` for a group the organization holds the role through in every
one of its catalogs, and `catalog` for a group granted on this catalog alone. A group can show twice
for one role, once per source. A catalog's own grants add groups; they cannot take away one it
inherits from its organization, so a catalog that must stay restricted has its own groups and no
organization-wide readers. `huron -o json get grants` (or `-o yaml`) gives the same rows with the
fields `role`, `group` and `scope`. `--org` prints the organization's groups for `org_admin`,
`catalog_admin`, `contributor` and `reader`. To be given a role, ask an administrator of the catalog
or the organization to add you to the right LDAP group; the change applies at your next
`huron login`.

## Where your files are

Each organization has its own directory, often on its own NFS export: `huron org` and
`huron get orgs` show it in the `PATH` column, such as `/data1/huron/helio`. A path marked
`(prefix)` is under your `mount_prefix` (`huron config show`) because the organization has no root
of its own. A collection's files are in the organization's directory, then the catalog, the
namespaces and the collection: `/data1/huron/helio/heliophysics/solar-wind/ace/run7/`.

The machine you work on must mount the export of every organization you write to, at that path.
`huron adm verify-mounts` lists each organization with `ok`, or what is wrong: `missing` (not
mounted here), `no marker`, `wrong instance` or `wrong org` (ask your storage administrator). An
organization marked `undeclared`, with its path marked `(undeclared)` in `huron get orgs`, is no
longer in the service configuration: its catalogs are still there, but the CLI cannot find its
directory until your operators declare it again.
Organizations themselves, and who administers them, are set up by your operators; `huron create org`
is refused when they are declared in the service configuration.

## In a browser

The Huron web app shows the same catalog, read-only. Open its address (your operator has it),
choose **Sign in with your company account** and sign in as you do for the CLI. You can switch
between the organizations you can see, browse catalogs, namespaces and collections with their
metadata, files, commits, activity and schema, and search a catalog or a whole organization.
Changes are made with the CLI: where you could make one, the page shows the `huron` command to
run. Your groups are read when you sign in, so after a change to your groups, sign out and sign in
again.

## Creating a collection

```bash
huron create collection solar-wind.run7
```

Huron reserves the name, walks you through every required metadata field of the catalog's schema
(and offers the optional ones), creates the directory with the right permissions, activates the
collection, writes `metadata.json` beside your files and checks the collection out. Use
`--metadata file.json` to skip the walkthrough, or `--draft` to stop before activation and run
`huron activate collection` later.

## Adding and removing files

```bash
huron add data/*.h5
huron add results/ --recursive
huron add notes.txt --as docs/notes.txt
huron rm old.h5
huron status
huron push -m "first run"
```

`huron status` shows where you are and what the next push holds:

```text
On collection heliophysics.solar-wind.run7 (version 4, up to date) in catalog heliophysics, organization helio
STAGED  PATH          SIZE       FROM
add     kp/q1.txt     179.1 KiB  /home/you/data/kp-q1.txt
remove  old.h5        -          -
Unrecorded on the share: stray.txt
push with: huron push -m "<message>" · unstage with: huron rm <path>
```

`Unrecorded on the share` lists files in the collection's directory that no commit recorded; it
reads `share not mounted here` when this machine does not mount the share. When someone else
changed the collection since you checked it out, the first line says `behind the service's
version N` and the hint is `huron pull`. Each collection you have checked out keeps its own stage;
`huron status --all` shows every one on this machine that has something staged, with `*` on the
checked-out one; when none has, it shows only the checked-out one and says `nothing staged in any
working copy`.

`huron rm <path>` undoes what is staged for that path: it unstages an add (`unstaged notes.txt`) or
a removal (`unstaged removal of old.h5`). Run on a recorded file with nothing staged, it stages the
file's removal (`staged removal of old.h5`).

Before `push` copies anything, it asks the service whether it would accept the commit: if you may
not write files to the collection, or it changed since your copy, the push stops with the error
and nothing is copied onto the share. Then `push` copies each file onto the share and records the
batch in one commit. If the push is interrupted, run it again; files already copied are not copied
twice.

## When someone else changed the collection

Every commit carries the version you checked out. If someone published metadata or pushed files
since, the push is refused before any file is copied:

```text
error: … is at version 6, your copy at 5 [BASE_VERSION_CONFLICT]
hint: run: huron pull
```

Run `huron pull`, then `huron push` again. Your staged files are kept.

## Editing metadata

```bash
huron get meta           # the published metadata and your draft
huron edit meta          # walk through the fields again (--from-scratch starts empty)
huron edit meta --file metadata.json   # take the draft from a JSON document, nothing asked
huron validate meta
huron publish meta       # sends the change and rewrites metadata.json
huron set override extra-fields.json   # add fields required for this collection only
huron unset override
```

## Deleting

`huron delete collection solar-wind.run7` removes every recorded file, the collection and its
directory. Its creator or a catalog admin may delete it. Files nobody recorded stop the delete so
nothing of yours is lost.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | failure (including findings from `huron adm check`) |
| 2 | usage: wrong arguments, nothing checked out, no catalog selected |
| 3 | not logged in |
| 4 | forbidden |
| 5 | not found |
| 6 | conflict: stale version, not empty, name taken |
| 7 | validation: metadata, schema or names |
| 8 | an organization's directory or the share is missing, unmarked or not writable |
| 130 | cancelled |

Errors print `error: <message> [<code>]` and often a `hint:`; codes are listed in
[api-errors.md](api-errors.md).
