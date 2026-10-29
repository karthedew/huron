# Prototype evidence: durable activity-aware admission and progress

## Question, hypothesis and scope

Source: [dispatch design](../../dispatch-concurrency-design.md). Can independent
non-code claims overlap while exclusive code, durable ownership, uncertain dispatch
and real-filesystem atomic admission remain fail-closed? Can progress survive empty
tool turns without mistaking older text for terminal evidence?

Throwaway `probe.mjs` uses installed SDK 1.17.18 against a simulated HTTP boundary
(the same external-I/O testing seam as existing live tooling tests). It never
imports product code or calls models/live server. Real local filesystem journal and
exclusive-create locks, plus one ordinary Node subprocess, exercise persistence and
cross-process exclusion. Subprocess is a filesystem probe, not an agent/server.

Owned files: `probe.mjs`, `evidence.md`, `check-owned.mjs`; generated private state
under `runs/probe-*` remains ignored and retained. No existing path was overwritten.
Fresh mkdtemp per scenario isolates mutable state; message times/IDs are fixed.
Temp directory randomness is only collision avoidance, not a behavioral input.

## Exact reproduction

Cwd `/home/karl/repo/huron`; locked `.agents/node_modules` already present:

```sh
/home/karl/.nvm/versions/node/v22.23.2/bin/node --version
/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/dispatch-concurrency/probe.mjs
/home/karl/.nvm/versions/node/v22.23.2/bin/node roadmap/prototypes/dispatch-concurrency/check-owned.mjs
```

Node v22.23.2 satisfies `.agents/package.json` engines
`^22.22.2 || ^24.15.0 || >=26.0.0`. Installed plugin/SDK 1.17.18. No install or
dependency changes. First probe attempt exited 1: `createRequire().resolve()` could
not resolve ESM-only SDK exports (`ERR_PACKAGE_PATH_NOT_EXPORTED`). The isolated
probe now directly imports the inspected installed SDK ESM entry; future product
keeps its normal TypeScript package import. Second run exited 0: 10 tests passed,
zero failures/skips/cancellations. Final rerun receipts are recorded below.

## Observed scenarios

1. Planning, isolated prototype, discovery and independent review overlap with
   distinct labels; recreating dispatcher loses no journal ownership.
2. Code and legacy implementation/fix/verification defaults exclude all workers
   in both admission orders, regardless of distinct labels.
3. Read/read shares; read/write, write/write and wildcard overlap refuse launch.
4. Concurrent starts from separate dispatcher instances create exactly one child
   when one request is exclusive.
5. Unknown existing child, lost create response, lost dispatch response and status
   outage fail closed after recreation; no replacement created.
6. Idle/no response, tool-calls/length, retry and resumed user turns are not terminal;
   a real terminal response releases claims observationally, not permanently.
7. Earlier meaningful assistant progress and tools survive an empty last tool turn;
   raw inputs/output/reasoning/tool title/error data do not appear. Tools bounded to 20.
8. Unrelated-parent polling/nested start denied; known cross-parent code claims and
   discovered unknown other-parent children block admission without sharing contents.
9. A second OS process holding `open('wx')` lock blocks creation; release permits
   admission. No timeout-based lock stealing or deletion of another owner's lock.
10. Invalid role/activity/claim names and corrupt journal refuse creation.

## What it proves and does not prove

Proves the stated bounded state model, installed SDK request serialization at an
external HTTP seam, real local filesystem lock contention and journal reuse across
dispatcher recreation. Tests assert observable admissions, counts and snapshots.
Does NOT prove a live server's persistence/compaction/message ordering, completeness
of session enumeration, crash/power-loss correctness on all filesystems, symlink
hardening, all production record validation, agent compliance with claims, model
permissions or no surviving processes after final/error. Existing Astra Low and
asset safety tests must remain; the prototype does not replace the untouched baseline.

The probe deliberately has a minimal journal schema and simplified prompt envelope,
progress fields and bootstrap. Production must add strict versioned validation,
canonical root/symlink checks, durable lock owner token, reservation ID/timestamps,
current+recorded-parent reconciliation, safe errors, bounded HTTP timeouts and
ownership summaries per the phase plan. No journal garbage collection, force unlock
or paid live smoke is proposed. Real filesystem tests are required again on the
implementation; this prototype is not promoted as a dependency.

Concrete carried-forward API:

```js
await client.session.create({ query: { directory },
  body: { parentID, title }, throwOnError: true });
await client.session.promptAsync({ path: { id }, query: { directory },
  body: { agent, model: { providerID: 'openai', modelID: 'gpt-6-astra' },
    parts: [{ type: 'text', text: envelope }, { type: 'text', text: prompt }] },
  throwOnError: true });
```

No `metadata` property is added to either SDK body. Durable authority is a private
journal, not prompt text. Resource labels are coordination declarations, not path
globs or permissions.

## Decision, review and cleanup

Carry the bounded design into an independently reviewed tooling phase. Reviewer
must baseline live untouched tooling and rerun this experiment. Writer self-check
is not independent PASS. Keep generated evidence/state until explicitly assigned
cleanup; never delete unknown roadmap data. No live tooling was changed.

## Final self-check receipt

All commands below ran from `/home/karl/repo/huron`. This is writer self-check,
NOT untouched live tooling baseline or independent verification.

| Command | Exit / observed output |
| --- | --- |
| `git diff --check` | 0; no output |
| `python roadmap/check_docs.py` | 0; `PASS: local documentation links/fragments, no tracked ignored-plan links, owned/untracked text whitespace, 000–010 phase cross-references/skills and 10 product phase structures` |
| `git check-ignore -v roadmap/dispatch-concurrency-design.md roadmap/prototypes/dispatch-concurrency roadmap/plans/dispatch-concurrency.md` | 0; all three matched `.gitignore:40:/roadmap/` |
| `git ls-files roadmap` | 0; empty output |
| `/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/dispatch-concurrency/probe.mjs` | 0; 10 tests, 10 pass, 0 fail/cancelled/skipped/todo; final measured duration 1118.594277 ms |
| `/home/karl/.nvm/versions/node/v22.23.2/bin/node roadmap/prototypes/dispatch-concurrency/check-owned.mjs` | 0; `Owned planning text: 5 files, whitespace/links/skills/phase sections OK` |
| `python --version` | 0; Python 3.14.0 |
| `git --version` | 0; git version 2.43.0 |
| `/home/karl/.nvm/versions/node/v22.23.2/bin/node --version` | 0; v22.23.2 |
| `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm --version` | 0; 10.9.8 |
| `git diff --stat` | 0; same initial/final tracked summary: 242 files changed, 1451 insertions(+), 16297 deletions(-), all pre-existing |

No public docs changed, so planning `make docs` is not applicable. Live
`.agents` `npm run check`, `npm test`, `node scripts/check-resolved.mjs` and root
`make docs` are deliberately NOT run here: independent reviewer owns the untouched
live tooling baseline and these are mandatory in the future phase gate. Their
outcomes are pending, not PASS. No application test suites apply.

Self-check found no remaining planning/prototype gate failure. Known initial
prototype import failure and its bounded correction are documented above.
SDK request `signal` support confirmed in installed `Config` extending `RequestInit`
and `RequestOptions` extending `Config`; future phase uses a 30-second abort signal.
No child agents, live API mutation, model calls, source/config edits or promotion.

Handoff: READY-FOR-REVIEW. Parent must provide fresh reviewer the full design/phase,
this evidence, exact planning gate and future live baseline gate. Reviewer inspects
assumptions/limitations and independently reruns, without treating receipts as proof.
