# M11 plan handoff for a new session

Date: 2026-11-09. **BLOCKED: plan not accepted; no production implementation.**
This handoff requests focused planning reconciliation and independent maximum-profile
plan review only. It neither resolves the defect itself nor authorizes implementation,
new probes, service changes, or P00 execution.

## Read order and authority

1. Read [AGENTS.md](AGENTS.md), then the local
   [orchestration](.agents/workflows/orchestration.md) and
   [verification](.agents/workflows/verification.md) contracts.
2. Load [implementation-plan](.agents/skills/huron-implementation-plan/SKILL.md),
   [design-plan](.agents/skills/huron-design-plan/SKILL.md), their
   [phase](.agents/templates/phase-plan.md) and
   [design](.agents/templates/design-plan.md) templates, and
   [domain guidance](docs/agents/domain.md).
3. Read [IMPLEMENTATION_PLAN_LATEST.md](IMPLEMENTATION_PLAN_LATEST.md), especially
   §12, then §3.5, P22/P23/P27b/P33/P34, gates, blockers and the failure ledger.
4. Read the three durable records:
   [architecture](design/m11-production-architecture.md),
   [review evidence](design/m11-review-evidence.md), and
   [prototype evidence](design/m11-prototype-evidence.md).
5. Inspect the token producer and callers below. Read the relevant historical M11.11
   smoke contract in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md):5220–5226.
   Keep the old plan unchanged; its unaffected sections 3–9 remain binding.

Canonical `asd-ste100` and `writing-for-agents` are missing. This is recorded policy
drift, not permission to fetch skills or edit tooling. Do not claim formal skill
qualification. No broad research is needed unless new evidence changes the finding.

## Preserved work and current checkpoint

Read-only checks for this handoff confirmed the supplied baseline still matches:

- HEAD `0dcdf1ff6a8689f704a73a0758a886c18b5d3584`, branch `tusd-integration`.
- Reference `m11.5-escalated`: `04958ad538eac69f16a6abdd3925350781e4d718`.
- User-dirty old-plan working-file blob: `862e1bafc54c5ca88b0351ff7ee723662a1ac7f8`.
- `migrations/versions/0003_uploads.py` blob: `83757f7e73640356639ae07c45d7885660b9a6e3`.

Recheck HEAD, status, refs and hashes in the new session before claiming they are current.
The exact initial dirty inventory is in review evidence §2. Preserve all M11.5e repair
work, tests, generated contracts, user tooling corrections and unknown data. The prior
session added four owned plan/design documents plus isolated ignored experiments; it
did not implement production changes. This handoff is the only addition in its assignment.
No reset, revert, clean, stash, commit, push, branch deletion or automatic cleanup.

The draft retains 42 serial slices, all 19 M11 mappings and F1–F7/O1–O16. Bounded
architecture and narrow prototype reviews passed; complete maximum plan reviews
1, 2 and 3 **all failed**. Historical or dirty product suites are not current PASS evidence.

Final reviewer: `ses_e412ba125ffeV3Y9o1hLnuYhTi`;
dispatch `35183e84-9e73-4a28-9bed-1ea7e0a7deb9`.
Terminal FAIL: `2026-11-09T05:53:13.859Z`; observed: `2026-11-09T05:53:43.997Z`.
The configured profile was maximum/max; provider effort acceptance was not proven.

## Sole remaining review finding: R3-1

**MEDIUM, PLAN DEFECT: token producer cutover has no owner.**

The proposed versioned `TokenState` requires destination approval and credential
provenance, and refuses legacy credentials. However, `scripts/dev-login.sh:23–40`
still acquires/exchanges credentials directly and writes the old four-field document
with truncating file I/O. It bypasses the proposed root lock and atomic state writer.
Changing one JSON line cannot supply an approved authentication/state transaction.

Verified consumers and obligations:

- `scripts/e2e.sh:77–81` sources the helper and switches development identities.
- `scripts/demo-noaa.sh:57–66` sources it before its first authenticated CLI read;
  it uses a persistent, isolated demo state directory.
