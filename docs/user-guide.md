# User guide

The [glossary](#glossary) at the end defines the Huron terms that this guide uses.

## Logging in

```bash
huron config set api_url https://huron.apps.example.org
huron config set issuer https://login.example.org/realms/company
huron login            # device code by default; --browser on a desktop
huron whoami           # your groups and the roles they hold
```

The CLI keeps your tokens in `~/.local/state/huron/tokens.json` (mode 0600) and renews them
automatically.

## Finding your way

Huron works like `oc`. One catalog is current, as one project is current in OpenShift.
Identifiers are relative to the current catalog. One organization is current too. The CLI lists
catalogs in the current organization and creates them there. `huron --help` groups the commands by
their purpose:

| Panel | Commands | Purpose |
| --- | --- | --- |
| Catalog | `org`, `catalog`, `get`, `describe`, `tree`, `search`, `checkout` | finding your way, searching and selecting a collection |
| Collection | `status`, `add`, `rm`, `pull`, `push`, `edit`, `validate`, `publish`, `activate` | working on the current collection |
| Manage | `create`, `delete`, `set`, `unset` | creating, deleting and configuring organizations, catalogs, namespaces and collections |
| Administration | `adm` | roles, directory ACLs, drift checks and schemas |
| Settings | `login`, `logout`, `whoami`, `config` | who you are and the configuration of the CLI |

```bash
huron org                          # the organizations you can see; * marks the current one
                                   # (deleting it with huron delete org clears it)
huron org helio                    # make helio current (clears a current catalog of another org)
huron catalog                      # the current organization's catalogs, * on the current one,
                                   # and the current collection
huron catalog heliophysics         # make heliophysics current, and its organization too
huron get catalogs                 # the current organization's catalogs, as a plain listing
huron get catalogs -A              # every organization's catalogs (--org <name> for another one)
huron tree                         # its namespaces, with every collection as a leaf
huron get collections              # every collection in the catalog
huron get collections solar-wind   # only those directly in solar-wind
huron checkout                     # choose a collection namespace by namespace
huron status                       # the current collection and what is staged
```

`huron tree` prints the full identifier of each collection. You can copy that identifier into
`huron checkout <identifier>`, also while another catalog is current. When an identifier names
nothing in the current catalog, the CLI resolves it as written.

Without an identifier, `huron checkout` asks you to choose, one level at a time: a namespace
(shown as `name/`), a collection in it, or `..` for the level above. This prompt needs a terminal.
In a script, name the collection.

## Finding things

```bash
huron get namespaces                    # the top level of the current catalog
huron get namespaces solar-wind         # its children
huron search -q "parker" -l site=a      # searches the current catalog
huron describe collection solar-wind.run7
huron get files solar-wind.run7
huron get log solar-wind.run7
```

To work in another catalog and keep the current one, put `--catalog <name>` before the command, as
in `huron --catalog <name> get collections`. Then `huron catalog` and `huron status` show the
organization of that catalog. The saved catalog does not change.

## Who has access

Roles belong to LDAP groups, never to people. `huron whoami` shows your groups and the roles they
hold. `huron get grants` shows who holds which role in a catalog:

```bash
huron get grants                        # the current catalog
huron get grants --catalog geoscience   # another one
huron get grants --org helio            # the organization-wide groups of each role
```

For a catalog, the command prints one row for each role and group, with the `SOURCE` of the group:

- `platform`: the group of the platform admins.
- `organization <org>`: a group that holds the role through the organization, in every catalog of
  that organization.
- `catalog`: a group with a grant on this catalog only.

A group can show two times for one role, one time for each source. The grants of a catalog add
groups. They cannot exclude a group that the catalog inherits from its organization. Thus a catalog
that must stay restricted has its own groups and no organization-wide readers.

`huron -o json get grants` (or `-o yaml`) gives the same rows with the fields `role`, `group` and
`scope`. `--org` prints the groups of the organization for `org_admin`, `catalog_admin`,
`contributor` and `reader`.

To get a role, ask an administrator of the catalog or of the organization to add you to the
applicable LDAP group. The change applies at your next `huron login`.

## Where your files are

Each organization has its own directory, often on its own NFS export. `huron org` and
`huron get orgs` show this directory in the `PATH` column, for example `/data1/huron/helio`. A path
marked `(prefix)` is under your `mount_prefix` (`huron config show`), because the organization has
no root of its own. The files of a collection are in the directory of the organization, under the
catalog, the namespaces and the collection: `/data1/huron/helio/heliophysics/solar-wind/ace/run7/`.

The machine that you work on must mount the export of each organization that you write to, at that
path. `huron adm verify-mounts` lists each organization with `ok` or with the problem:

- `missing`: the export is not mounted on this machine.
- `no marker`, `wrong instance` or `wrong org`: ask your storage admin.

When the service configuration no longer declares an organization, `huron adm verify-mounts` marks
it `undeclared` and `huron get orgs` marks its path `(undeclared)`. Its catalogs are still there.
But the CLI cannot find its directory until your operators declare the organization again.

Your operators configure the organizations and who administers them. When the service
configuration declares the organizations, the service refuses `huron create org`.

## In a browser

The Huron web app shows the same catalog, read-only. Open its address (your operators have it).
Choose **Sign in with your company account** and use the same account as for the CLI. In the web
app, you can:

- switch between the organizations that you can see.
- browse catalogs, namespaces and collections with their metadata, files, commits, activity and
  schema.
- search a catalog or a whole organization.

You make changes with the CLI. Where you could make a change, the page shows the `huron` command to
run. The web reads your groups when you sign in. After a change to your groups, sign out and sign in
again.

## Creating a collection

```bash
huron create collection solar-wind.run7
```

Huron reserves the name. Then it does these steps:

1. It asks for each required metadata field of the catalog schema, and it offers the optional
   fields.
2. It creates the directory with the applicable permissions.
3. It activates the collection.
4. It writes `metadata.json` next to your files.
5. It selects the collection as the current collection.

Use `--metadata file.json` to skip the questions. Use `--draft` to stop before activation. Then run
`huron activate collection` later. With `--draft`, Huron stops after step 1, and the draft becomes
the current collection.

## Staging and pushing files

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
Unrecorded files on the share: stray.txt
To push, run `huron push -m "<message>"`. To unstage a path, run `huron rm <path>`
```

`Unrecorded files on the share` lists the files in the directory of the collection that no commit
recorded. When this machine does not mount the share, the line says
`The share is not mounted on this machine` instead. When someone else changed the collection
after the version of your working copy, the first line says
`behind the service's version N` and the hint is `huron pull`.

Each working copy keeps its own stage. `huron status --all` shows each working copy on this
machine that has something staged, with `*` on the current collection. When no working copy has
something staged, the command shows only the current collection and says
`Nothing is staged in any working copy`.

`huron rm <path>` does one of these:

- It unstages an add (`unstaged notes.txt`) or a staged removal (`unstaged removal of old.h5`).
- On a recorded file with nothing staged, it stages the removal of the file
  (`staged removal of old.h5`).

Before `push` copies anything, it asks the service whether the service would accept the commit. In
these cases, the push stops with the error and copies nothing onto the share:

- You may not write files to the collection.
- The collection changed after the version of your working copy.

Otherwise, `push` copies each file onto the share and records the batch in one commit.

If something interrupts the push, run it again. The push does not copy a file again when it copied
that file before.

## When someone else changed the collection

Each commit carries the version of your working copy. If someone published metadata or pushed
files after the version of your working copy, the push stops before the CLI copies a file:

```text
error: … is at version 6, but your working copy is at version 5 [BASE_VERSION_CONFLICT]
hint: run `huron pull`
```

Run `huron pull`, then run `huron push` again. Your staged files stay staged.

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

`huron delete collection solar-wind.run7` deletes every recorded file, the collection and its
directory. Its creator or a catalog admin may delete it. Files that nobody recorded stop the
delete, so you lose nothing of yours.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | failure (also findings from `huron adm check`) |
| 2 | usage: wrong arguments, no current collection, no current catalog |
| 3 | not logged in |
| 4 | forbidden |
| 5 | not found |
| 6 | conflict: stale version, not empty, name taken |
| 7 | validation: metadata, schema or names |
| 8 | the directory of an organization or the share is missing or not writable, or its marker is missing or names a different instance or organization |
| 130 | cancelled |

An error prints `error: <message> [<code>]` and often a `hint:` line.
[api-errors.md](api-errors.md) lists the codes.

## Glossary

| Term | Meaning |
| --- | --- |
| organization | The top level of Huron. An organization holds catalogs and has its own directory on the share. LDAP groups hold its organization-wide roles. One organization is current in the CLI. |
| catalog | A tree of namespaces and collections in one organization, with one metadata schema. One catalog is current in the CLI, and identifiers are relative to it. |
| namespace | A level in a catalog. A namespace holds other namespaces. It can hold collections when it allows them (`--allow-collections`). |
| collection | A set of files in one directory on the share, with its metadata, in a namespace of a catalog. A collection has a version, which `huron status` shows. |
| identifier | The full name of a namespace or a collection: the catalog, the namespaces and the name, with dots between them, as in `heliophysics.solar-wind.run7`. |
| working copy | The record of one collection on this machine: the version of the collection that it holds, the stage and your metadata draft. `huron checkout` records one. |
| current collection | The working copy that the commands of the Collection panel use. `huron checkout` selects it. |
| stage | The adds and removals that the next push holds. Each working copy has its own stage. `huron add` and `huron rm` change it. |
| push | The command that copies the staged files onto the share and records the batch in one commit. |
| pull | The command that updates the working copy to the current version of the collection on the service. |
| share | The NFS exports that hold the directories of the organizations, mounted at the same path on each machine that runs the CLI. |
| root | An absolute path that the service configuration sets for an organization. The directory of the organization is then `<root>/<name>`. Without a root, the directory is under the `mount_prefix`. |
| marker | The `.huron` file in the directory of an organization. It names the instance of the service and the organization. The CLI touches the directory only when its marker names this instance and this organization. An organization without its own marker uses the marker at the mount prefix, which names only the instance. |
