# Generate assertions from observed interactions

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).

1. Read the phase acceptance criteria and existing e2e fixtures/tests. Record any
   missing scenario in the local plan under `/roadmap/`; reuse the project's setup.
2. Explore through an existing relevant test using [debug attach](playwright-tests.md)
   when setup/auth fixtures matter. Each scenario begins with isolated state.
3. CLI actions emit equivalent TypeScript. Prefer role/label locators and add an
   explicit observable assertion for every expected outcome; actions alone are not
   a test. `generate-locator <ref>` can help inspect a locator from a fresh snapshot.
4. Write tests only in the assigned product scope, following existing fixtures and
   file organization. Do not scaffold a new Playwright project or promote scratch
   scripts automatically. Comments explain behavior, not plan step numbers.
5. Run the focused test, then the complete applicable gate. Diagnose disagreement
   between expectation and app rather than changing the expectation to match a bug.
   Unresolved intent blocks the change. No skips, fixme markers, weakened assertions
   or sleeps as a repair. Preserve failures as evidence for the serial review loop.

For network scenarios see [request mocking](request-mocking.md); for isolation and
cleanup see [session management](session-management.md).
