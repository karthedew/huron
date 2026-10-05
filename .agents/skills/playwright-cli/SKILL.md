---
name: playwright-cli
description: Use the installed Playwright CLI for browser interaction, visual QA, failure-state inspection and test debugging in Huron. Use for visible UI verification and browser automation.
---

# Browser QA with the local Playwright CLI

Adapted from the official installed Playwright **1.62.1** skill and all nine linked
references. See [provenance](PROVENANCE.md). These are canonical local files, not
links to node_modules. Read relevant references before their specialized tasks.

## Setup and ownership

Run from `web/` with a supported Node version:

```sh
npx --no-install playwright --version
npx --no-install playwright cli --help
```

Expected version at adoption: 1.62.1. On mismatch inspect installed official source
and help before assuming commands work. Do not install globally or bootstrap a new
Playwright project. Missing locked dependencies/browser are a reported prerequisite.

Establish app/port ownership before navigation or service startup: 5173 and 9000
may belong to other projects; Huron e2e uses 4173. Inspect actual task config. Use a
unique named session (replace `huron-qa-slice` below) and only close your own session.
Never use `close-all`, `kill-all`, or attach to unrelated browsers. Attached owned
browsers use `detach`, which leaves the external browser running.

Keep default CLI artifacts in ignored `web/.playwright-cli/`; explicit screenshots,
traces, state and videos go there or under `/roadmap/`. Verify `git check-ignore`
before saving. Use in-memory profiles by default. Never put Huron credentials in
browser local/session storage, commit auth state, or paste cookies/tokens into reports.

## Interaction loop

After confirming the URL belongs to this task:

```sh
npx --no-install playwright cli -s=huron-qa-slice open http://localhost:5173
npx --no-install playwright cli -s=huron-qa-slice snapshot
npx --no-install playwright cli -s=huron-qa-slice click e15
npx --no-install playwright cli -s=huron-qa-slice fill e5 "example"
npx --no-install playwright cli -s=huron-qa-slice press Enter
npx --no-install playwright cli -s=huron-qa-slice console
```

Use refs from a fresh snapshot (example refs above are placeholders), or semantic
role/label locators. Inspect post-action state rather than assuming success.
CLI actions emit Playwright TypeScript; add behavioral assertions before using
that output as a test. Browser QA supplements, not replaces, the frontend gate.

## Required visual evidence

```sh
npx --no-install playwright cli -s=huron-qa-slice resize 390 844
npx --no-install playwright cli -s=huron-qa-slice resize 816 900
npx --no-install playwright cli -s=huron-qa-slice resize 1440 1000
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { await page.emulateMedia({ colorScheme: 'dark' }); }"
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { await page.emulateMedia({ colorScheme: 'light' }); }"
npx --no-install playwright cli -s=huron-qa-slice press Tab
npx --no-install playwright cli -s=huron-qa-slice screenshot --filename=.playwright-cli/qa-wide-light.png
npx --no-install playwright cli -s=huron-qa-slice close
```

At **each** viewport, inspect light/dark appearance, primary keyboard flow and
visible focus. Exercise loading, empty, long-content, validation, failure and
unauthorized/undiscoverable states affected by the change. Check clipping,
horizontal overflow, hydration/console errors and accessible control names.
Use controlled fixtures/network routes for states; label mocks as synthetic and
never claim backend authorization was proved by them. Record session name, URL,
viewport/theme, scenario/result, screenshots/snapshots and limitations in the local
evidence record. Restore owned mocks and close the owned session when done.

## References

- [Test running and debugging](references/playwright-tests.md)
- [Request mocking](references/request-mocking.md)
- [Running Playwright code and media emulation](references/running-code.md)
- [Named session management](references/session-management.md)
- [Storage state](references/storage-state.md)
- [Test generation and diagnosis](references/test-generation.md)
- [Tracing](references/tracing.md)
- [Video recording](references/video-recording.md)
- [Element attributes](references/element-attributes.md)
