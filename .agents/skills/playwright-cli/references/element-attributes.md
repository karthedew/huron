# Inspect attributes omitted by snapshots

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
From `web/`, obtain a fresh ref then inspect only needed properties:

```sh
npx --no-install playwright cli -s=huron-qa-slice snapshot
npx --no-install playwright cli -s=huron-qa-slice eval "el => el.id" e7
npx --no-install playwright cli -s=huron-qa-slice eval "el => el.getAttribute('aria-label')" e7
npx --no-install playwright cli -s=huron-qa-slice eval "el => getComputedStyle(el).display" e7
```

Replace `e7` with the observed ref. Inspect focus/accessible names and computed
styles to explain a failure; do not use DOM mutation to conceal UI defects.
