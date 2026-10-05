# Named browser sessions

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
All commands run from `web/`.

```sh
npx --no-install playwright cli list
npx --no-install playwright cli -s=huron-qa-slice open http://localhost:5173
npx --no-install playwright cli -s=huron-qa-slice snapshot
npx --no-install playwright cli -s=huron-qa-slice close
```

Verify URL/service ownership before opening. Choose a unique task-specific name;
each session has independent cookies, storage, cache, history and tabs. Omit
persistent profiles unless the experiment needs one, and then store it in an owned
ignored path. Explicit `-s` prevents accidental default-session reuse.

For an owned running browser, `-s=huron-qa-slice attach --cdp=<owned-endpoint>`
attaches; `-s=huron-qa-slice detach` disconnects without closing that browser.
Only attach after establishing ownership. Never close/kill all browsers, delete
unknown profiles or kill unrelated processes. Report a stuck owned session before
attempting bounded recovery. Multiple browser names do not authorize concurrent
workers: dispatched activity/claims and service/check-output ownership must satisfy
the orchestration contract. Actual code is exclusive; non-code overlap requires
nonconflicting exact claims, which are cooperative coordination, not a sandbox.
