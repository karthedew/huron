# User guide

The [glossary](#glossary) at the end defines the Huron terms that this guide uses. This guide tells
you what to do. For the reasons, read [How Huron works](concepts/how-huron-works.md) and the other
concept pages.

## Logging in

```bash
huron config set api_url https://huron.apps.example.org
huron config set issuer https://login.example.org/realms/company
huron login            # device code by default; --browser on a desktop
huron whoami           # your groups and the roles they hold
```

The CLI keeps your tokens in `~/.local/state/huron/tokens.json` (mode 0600) and renews them
automatically.

## Where the CLI keeps its state

The CLI keeps its state in `$XDG_STATE_HOME/huron`. When `XDG_STATE_HOME` is not set or empty, this
state directory is `~/.local/state/huron`. It holds your tokens and one directory for each working
copy, `collections/<collection id>/`. The file `working.json` in that directory holds the stage,
the state of each upload and a commit whose result the CLI did not get.

Two locks prevent two commands from changing the same state at the same time:

- The state lock, `state.lock` in the state directory. A command holds it while it changes the
  configuration, your tokens, a metadata draft or a working copy. When another command holds the
  lock, the command waits for at most 10 seconds. Then it stops with exit code 6:
  `another huron command holds the lock of <directory> for more than 10 seconds`.
- The push lock, `push.lock` in the directory of the working copy. A push holds it until the push
  ends. A second `huron push` of the same working copy stops at once with exit code 6:
  ``another `huron push` of this working copy holds the push lock``. A push of a different working
  copy can run at the same time.

The operating system releases the locks when a command ends, also when you stop or kill it. Never
delete a lock file. A command that runs can hold it.

The locks need a local file system. When the state directory is on NFS, each command that takes a
lock stops with exit code 1:

```text
error: the state directory /home/you/.local/state/huron is on NFS. The CLI needs a local file system for its locks
hint: set `XDG_STATE_HOME` to a directory on a local disk of this machine
```

In the profile of your shell, set `XDG_STATE_HOME` to a directory on a local disk. The CLI does not
move its state to the new directory. Run `huron login` and `huron checkout` again.

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
| Administration | `adm` | roles, directory modes, drift checks and schemas |
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

[How search works](concepts/search.md) tells what a search matches and which collections it finds.

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

[Access and roles](concepts/access-and-roles.md) explains the roles, their scopes and how they
become directory ACLs.

## Where your files are

Each organization has its own directory, often on its own NFS export. `huron org` and
`huron get orgs` show this directory in the `PATH` column, for example `/data1/huron/helio`. A path
marked `(prefix)` is under your `mount_prefix` (`huron config show`), because the organization has
no root of its own. The files of a collection are in the directory of the organization, under the
catalog, the namespaces and the collection: `/data1/huron/helio/heliophysics/solar-wind/ace/run7/`.

`huron push` sends your files to the service, so it does not need the share. `huron status` reads
the share to find unrecorded files, and `huron adm check` reads it to find drift. For these checks,
the machine that you work on must mount the export of the organization at that path.
`huron adm verify-mounts` lists each organization with `ok` or with the problem:

- `missing`: the export is not mounted on this machine.
- `no marker`, `wrong instance` or `wrong org`: ask your storage admin.

When the service configuration no longer declares an organization, `huron adm verify-mounts` marks
it `undeclared` and `huron get orgs` marks its path `(undeclared)`. Its catalogs are still there.
But the CLI cannot find its directory until your operators declare the organization again.

Your operators configure the organizations and who administers them. When the service
configuration declares the organizations, the service refuses `huron create org`.

[The layout of the share](concepts/raw-ingest.md#the-layout-of-the-share) and
[the marker](concepts/raw-ingest.md#the-marker) explain why the CLI checks each directory.

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

[The collection lifecycle](concepts/how-huron-works.md#the-collection-lifecycle) explains the
states of a collection.

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
STAGED  PATH       SIZE       UPLOAD  FROM
add     kp/q1.txt  179.1 KiB  -       /home/you/data/kp-q1.txt
remove  old.h5     -          -       -
Unrecorded files on the share: stray.txt
To push, run `huron push -m "<message>"`. To unstage a path, run `huron rm <path>`
```

`Unrecorded files on the share` lists the files in the directory of the collection that no commit
recorded. When this machine does not mount the share, the line says
`The share is not mounted on this machine` instead. When someone else changed the collection
after the version of your working copy, the first line says
`behind the service's version N` and the hint is `huron pull`.

`UPLOAD` gives the last state of the upload of each staged add that the CLI got from the service:

| UPLOAD | Meaning |
| --- | --- |
| `-` | The CLI did not get a state of the upload yet. |
| `receiving` | The service takes the bytes of the file. |
| `sealing` | The service has all of the file and seals it. |
| `ready` | The service sealed the file. The file waits for the commit. |
| `failed`, `cancelled` or `expired` | The upload ended. The next push starts a new upload of the file. |

When the CLI did not get the result of the last commit, `huron status` says so. Refer to
[Continuing an interrupted push](#continuing-an-interrupted-push).

Each working copy keeps its own stage. `huron status --all` shows each working copy on this
machine that has something staged, with `*` on the current collection. When no working copy has
something staged, the command shows only the current collection and says
`Nothing is staged in any working copy`.

`huron rm <path>` does one of these:

- It unstages an add (`unstaged notes.txt`) or a staged removal (`unstaged removal of old.h5`).
- On a recorded file with nothing staged, it stages the removal of the file
  (`staged removal of old.h5`).

`huron add` reads each file and records its size, its modification time and its SHA-256 hash. The
CLI makes no copy of the file. The push reads the file where you staged it. Thus do not change a
staged file until the push is complete.

`huron add` makes these checks:

- In a directory, it does not follow symbolic links. It does not stage a symbolic link, a special
  file or a file that it cannot read. It gives a warning for each one, for example
  `warning: the CLI did not stage /home/you/results/latest: it is a symbolic link`.
- When you name such a file, the command stops with exit code 2 and stages nothing.
- Paths in the collection that are equal after NFC normalization and case folding, such as `Q1.txt`
  and `q1.txt`, are the same path. When one `huron add` finds two such files, it stops with exit
  code 2 and stages nothing. To give one file a different path, use `--as <path>`.
- Each name in a path in the collection can have at most 206 bytes in UTF-8. A longer name stops
  the command with exit code 2.

Before `push` sends a file, it compares the size and the modification time of the file with the
recorded values. When the file changed, or the CLI cannot read it, the push stops with exit code 2
and names the file:

```text
error: /home/you/data/kp-q1.txt changed after you staged it as kp/q1.txt
hint: to stage the file again, run `huron add /home/you/data/kp-q1.txt --as kp/q1.txt`. To unstage it, run `huron rm kp/q1.txt`
```

The service compares the SHA-256 hash of the bytes that it sealed with the recorded hash. When the
two hashes are not equal, the service refuses the commit with `UPLOAD_INELIGIBLE` and exit code 6.
Then stage the file again with `huron add`, and run `huron push` again.

Before `push` uploads anything, it asks the service whether the service would accept the commit.
In these cases, the push stops with the error and uploads nothing:

- You may not write files to the collection.
- The collection has a pending commit.
- The collection changed after the version of your working copy.

A push can send at most 10,000 changes, adds and removals together. When the stage holds more,
the push stops with exit code 7 before it sends a request:

```text
error: the stage holds 12,000 changes. A push can send at most 10,000 changes
hint: push the changes in parts. To unstage a path, run `huron rm <path>`. Stage the path again after the push
```

To push in parts, unstage some paths with `huron rm <path>`, and push the other changes. Then stage
those paths again with `huron add` or `huron rm`, and push again.

Otherwise, `push` uploads each file to the service and records the batch in one commit. The
service puts the files on the share. When you unstage a file with `huron rm` during its upload,
the commit of that push does not include the file.

If something interrupts the push, run it again. The push does not upload a file again when the
service has its upload and the file did not change.
[Continuing an interrupted push](#continuing-an-interrupted-push) tells what the CLI keeps and what
to do.

[The push, step by step](concepts/raw-ingest.md#the-push-step-by-step) explains what the CLI does
at each step. [When a push stops](concepts/raw-ingest.md#when-a-push-stops) tells what stays on the
share and in the stage.

## Continuing an interrupted push

A push can stop before its end. For example, the connection drops, the service does not answer in
time, or you stop the command. The working copy keeps the state of each upload and of the commit.
In almost every case, run `huron push` again.

The CLI records each upload before it sends the first byte. The next push asks the service for the
state of each upload, and continues from that state:

- It sends only the bytes that the service does not have.
- For a file that the service has completely, it waits for the seal. The wait lasts at most the
  hook timeout, `upload_hook_timeout`, a setting of the service (15 minutes by default). When the
  seal does not end in that time, the push stops with exit code 8:
  `the service did not seal <path> in <seconds> seconds`. Run `huron push` again.
- It does not send a file again when the service sealed its upload.

A timeout or an interruption does not make a second upload of a file. The CLI sends a file again
from its first byte only when the service ended the upload or does not have it.

The CLI sends a file in parts of at most 64 MiB. When the connection drops during the last part,
the CLI asks the service how many bytes arrived. When bytes of that part arrived, the push
continues. When no byte of that part arrived, the push stops with exit code 1:

```text
error: the upload service at … is unreachable: …
hint: run `huron push` again. The next push continues the upload
```

When the connection drops during a different part, the push stops with the same error and hint.

The CLI saves each commit in the working copy before it sends it. When the push does not get the
result of the commit, the commit stays saved, and `huron status` shows this line:

```text
The CLI did not get the result of the commit request <request ID>. To get the result, run `huron push`
```

Then the next `huron push` asks the service for the result of that request. The CLI never guesses
the result. This push sends no other changes, and it does one of these:

| Result | What the push does | What you do |
| --- | --- | --- |
| The commit succeeded. | It unstages the committed changes and records the new version: `version 4 → 5, +1 −1 files`. | When `huron status` still shows staged changes, run `huron push` again. |
| The service still works on the commit. | It gets the state again every 5 seconds, for at most 600 seconds. Then it stops with exit code 1: `the service accepted the commit, but did not finish it in 600 seconds`. The commit stays saved. | Run `huron push` again later. |
| The service blocked a step of the commit. | It waits in the same way. Then it stops with exit code 6: `the service accepted the commit, but a step of it is blocked [PUBLICATION_BLOCKED]`. The commit stays saved. | Ask a platform administrator to resolve the commit request. Then run `huron push`. |
| The service refused the commit. | It shows the error of the refusal. The CLI clears the saved commit and keeps the stage. | Correct the cause that the error gives. Then run `huron push`. |
| A platform administrator abandoned the commit. | It stops with exit code 6: `a platform administrator abandoned the commit`. The CLI clears the saved commit and keeps the stage. | Run `huron push` again. |
| The service does not have the commit. | It sends the same commit again, with the same request ID. Then it does what the row of the result of that commit tells. | Do what the row of that result tells. |

A push waits for the result of a new commit in the same way.

While the working copy has a commit whose result the CLI did not get, `huron add`, `huron rm`,
`huron pull` and `huron checkout` stop with exit code 6 and change nothing:

```text
error: the CLI did not get the result of the last commit of heliophysics.solar-wind.run7
hint: run `huron push` to get the result. Then run the command again
```

`huron checkout` also stops when the current working copy has such a commit. These commands stop
with the same error before they change something on the service:

- `huron create collection`, when the current working copy has such a commit.
- `huron activate collection`, when the current working copy or the working copy of the
  collection has such a commit.
- `huron publish meta`, `huron set override` and `huron unset override`, in the same cases as
  `huron activate collection`, when a working copy of the collection is at the version of the
  collection.

Run `huron push` to get the result. Then run the command again.

## When someone else changed the collection

Each commit carries the version of your working copy. If someone published metadata or pushed
files after the version of your working copy, the push stops before the CLI uploads a file:

```text
error: … is at version 6, but your working copy is at version 5 [BASE_VERSION_CONFLICT]
hint: run `huron pull`
```

Run `huron pull`, then run `huron push` again. Your staged files stay staged.
[Base version conflicts](concepts/raw-ingest.md#base-version-conflicts-and-huron-pull) explains
what `huron pull` changes.

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

[Metadata and schemas](concepts/metadata-and-schemas.md) explains the schemas, the overrides and
what Huron does when metadata does not match its schema.

## Deleting

`huron delete collection solar-wind.run7` deletes every recorded file, the collection and its
directory. Its creator or a catalog admin may delete it. Files that nobody recorded stop the
delete, so you lose nothing of yours.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | failure (also findings from `huron adm check`). Also: a state directory on NFS, or a state file that the CLI cannot read or save or whose format it does not know |
| 2 | usage: wrong arguments, no current collection, no current catalog, a file that `huron add` cannot stage, a staged file that changed or that the CLI cannot read |
| 3 | not logged in |
| 4 | forbidden |
| 5 | not found |
| 6 | conflict: stale version, not empty, name taken. Also: a lock that another command holds. A command that stops because the CLI did not get the result of the last commit. A blocked or abandoned commit |
| 7 | validation: metadata, schema or names, more than 10,000 staged changes |
| 8 | the directory of an organization or the share is missing or not writable, or its marker is missing or names a different instance or organization. Also: the service did not seal an upload |
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
| push | The command that uploads the staged files to the service and records the batch in one commit. |
| pull | The command that updates the working copy to the current version of the collection on the service. |
| share | The NFS exports that hold the directories of the organizations, mounted at the same path on each machine that runs the CLI. |
| root | An absolute path that the service configuration sets for an organization. The directory of the organization is then `<root>/<name>`. Without a root, the directory is under the `mount_prefix`. |
| marker | The `.huron` file in the directory of an organization. It names the instance of the service and the organization. The CLI touches the directory only when its marker names this instance and this organization. An organization without its own marker uses the marker at the mount prefix, which names only the instance. |
