# Custom Playwright code

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
From `web/`, `run-code` accepts a single function expression with `page` available;
import/export/require statements are not supported.

```sh
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { await page.emulateMedia({ colorScheme: 'dark' }); }"
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { await page.emulateMedia({ colorScheme: 'light' }); }"
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { await page.emulateMedia({ reducedMotion: 'reduce' }); }"
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { return page.viewportSize(); }"
npx --no-install playwright cli -s=huron-qa-slice run-code --filename=../roadmap/prototypes/qa/scenario.js
```

Wait for a specific observable condition, such as a locator becoming visible or
the expected URL, rather than arbitrary sleeps or network-idle heuristics. Do not
catch and hide failures in evidence scripts. Use `page.context()` for scoped
browser capabilities; keep downloads, scripts and artifacts in owned ignored paths.
