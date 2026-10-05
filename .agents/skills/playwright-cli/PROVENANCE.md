# Playwright skill provenance

- Source: Microsoft Playwright, npm package `playwright-core` **1.62.1** installed
  by the frontend lockfile at adoption (2026-10-04).
- Source directory: `web/node_modules/playwright-core/lib/tools/skills/playwright-cli`.
- Official project: <https://github.com/microsoft/playwright>.
- Upstream license: Apache-2.0 (<https://www.apache.org/licenses/LICENSE-2.0>).
- Read source `SKILL.md` and every linked `references/*.md` before adapting.
  All nine reference filenames are retained locally. They are abridged/adapted,
  **not byte-identical vendor copies**. No runtime skill dependency on node_modules.
- Verified entry point: from `web/`, `npx --no-install playwright --version`
  returns `Version 1.62.1`; `npx --no-install playwright cli --help` succeeds.

Local adaptations replace bare/global CLI commands with the installed no-install
entry point, require owned named sessions and ignored artifacts, omit global
installation/broad browser shutdown, retain Huron's no-skip testing contract,
reuse existing fixtures instead of scaffolding, and route plans to `/roadmap/`.
Token-in-localStorage examples and automatic prototype/test promotion are removed.

Refresh deliberately when Playwright changes: inspect the new installed official
skill and all linked references, verify CLI help/version, update adapted guidance
and this record, and rerun agent asset checks. Do not regenerate from `latest` or
replace the local skill with a symlink.
