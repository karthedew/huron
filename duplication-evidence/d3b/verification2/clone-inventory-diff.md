# D3b verification 2 — independently recomputed clone inventory diff

| Report | Stats |
| --- | --- |
| baseline (pre-D3b) | 213/938 frags, 253 pairs, 58 groups, 132 files |
| verification1 (attempt-1 tree) | 216/939 frags, 254 pairs, 59 groups, 133 files |
| fix1 (implementer) | 216/939 frags, 254 pairs, 59 groups, 133 files |
| verification2 (this run) | 216/939 frags, 254 pairs, 59 groups, 133 files |

## verification2 vs baseline

### Removed cloned fragments (3)

- `src/huron/applications/api/routes/v1/endpoints/datasets.py:341-360` hash `32c0b603680ff709`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:310-335` hash `37383bd8e1be4cb5`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:248-300` hash `387289410ce788cc`

### Introduced cloned fragments (6)

- `src/huron/core/releases.py:34-47` hash `032abe5de3352373`
- `src/huron/applications/api/dependencies.py:62-76` hash `045237841e5bbb5e`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:309-334` hash `1ba45cc3ab12a739`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:248-299` hash `c6e27880bcc723be`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:340-359` hash `d6def09a882b2eb5`
- `src/huron/core/_ingest.py:249-263` hash `f357f7313e7a622d`

## verification2 vs fix1 (implementer's final tree)

Removed vs fix1: []

Added vs fix1: []

## verification2 vs verification1 (attempt-1 tree)

### Only in verification1

- `src/huron/applications/api/routes/v1/endpoints/datasets.py:341-360` hash `934eed217cc1f085`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:310-335` hash `97a67889bf005429`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:249-300` hash `d9ed63f31f4b9794`

### Only in verification2

- `src/huron/applications/api/routes/v1/endpoints/datasets.py:309-334` hash `1ba45cc3ab12a739`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:248-299` hash `c6e27880bcc723be`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:340-359` hash `d6def09a882b2eb5`

## Per-file cloned-fragment delta (baseline -> verification2)

- `src/huron/applications/api/dependencies.py`: 3 -> 4
- `src/huron/core/_ingest.py`: 7 -> 8
- `src/huron/core/catalog_ports.py`: 1 -> 2
- `src/huron/core/ports.py`: 1 -> 0
- `src/huron/core/releases.py`: 0 -> 1

## Groups containing the new fragments

- group 53 size 2 sim 0.781: `src/huron/core/_ingest.py:249`, `src/huron/core/releases.py:34`
- group 41 size 4 sim 0.766: `src/huron/applications/api/dependencies.py:19`, `src/huron/applications/api/dependencies.py:62`, `src/huron/applications/api/dependencies.py:82`, `src/huron/applications/api/dependencies.py:125`
