# Trace an owned flow

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
After opening the named owned session, from `web/`:

```sh
npx --no-install playwright cli -s=huron-qa-slice tracing-start
# Reproduce the flow in this named session.
npx --no-install playwright cli -s=huron-qa-slice tracing-stop
```

Capture the actual output paths and ensure they are beneath ignored
`.playwright-cli/` or `/roadmap/`. Traces contain actions, DOM snapshots, network,
console and resources; network headers/bodies can contain secrets. Keep raw traces
local and report only safe findings and paths. Start before the failing action.
Tracing adds overhead and dynamic state may not replay perfectly; a trace is
diagnostic evidence, not a replacement for assertions or visual inspection.
Do not bulk-delete old traces; cleanup is limited to owned artifacts.