- `Makefile:56–57` exposes `make demo-noaa`.
- `examples/noaa/README.md:97–104` documents direct helper use; README describes
  the demo and e2e workflows. Inventory these references when choosing retirement.
- Historical M11.11 smoke uses the helper and writes a token into pod state. P34's
  replacement smoke must account for that producer too; historical text is not edited.

P27b currently switches CLI callers but omits the shell producer. P33 owns e2e work
without the complete authentication cutover. Plan an explicit owner and ordering:
either migrate development authentication through fresh, explicitly approved login,
new credential collaborators, root lock and atomic state; or retire the helper and
replace **every** caller and documented target. Select one approach, not an unresolved
choice left to an implementer. Specify the dev-only trust/approval input and its public
interface; do not add a production bypass or implicit approval via configuration.

Never stamp current configuration onto old tokens, decode them as provenance, weaken
legacy refusal, forward old credentials to a new destination, or discard old working
state. Preserve non-disclosure before identity/refresh/exchange, including valid and
expiring credentials. This is a CLI/development-workflow seam, not publication redesign.

## Scope of the reconciliation

Proposed edit ownership is **only these four documents**, after parent admission:

| Document | Intended change |
| --- | --- |
| `IMPLEMENTATION_PLAN_LATEST.md` | Concrete producer/caller ownership, ordering, interfaces, tests and full gates in affected slices; new reconciliation receipt without erasing §12 |
| `design/m11-production-architecture.md` | Focused development-authentication decision and current handoff status |
| `design/m11-review-evidence.md` | Inspected producer/consumer evidence, R3-1 disposition and preserved failure history |
| `design/m11-prototype-evidence.md` | Status/history and explicit untested limits only; no invented probe result |

Source, shell scripts, tests, Makefile, examples and other docs are inspected, **not
edited now**. Future implementation ownership must be named precisely in the plan,
including any replacement helper, subprocess tests, callers, targets and documentation.
Do not silently broaden this planning assignment to repair them.

Carry forward all resolved corrections:

- P07 isolated test-only PostgreSQL composition and caller transition; delete it at
  P27c without removing real-PG assertions or adding a production bypass.
- Durable working-copy/upload/commit instance, principal and endpoint binding.
- LOCAL destination approval and provenance checks before any bearer, refresh,
  exchange or authenticated identity request; fresh endpoint-specific login.
- Atomic endpoint-acceptance transaction and preservation after abort/failure.
- CLI root `LAYOUT`, single context group, `test_panels` and strict reference ownership.

## Review-cycle admission and runtime rules

The user said, “we can try fourth iteration.” This expresses willingness to continue,
not an exception to the repository's three-review cap. The parent explained that the
next step must be substantive `/implementation-plan` reconciliation and scoped review,
not automatic review4, renaming the same slice, or resetting review counts.
The new parent must read the current lifecycle and record the actual reconciliation.
If review-cycle admission remains unclear, escalate before dispatch; do not bypass it
or promise acceptance. Preserve FAIL/FAIL/FAIL and every earlier finding disposition.

Check loaded readiness anew. Tooling schema was already corrected; do not repeat those
fixes. Actual `implementation_start` fields are role, title, prompt, activity, claims,
profile. Use actual available tools/status, not Task, a second server, manual resume
or history edits. Missing launch/status capability requires reconciliation/restart.
All previous children were terminal as last observed, not freshly verified here;
direct-child status does not imply access to another parent's session history.
Unknown journal state blocks admission; never steal locks or replay uncertain launches.

Use serial conservative `*:write` coordination, mapping it to the entire repository
and check artifacts, not permission to edit everything. A planning writer may use
preparatory Low; independent complete plan qualification requires verification/review
with explicit maximum Astra. Actual code/fixes require separate maximum exclusive
code dispatches and are outside this session. Record configured effort separately
from observed evidence; historical v1 profiles remain not-recorded.
Poll quietly at least once per minute. Workers send 2–4 line progress at least every
15 minutes, including validation, with phase/role/attempt, elapsed time, concrete
progress, command and next step. Report blockers, repeated failures and hangs immediately.
Never put credentials in progress, tool titles, evidence or the handoff.

