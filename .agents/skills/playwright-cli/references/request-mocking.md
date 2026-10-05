# Failure-state request mocking

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
From `web/`, use narrow patterns for actual requests observed in the owned session:

```sh
npx --no-install playwright cli -s=huron-qa-slice requests
npx --no-install playwright cli -s=huron-qa-slice route "**/api/example" --status=503
npx --no-install playwright cli -s=huron-qa-slice route-list
npx --no-install playwright cli -s=huron-qa-slice unroute "**/api/example"
npx --no-install playwright cli -s=huron-qa-slice run-code "async page => { await page.route('**/api/example', route => route.abort('internetdisconnected')); }"
```

The example endpoint is illustrative, not a Huron API contract. For JSON mocks,
use `--body='<json>' --content-type=application/json` against the verified wire shape.
Confirm the interception occurred and record it as synthetic. Browser routes do
not intercept server-side SvelteKit requests: those need the existing controlled
server/test fixture seam. Fixture-backed UI may make no request at all. Restore
owned routes after each scenario. Mocked denials never prove backend authorization.
