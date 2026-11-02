# NOAA Planetary K-index in Huron

This example loads a year of NOAA's geomagnetic K-index data into Huron as raw files, unchanged
(no Zarr or Icechunk conversion). It creates the catalog `planetary` in the organization `noaa`,
which `huron.dev.yaml` declares.

- `fetch.py` downloads the files from NOAA SWPC and writes `manifest.json` with each file's
  sha256.
- `load.sh` creates the catalog, its namespaces and one collection per file group, then pushes
  the files.

On the development stack, `make demo-noaa` does all of it in one command once `make app` is up:
it signs a CLI of its own in as `admin` (configuration and state under
`~/.cache/huron/demo-noaa/`, never your own), runs `fetch.py` into
`~/.cache/huron/demo-noaa/raw` the first time, then `huron adm provision-orgs` and `load.sh`, and
prints the tree and the files on disk. Running it again changes nothing. `NOAA_REFRESH=1` fetches
again; `NOAA_RAW=<dir>` loads an existing download instead. The rest of this page is what it does,
step by step, for running it by hand.

## The data

The source is the NOAA Space Weather Prediction Center (SWPC). All values are SWPC's preliminary
estimates, not the definitive Kp that GFZ Potsdam publishes later.

| Product | Source | What it holds |
| --- | --- | --- |
| Daily Geomagnetic Data (DGD), one file per quarter | `ftp.swpc.noaa.gov/pub/indices/old_indices/<YYYY>Q<n>_DGD.txt` | One row per UT day. Each row has the daily A index and the eight 3-hourly K indices for three sets: Fredericksburg, College and the estimated planetary index (Kp). Missing values are `-1`. |
| Planetary K-index snapshot | `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json` | Roughly the last seven days of 3-hourly Kp, with `a_running` and `station_count`. `time_tag` is the start of each 3-hour interval. |

The DGD column layout is described in NOAA's own README,
`ftp://ftp.swpc.noaa.gov/pub/indices/old_indices/README`. `fetch.py` downloads it too, but it is
not loaded into a collection. Each DGD collection records its URL as `source.documentation`.

The current quarter (2026Q4 as of 2026-10-31) is reissued every day, and its last day can be
incomplete. The JSON product is a rolling window, so each retrieval is kept as its own dated file
(`noaa-planetary-k-index-<YYYY-MM-DD>.json`).

## Layout in Huron

```text
planetary                                    catalog (org noaa), "Planetary K-index"
└── k-index/                                 namespace, no collections
    ├── quarterly/                           namespace, collections allowed
    │   ├── planetary.k-index.quarterly.2025-q4    2025Q4_DGD.txt
    │   ├── planetary.k-index.quarterly.2026-q1    2026Q1_DGD.txt
    │   ├── planetary.k-index.quarterly.2026-q2    2026Q2_DGD.txt
    │   ├── planetary.k-index.quarterly.2026-q3    2026Q3_DGD.txt
    │   └── planetary.k-index.quarterly.2026-q4    2026Q4_DGD.txt (current quarter)
    └── snapshots/                           namespace, collections allowed
        └── planetary.k-index.snapshots.3-hour     noaa-planetary-k-index-<date>.json, one per retrieval
```

Nobody is granted a role on the catalog itself. `huron.dev.yaml` declares `noaa` with
`groups.reader: [noaa-readers]` (and `groups.org_admin: [noaa-org-admins]`), and every catalog of
`noaa` inherits those groups, so `noaa-readers` reads `planetary` as soon as it exists.
`huron get grants --catalog planetary` lists the group with the source `organization noaa`. On
the dev stack the user `user` (password `user`) is in that group.

Collections hold only the data files. Everything else from the manifest goes into the
collection's metadata, which the catalog's `huron-base` schema validates (`title` and
`description` are required, and extra fields are allowed):

- `title`, `description`, `instrument`, `keywords`.
- `start_time` and `end_time` in UTC. The end is exclusive: the day after the last DGD day, or the
  last JSON `time_tag` plus 3 h.
- `labels` for search: `source=noaa-swpc`, and `product=daily-geomagnetic-data` or
  `product=planetary-k-index`. DGD collections also have `quarter=2026-q1`, `year`,
  `status=complete` or `status=in-progress`, and `format=text`. The JSON collection has
  `status=rolling`, `format=json` and `snapshots=<count>`. Both have `cadence=3-hour`.
- `source`: the publisher and the URL. DGD collections also record the format README as
  `source.documentation`.
- `files`: one entry per file with `name`, `url`, `sha256`, `size`, `retrieved_at`,
  `covers {start, end}` and, for DGD files, the `issued` time from the file's header.

## Fetch

```bash
python3 -I examples/noaa/fetch.py --out /path/to/raw            # last 12 months to UTC today
python3 -I examples/noaa/fetch.py --out /path/to/raw --months 12 --today 2026-10-31
```

`fetch.py` uses only the standard library. It tries HTTPS and falls back to FTP. Files that are
already present with the same size as the remote copy are skipped. The current quarter and the
JSON snapshot are downloaded again on every run. Keep the raw directory outside the repository.

## Log in

`load.sh` uses the CLI's stored token, so log in first. You need to be able to create catalogs
in `noaa`, which means a platform admin or a member of `noaa-org-admins`:

```bash
huron config set api_url http://127.0.0.1:8080
huron config set issuer http://127.0.0.1:8081/realms/company
huron login                 # browser; or: huron login --device
```