## Acceptance checklist for the next planning session

- [ ] Inventory every credential producer and shell/demo/e2e/smoke consumer; give each
  a named cutover owner, exact future file/symbol scope and acyclic dependencies.
- [ ] Specify one fresh approved authentication or retirement/replacement design using
  new collaborators, stable root lock and atomic state; legacy refusal stays intact.
- [ ] Require subprocess/public-behavior tests with isolated XDG roots: successful
  fresh login followed by real CLI use; malformed/legacy state; failed/declined approval;
  changed destinations/provenance; lock contention; interrupted saves; old state retained.
- [ ] Require observable zero credential delivery to unapproved endpoints, not merely
  a private helper call assertion. Reuse existing fixtures; retain real-adapter tests.
- [ ] Preserve complete e2e, demo and deployment smoke obligations with exact commands,
  prerequisites and isolated resource ownership. Syntax checks alone are not acceptance.
- [ ] Retain 42 slices/19 mappings/F/O traceability and all earlier corrections, or
  explicitly justify and independently review any necessary structural change.
- [ ] Preserve thresholds, assertions and full applicable future gates; no skips,
  xfails, exclusions or reduced coverage to manufacture success. No tests are added now.
- [ ] Run prose checks below; record independent review only after legitimate admission
  and terminal evidence. Keep BLOCKED if acceptance or required evidence is absent.

## Prose checks and later qualification

Run from `/home/karl/repo/huron-tusd`:

```sh
uv run --offline --no-sync python scripts/check_links.py HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md
git diff --check
git diff --cached --check
```

Also run `git diff --no-index --check /dev/null <doc>` separately for each owned
untracked document (including this handoff when validating it). Exit 1 with no
diagnostics means additions, not whitespace failure. Root diff has a known existing
failure at `web/src/lib/api/openapi.ts:170`; preserve and attribute it. Check links'
anchors manually where necessary; the checker validates relative file existence.

Root/design prose does not require product or site suites. Future code gates remain
the plan's actual `UV_OFFLINE=1 UV_NO_SYNC=1 make gate`, contract/integration and all
affected e2e/smoke/deployment gates. Do not substitute the invalid `unit` marker,
nonexistent current `test-acceptance` target or no-op `make docs` for real checks.
No installs, service starts or tooling corrections are authorized here.

## Retained experiments and external blockers

Ignored artifacts live under `roadmap/prototypes/m11-production/__pycache__/attempt2`.
Actual selected Placer/StateDir/_recover defects and six tiny real-PG/FS logical
reconnects were observed. They do not prove full process-crash, tusd, NFS or quotas.
Seven durable artifact hashes and the precise limitations are in prototype evidence §5.
The first loopback setup failed; private bridge access was later parent-authorized.

Retained container `huron-m11-production-a1`, ID
`ca0aac2e123e4f18dea1ece653ca62f4c6555a46059a46271cd9ca63ec206936`, was last stopped/PID 0.
Network `huron-m11-production-a1-net`, volume `huron-m11-production-a1-pg`, four probe
databases and failed evidence remain. No restart or deletion is needed or authorized.
Future use requires fresh ownership/process reconciliation. Missing offline tusd/nginx/
Helm assets, ONTAP and workload evidence are downstream qualification gates, not the
sole remaining reason for this plan review's FAIL. P00 is separately admissible
discovery, never auto-run from this handoff.

## Copy-paste prompt for the new session

> Read HANDOFF_M11_PLAN.md and its ordered sources. Perform focused substantive
> /implementation-plan reconciliation of R3-1 (development token producer and all
> callers), with edits limited to the four named plan/design documents. Preserve all
> dirty work, earlier corrections, FAIL/FAIL/FAIL ledger and the three-review cap.
> Resolve review-cycle admission explicitly; escalate if unclear, rather than launch
> review4 or reset counts. Then obtain a legitimately admitted independent maximum
> plan review. No production implementation, probes, service changes, tooling fixes,
> installs or P00 execution. Run the exact prose gates and report actual outcomes;
> keep the plan BLOCKED unless independent acceptance is established.
