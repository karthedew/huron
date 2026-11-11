# How raw ingest works

Huron does not hold your files itself. The files of a collection stay on the share, in one
directory for each collection. The CLI is the only part of Huron that writes to the share. It
copies your staged files into the directory of the collection. Then it records them in one commit
on the service. The service records the size and the SHA-256 hash of each file, and the share holds
the bytes. This page tells how each step works and what the CLI checks before it writes.

## The layout of the share

Each organization has one directory, `<root>/<org>`. The root comes from the service configuration.
An organization without a root uses the `mount_prefix` of the CLI, which is `/projects/huron` by
default. Below the directory of the organization, each catalog, namespace and collection has its own
directory:

```text
<root>/<org>/<catalog>/<namespace>/.../<collection>/

/data1/huron/                     root of the organization
  helio/                          organization, with its .huron marker
    heliophysics/                 catalog
      solar-wind/                 namespace
        ace/                      namespace that allows collections
          run7/                   collection
            metadata.json         sidecar that the CLI writes
            kp/q1.txt             a recorded file
```

The API gives each path relative to the root, and the path starts with the name of the
organization, as in `helio/heliophysics/solar-wind/ace/run7`. The CLI finds the root of the
organization from the first segment of that path. A path with an empty segment, `.` or `..` is
outside the share, and the CLI refuses it.

Inside a collection, a file has a relative path, such as `kp/q1.txt`. Huron ignores case when it
checks path uniqueness. Thus it cannot record `Data.h5` and `data.h5` as separate files. This rule
does not change how the filesystem treats names. Keep the recorded spelling when you replace a file.

Some names belong to Huron: `metadata.json` at
the top of the collection, any segment that starts with `.huron`, and any segment that ends with
`.huron-part`. You cannot stage a file with one of these names.

A relative path has at most 1,024 UTF-8 bytes, with at most 206 bytes in each segment. It uses `/`
between segments and has no leading or trailing `/`. Huron refuses empty segments, `.` and `..`,
backslashes and control characters. Unicode names must use NFC normalization, a standard form for
equivalent characters.