On the dev stack (`make app`) you can log in without a browser with `scripts/dev-login.sh`: it
runs the Keycloak password grant for `admin`/`admin`, then `POST /api/v1/auth/exchange`, and
writes `$XDG_STATE_HOME/huron/tokens.json`. It needs `XDG_STATE_HOME` set, so give the CLI a
directory of its own, as `make demo-noaa` does:

```bash
export XDG_CONFIG_HOME=~/.cache/huron/demo-noaa/config XDG_STATE_HOME=~/.cache/huron/demo-noaa/state
scripts/dev-login.sh admin admin
```

## Load

```bash
examples/noaa/load.sh /path/to/raw
```

Before it sends anything, `load.sh` checks every local file against the sha256 in its manifest.
Then it does the following:

1. Creates the catalog `planetary` in `noaa` unless `huron describe catalog` finds it. It grants
   nothing: it reports the organization-wide reader groups the catalog inherits from `noaa`
   (`huron get grants`), or that `noaa` has none, in which case set `groups.reader` in its
   entry of the service configuration. From here on
   every identifier is resolved against this catalog (`huron --catalog planetary`), whatever
   your current catalog is.
2. Creates `planetary.k-index`, `planetary.k-index.quarterly` and `planetary.k-index.snapshots`
   unless they exist.
   For namespaces that exist, it checks that `collections_allowed` is as expected.
3. For each collection, creates it with `--metadata` if it is missing. Then it runs
   `huron checkout`, compares `huron -o json get files` with the manifest, and runs `huron add` and
   `huron push -m <source url>` only for files that are missing or have a different sha256. A
   reissued current quarter replaces the recorded file. A new dated snapshot is added next to the
   earlier ones.
4. Rebuilds the metadata and republishes it only if it differs from what the collection holds.
   This happens, for example, when a reissued quarter has a new `issued` time or sha256, or when a
   new snapshot extends the coverage. A file whose sha256 has not changed keeps its earlier
   `retrieved_at`. The new document becomes the local draft with
   `huron edit meta <collection> --file <document.json>`, which asks nothing, and is sent with
   `huron validate meta` and `huron publish meta`.

Running it again with the same raw directory changes nothing: every step reports `skipped`,
`nothing to push` or `metadata unchanged`, and no collection's version changes. To refresh, run
`fetch.py` and then `load.sh` again. Only the changed quarter and the new snapshot are pushed.

You can change the defaults with `ORG` (`noaa`) and `CATALOG` (`planetary`), set `HURON` to the
command that runs the CLI (default `uv run --quiet --project <repo> huron`), and set `TREE=0` to
skip the closing `huron tree`.

### After `make app-reset`

`make app-reset` deletes the database but not the share, so `/data1/huron/noaa/planetary/…`
still holds the directories, files and `metadata.json` sidecars of the earlier load, which the
service no longer records. `load.sh` needs nothing special for that: the create commands accept
an existing directory (and set its mode), `huron push` writes each file through a part file and
renames it over the one at the same path, and activating a collection rewrites its
`metadata.json`. A file that is byte-for-byte the same is simply written again; a newer copy
(such as a reissued current quarter) replaces the old one. Nothing is deleted. Only a file the
earlier load pushed that is no longer in the raw directory (an older dated snapshot, say) stays
on disk unrecorded; `huron adm check --catalog planetary` reports it as `file_unrecorded`, and you
may delete it by hand.

## Browse

```bash
huron org noaa
huron catalog planetary                 # make it current; `huron catalog` lists noaa's catalogs
huron describe catalog
huron tree
huron get collections
huron get collections k-index.quarterly
huron get files k-index.quarterly.2026-q4
huron describe collection k-index.snapshots.3-hour
huron get meta k-index.quarterly.2025-q4    # the published metadata
huron search -l product=daily-geomagnetic-data -l status=complete
huron adm check --catalog planetary --hash  # service and share agree, sha256 included
```

A member of `noaa-readers` can browse and download but not push: `huron push` asks the service
first (a dry-run commit) and stops with `FORBIDDEN` before any byte reaches the share.

## Where the bytes are

`noaa` has the root `/data1/huron` in `huron.dev.yaml`, so its directory is `/data1/huron/noaa`.
That directory is created and marked by `huron adm provision-orgs` and checked by
`huron adm verify-mounts`. Each collection is a directory under it, holding the raw file as it
was fetched and the `metadata.json` sidecar that the service renders:

```text
/data1/huron/noaa/.huron
/data1/huron/noaa/planetary/k-index/quarterly/2025-q4/2025Q4_DGD.txt
/data1/huron/noaa/planetary/k-index/quarterly/2025-q4/metadata.json
…
/data1/huron/noaa/planetary/k-index/quarterly/2026-q4/2026Q4_DGD.txt
/data1/huron/noaa/planetary/k-index/snapshots/3-hour/noaa-planetary-k-index-2026-10-31.json
/data1/huron/noaa/planetary/k-index/snapshots/3-hour/metadata.json
```

```bash
sha256sum /data1/huron/noaa/planetary/k-index/quarterly/*/*_DGD.txt \
  /data1/huron/noaa/planetary/k-index/snapshots/3-hour/noaa-planetary-k-index-*.json
```

The output matches the `sha256` values in `manifest.json`.
