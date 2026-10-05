# Run and debug tests

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
From `web/`, use the repository gate:

```sh
PLAYWRIGHT_HTML_OPEN=never npm run test:e2e
```

Inspect the Playwright configuration, prerequisites and server ownership before
running it. For a focused failure, launch the following through a supported
background process tool and retain its process identity:

```sh
PLAYWRIGHT_HTML_OPEN=never npx --no-install playwright test <test-path> --debug=cli
```

Wait for the actual “Debugging Instructions” and generated `tw-...` session name.
Attach to that owned test with `npx --no-install playwright cli attach <printed-name>`;
use its printed name explicitly for subsequent CLI commands. Keep the test running
while inspecting `snapshot`, `console`, `requests`, `step-over` and `resume`.
Detach and stop only the owned debug process when done, then rerun the test and the
complete applicable gate. Do not skip tests or weaken assertions to obtain green.