[Where your files are](../user-guide.md#where-your-files-are) tells how to find the directory of
an organization on your machine.

## The marker

The marker is the `.huron` file in the directory of an organization. It is a small JSON document
with the fields `huron`, `api_url`, `instance_id` and `organization`. A storage admin writes it
with `huron adm provision-orgs`. An organization without a root that the configuration does not
declare uses the marker at the mount prefix. That marker names only the instance.

Before the CLI touches any directory of an organization, it reads the marker that guards it. The
CLI refuses the operation unless these conditions are true:

- The directory exists on this machine, and its marker exists and is readable.
- Its `instance_id` is the instance id that the service gives in `GET /healthz`.
- The marker of an organization names that organization. The marker at the mount prefix names no
  organization.

The check stops two mistakes. A CLI that points at a test service cannot write into the
directories of the production service. An export that is mounted at the root of another
organization cannot get files of the wrong organization. The CLI does this check inside every path
that it uses on the share, so no command can skip it. A refusal exits with code 8.

[Adding an organization](../operator.md#adding-an-organization) tells how a storage admin prepares
the directory and the marker. [The mount prefix](../operator.md#the-mount-prefix-for-organizations-without-a-root)
tells how to mark the mount prefix.

## Creating and activating a collection

`huron create collection` makes the collection and its directory in this sequence:

1. The CLI checks the marker of the organization. Thus a missing or wrong share stops the command
   before the service reserves the name.
2. The service reserves the name. The collection is a draft at version 1.
3. The CLI asks for the metadata, or it reads `--metadata file.json`.
4. The API creates the directory of the collection in the directory of its namespace. The directory
   gets mode `2750` and inherits its parent's group.
5. The service activates the collection. The request carries the version of the collection.
6. The CLI gets the `metadata.json` document from the service and writes it into the directory.
7. The CLI records a working copy and selects it as the current collection.

With `--draft`, the CLI does not check the marker, and it stops after step 3. The draft becomes
the current collection. `huron activate collection` does steps 4 to 7 later. The service activates
a collection only when its metadata satisfies the schema.

Creating the directory and activating the record are separate operations. If activation fails,
the draft can have a directory left by the CLI. Check the error and correct its cause. Then use
`huron activate collection <identifier>` to continue with the reserved collection.

The service user owns the collection directory. The directory inherits its group through setgid,
not through ACLs or API grants. Clients mount the share read-only.
See [Directory modes and share groups](access-and-roles.md#directory-modes-and-share-groups) for the access rules.

## The working copy and the stage

The CLI keeps its own state under `$XDG_STATE_HOME/huron`, which is `~/.local/state/huron` by
default. Each working copy has a directory there, `collections/<collection id>/`, with these files:

| File | Contents |
| --- | --- |
| `working.json` | A format version, the id and identifier of the collection, the path of its directory, the version that the working copy holds, and the stage. Each staged add has the path in the collection, the absolute path of the local file, its size, its `sha256` and its upload attempt. |
| `metadata.draft.json` | Your metadata draft, when you have one. |
| `push.lock` | The lock that a push holds. |

To change `working.json` or `metadata.draft.json`, the CLI writes a new temporary file first. It
syncs that file, renames it over the old file and syncs the directory.
The files have mode 0600. The CLI creates the directories with mode 0700. The current collection
is in the CLI configuration, `$XDG_CONFIG_HOME/huron/config.yaml`.

The working copy holds no copy of your files. It holds the version of the collection, the stage
and your metadata draft. `huron checkout` records a working copy and keeps the stage of each working
copy.

## Staging files

`huron add` and `huron rm` change only the stage. They do not touch the share.

`huron add <file>` stages the file at its own name in the collection. `--as <path>` gives one file
another path. `huron add <directory> --recursive` stages each file in the directory, at its path
relative to that directory. The CLI makes these checks:

- It refuses a symbolic link that you name. It does not stage a symbolic link inside a directory.
- It refuses a path that breaks a path rule, such as a reserved name.
- When you stage a path again, the new add replaces the old one and unstages a removal of that path.

The CLI reads the size of each file when you stage it. It does not read the contents until the
push.

`huron rm <path>` unstages an add or a removal of that path. When nothing is staged for a recorded
file, `huron rm` stages its removal. The CLI asks the service which files it records. A path that
is neither recorded nor staged is an error.

[Staging and pushing files](../user-guide.md#staging-and-pushing-files) shows the commands with
examples.

## The push, step by step

`huron push` copies the staged files onto the share and records them in one commit:

```text
huron push
  |
  |-- read the collection ---- other version? --> stop, BASE_VERSION_CONFLICT
  |-- dry-run commit --------- refused? --------> stop, nothing copied
  |-- check the marker
  |-- for each add:  copy to <name>.huron-part while hashing,
  |                  fsync, rename to <name>, save the stage
  |-- commit (base_version, adds, removes, host)
  |-- unlink each removed file
  '-- clear the stage, record the new version
```

These are the steps:

1. The CLI takes the lock of the working copy. When another push of the same working copy holds
   the lock, the push stops.
2. The CLI reads the collection from the service. When its version is not the version of the
   working copy, the push stops with `BASE_VERSION_CONFLICT`. When the collection is a draft, the
   push stops too.
3. The CLI sends the commit to the service as a dry run. The dry run carries the paths and sizes,
   and a `sha256` only where an earlier push already copied the file.
4. The CLI checks the marker of the organization and finds the directory of the collection.
5. For each staged add, the CLI copies the file into the directory, as the next list tells.
6. The CLI sends the commit. The commit has `base_version`, `adds`, `removes`, `host` and the
   optional `message`. Each add has `rel_path`, `size` and `sha256`.
7. After the service accepts the commit, the CLI unlinks each removed file from the share.
8. The CLI clears the stage and records the new version in the working copy.

The dry run does all the checks of a real commit, and it changes nothing. The service checks your
right to write files, the state of the collection, the paths, the removed files, the base version
and the file tree. When the service refuses the dry run, the push stops before it copies one byte.
The share and the stage do not change.

The dry run reserves no version and holds no lock during the copy. Another client can change the
collection before the real commit. The service checks the version again when that commit arrives.
The database transaction covers the recorded changes only. It cannot undo file copies on the share.

For each file in step 5, the CLI does these steps:

1. It creates the parent directories inside the collection with mode 2770.
2. It opens `<name>.huron-part` next to the destination. It unlinks an old part file first.
3. It copies the local file into the part file and calculates the SHA-256 hash during the copy.
4. It flushes the part file to disk with `fsync`.
5. It renames the part file to `<name>`. The rename replaces a file with that name.
6. It saves the size and hash in `working.json`, and it prints `copied <path> (<n> bytes)`.

When the copy fails, the CLI unlinks the part file. The file at `<name>` does not change.

The service refuses a commit with more than 10,000 entries, adds and removals together. The CLI
unlinks removed files only after the commit, so a commit that fails never unlinks a file. When an
unlink fails, the CLI prints a warning and the push continues. A file that is already gone is not
an error.

## When a push stops

A push can stop at different points. The result is different for each point:

- **Before the copy.** The checks of steps 2 and 3 change nothing. Correct the cause and push again.
- **During the copy.** The stage already holds the hash of each file that the CLI copied. Run
  `huron push` again. When a file on the share still has the saved size and hash, the CLI does not
  copy it again. The CLI reads the file on the share again to calculate its hash.
- **When the service refuses the commit after the copy.** This can occur when another commit
  came first. The copied files stay on the share, but no commit records them. `huron status` shows
  new paths as unrecorded files. A copied file that replaces a recorded file already holds the new
  bytes, while its record still describes the old file. `huron adm check --hash` detects that
  difference. The stage keeps the hashes for a later push.
- **When the commit gets no answer from Huron.** The service can be unreachable, or the answer can
  be lost. Then the CLI cannot tell whether the service applied the commit, so it reads the
  collection again. The CLI accepts the commit as applied when these two conditions are true:
  - The version of the collection is higher than the version of the working copy.
  - The service records each staged add with the hash that the CLI copied.

  Otherwise, the CLI shows the original error. The stage stays, and you can push again.

A crash or a killed process during a copy can leave a `.huron-part` file. `huron adm check`
reports a part file older than one hour as `stale_part`. A later copy of the same file unlinks the
part file and writes it again.

## Base version conflicts and huron pull

Each commit carries the version of your working copy as its `base_version`. The service locks the
collection row and compares the base version with the current version. When they are not equal,
it refuses the commit with `BASE_VERSION_CONFLICT`, status 409. The CLI exits with code 6 and the
hint ``run `huron pull` ``. Each commit and each metadata change increases the version, also when
another person makes it.

`huron pull` reads the current version of the collection from the service and records it in the
working copy. It keeps your staged adds. It unstages each staged removal of a file that the service
no longer records, and it prints a warning for each. `huron pull` does not copy files to your
machine. Then run `huron push` again.

The lock belongs to one local working copy. It does not lock the collection for other users or
machines. `huron pull` updates your base version but does not merge file contents. Check the
current files before you repeat a push that replaces an existing path.

[When someone else changed the collection](../user-guide.md#when-someone-else-changed-the-collection)
shows the error and the commands.

## What the service records

The service writes each commit in one database transaction. It applies all of the commit, or it
refuses all of it. A commit that it accepts does these changes:

- It records one row for each added file: the path, the size, the SHA-256 hash, the time, the user
  and the commit. An add of a path that is already recorded replaces the row of that path.
- It removes the row of each removed file.
- It increases the version of the collection by 1 and sets its file count.
- It records the commit: the base version, the new version, the number of adds and removals, the
  host, the message and the user.
- It writes an audit entry for the commit. `huron get log` shows the audit entries of a collection.

Thus the service has one row for each current file. Huron keeps no older copies of file contents.
The share holds only the current files. When a push replaces a file, the old bytes are gone from
the share, and Huron cannot recover them. The snapshot policy of your storage team recovers files.
Refer to [Backups and recovery](../operator.md#backups-and-recovery).

## The metadata.json sidecar

The metadata is in PostgreSQL, and the service is its source of truth. The CLI also writes a copy,
`metadata.json`, into the directory of each collection that is not a draft. Thus the information
stays next to the files, also without the service.

The service makes the document, and the CLI writes it without changes. It holds the identifier, the
organization, the catalog, the schema, the schema override, the metadata, the creator and the time
of creation. It does not hold the version or the file count, so a push does not make it stale.

The CLI writes the sidecar at activation. It writes the sidecar again at each change that the CLI
makes to the metadata or the schema override, such as `huron publish meta` or `huron set override`.
`huron adm check` reports `sidecar_stale` when the file is missing or does not agree with the
document of the service.

## Drift detection

`huron adm check` compares what the service records with what the share holds. It first checks the
directory and the marker of each organization. It does not check ACLs: Huron uses none.
Then it checks each catalog that you can read, or only the catalog of `--catalog`. It skips the
catalogs of an organization when its own directory or marker is missing or wrong. These findings
concern raw ingest:

| Finding | Meaning |
| --- | --- |
| `file_missing` | The service records a file that is not on the share. |
| `file_changed` | The size of the file is not the recorded size. With `--hash`, also: the SHA-256 hash is not the recorded hash. |
| `file_unrecorded` | A file in the directory of a collection that no commit records. |
| `stale_part` | A `.huron-part` file older than one hour. |
| `sidecar_stale` | `metadata.json` is missing or does not agree with the service. |

Without `--hash`, the check compares only the size of each file. Thus it does not find a change
that keeps the size. `huron adm check --hash` reads each file and calculates its hash. The command
exits with code 1 when it has findings.

The check does not repair directories. API grants and the catalog's filesystem share group are separate.
A grant change does not change directory permissions. The API repair endpoints use database rows to plan directory work, not a filesystem scan.
Missing setgid bits or wrong groups below a catalog need the storage administrator.
The current CLI has no `adm repair`, `adm provision-catalogs` or `adm apply-acl` command.
See [Grant changes and directory repair](access-and-roles.md#grant-changes-and-directory-repair) before requesting repair.

[Reading huron adm check](../operator.md#reading-huron-adm-check) tells what to do for each
finding.

## The trust model

Huron contains and detects mistakes. It does not prevent all of them. Clients mount the share read-only,
and API privileges control writes through Huron. Directory modes and share groups control filesystem reads.
AUTH_SYS trusts client user IDs, so these permissions do not protect against root on an authorized client.

The service never reads the share. It trusts the size and the hash that the CLI reports in each
commit. After the commit, `huron adm check` finds a changed file when its size changed. Only
`huron adm check --hash` compares the contents.

Huron uses no ACLs. Directory modes and share groups control filesystem read access independently of API grants.
The CLI reports drift but does not change those directory permissions.

## Related pages

- [User guide](../user-guide.md): staging, pushing and pulling, with examples.
- [Glossary](../user-guide.md#glossary): the Huron terms on this page.
- [`huron push`](/docs/reference/cli/push/), [`huron add`](/docs/reference/cli/add/),
  [`huron rm`](/docs/reference/cli/rm/) and [`huron pull`](/docs/reference/cli/pull/).
- [`huron adm check`](/docs/reference/cli/adm/#huron-adm-check): report drift without changing the share.
- [Reading huron adm check](../operator.md#reading-huron-adm-check): what to do for each finding.
- [API error codes](../api-errors.md): `BASE_VERSION_CONFLICT`, `COMMIT_INVALID` and others.
- [How Huron works](how-huron-works.md): the parts of Huron and the collection lifecycle.
- [Directory modes and share groups](access-and-roles.md#directory-modes-and-share-groups): the
  permissions of each directory.
