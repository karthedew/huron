# Scoped storage state

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
Prefer in-memory sessions. Only save state when the assigned test needs reuse:

```sh
npx --no-install playwright cli -s=huron-qa-slice state-save .playwright-cli/qa.auth-state.json
npx --no-install playwright cli -s=huron-qa-slice state-load .playwright-cli/qa.auth-state.json
npx --no-install playwright cli -s=huron-qa-slice reload
```

Run from `web/` and confirm the output path is ignored first. State includes
cookies and origin storage and may contain credentials; keep it out of reports,
commits and shared artifacts. Huron credentials remain server-side; never use
upstream token-in-localStorage examples. Non-secret theme preferences can be
inspected with `localstorage-get <actual-key>` if the implementation uses that key.
Clean up only explicitly owned saved state when its retention is no longer needed.
