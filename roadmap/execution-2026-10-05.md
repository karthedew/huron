# Raw MVP execution and DOCS design ledger — 2026-10-05 label

Status: DRAFT — discovery reported; design writer gates passed, independent review pending.

## Orchestrator checkpoint — concurrency change accepted, restart pending

The user's subsequent request prioritized allowing concurrent independent non-code
subagents while keeping actual code implementation exclusive. This tooling slice
is now independently verified under [its phase receipt](plans/dispatch-concurrency.md):
review attempt 2 PASS, 55 tests and complete applicable gates passed, no open findings.
The running session still exposes the old serial schema. Quit and restart OpenCode
before using the new explicit activity/resource-claim API; inspect loaded tools first.

The Starlight design writer was `ses_ef62158f4ffedNPjwjMap4j0Fw`, terminal observed
2026-10-05 02:37 UTC. Its intermediate progress was observed by the parent, resolving
the earlier visibility uncertainty for that worker. Its four roadmap-only edits
remain pending independent design/checker review; Starlight is not implemented.

Dispatch concurrency children (all Astra Low, terminal):

| Task | Session | Outcome |
| --- | --- | --- |
| Design/prototype/phase writer | `ses_ef612e9b4ffeiUD19aiGTiknzC` | Ten prototype tests, plan ready for review |
| Independent plan review + untouched baseline | `ses_ef6041902ffeLjT19n0Ss57Ppy` | PASS; 15 live tooling tests |
| Exclusive implementation | `ses_ef5fe47f6ffeW99WQVa50taWmW` | Self-check green; 36 tests |
| Independent implementation review 1 | `ses_ef5e4658bffefLNgFfXlY9TKrY` | FAIL: raw SDK diagnostics could expose private details despite green gates |
| Privacy fix | `ses_ef5dddd86ffeHLMBPxd2ZlxgVl` | Red/green 18-case regression matrix; 55 tests |
| Independent implementation review 2 | `ses_ef5d8c796ffewBKlmQUCaDfRYs` | PASS; full rerun, 55 tests, no remaining findings |

After restart, resume the Raw MVP: independently review the existing Starlight
design/checker slice, run bounded reviewed docs/001 prototypes with nonconflicting
claims, and preserve all product/infrastructure decisions below. No product phase
or Starlight website completion is asserted by this tooling checkpoint. No sudo,
commits, user-data deletion, service takeover, or model/permission changes occurred.

## Current authority and ownership

### Current handoff — launcher active; Starlight design/checker PASS

The new serving environment exposes `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`; the
actual skill tool resolved `prototype` to the repository's canonical skill file.
Activation is confirmed, with no new config/plugin changes or restart needed.

Starlight F1 correction is independently PASS on maximum review 2
`ses_ef16989d2ffe7w6I5eoCqTGC73` (terminal observed 2026-10-06 00:31:57 UTC).
All 63 CLI cases passed (19 accepted, 44 rejected), plus the complete applicable
docs/whitespace/ignore/preservation gates. Original attempt's API error and timeout
left a known negative fixture; parent verified its timing/content and preserved
its exact bytes under `roadmap/checks/recovery/` rather than deleting it. A harness
expectation was corrected to include the existing empty-status whitespace error;
no validation was weakened. No live source or real plan was modified by the fix.

Next is the authorized isolated DOCS-P experiment at `roadmap/prototypes/starlight/`,
not another tooling redesign. Local commit `2b2e9c0` remains HEAD; unrelated dirty
work is preserved. Ignored checker/experiment artifacts are not committed. Public
Starlight site and Raw MVP product implementation remain pending their own gates.

### Latest handoff — source checkpoint committed; serving restart required

Local commit **`2b2e9c0c9d6b9beafef2e11b840f28535502aa6b`**:
`Consolidate agent tooling and enforce profile-aware dispatch`.
Its tree is the independently qualified
`028edc75f61292d3887be71f59f95f7e37625b40`; the parent verified exact tree equality,
empty staged diff after commit and clean whitespace. No push, branch creation,
hook bypass, global edit, sudo or unrelated cleanup occurred. The same 51 unrelated
tracked changes and four untracked product/design/scaffold files remain outside
the checkpoint. Ignored roadmap/prototype evidence is deliberately not committed.

Root-cause worker `ses_ef54d50ffffezcQ6dgASvNLs89` completed after the external reads
returned. It identified installed OpenCode 1.18.34's unbounded concurrent same-name
skill parsing, and the supported startup flag that excludes automatic external
skill scans while preserving explicit canonical registration. Global skills stayed
untouched. Exclusive maximum fix `ses_ef3aee631ffeeUZPnYb0UOks9N` added the launcher,
fail-fast resolved-check environment guard, docs and 20 focused regressions. Parent
corrected only the supplemental inventory expectation: 11 project skills plus the
separate allowed built-in, not 11 total entries.

Maximum independent checkpoint review 3 `ses_ef39a4415ffeYxgbAgyAK8cuxX`, dispatch
`b5787bfa-ca6d-456a-9701-c88be1e9f31c`, returned SOURCE PASS with no remaining
findings. Fresh exact export `/tmp/opencode/huron-checkpoint-JC6FJT6r` passed npm ci,
strict TypeScript/assets, 86 tests, 20 focused launcher tests, flagged resolved
checks, one fixed three-process canonical-inventory sequence and strict docs. No
retry-until-green. Git's raw index stat cache changed during export comparisons;
staged modes/blob IDs/tree and all unrelated content were verified unchanged.

**Immediate next action:** quit the current owned serving OpenCode process and,
from `/home/karl/repo/huron`, restart with:

```sh
sh .agents/scripts/opencode-project.sh
```

If using a separate server, restart that server through the launcher with its
intended arguments; attaching a flagged client to the old server is insufficient.
All workers are terminal. Current serving activation is not claimed by source or
fresh-CLI checks. After restart verify actual canonical loading, then fix the ignored
Starlight checker/template mismatch, re-review the docs design, and resume docs/SDK
prototypes and downstream MVP plans. Schema prototype review 2 remains a bounded
PASS, not product policy approval or production delivery. Its old preservation
fingerprints describe the earlier assignment epoch; later authorized tooling edits
and this commit must not be mistaken for prototype corruption or silently rebaselined.

Earlier blocked/waiting/uncommitted entries below are historical observations and
are superseded by this checkpoint receipt. Raw MVP and Starlight remain incomplete.

### Current checkpoint: Max qualification passed; local commits authorized

Latest bounded result: schema prototype maximum review 2
`ses_ef523c37dffeU9gzrARyTKHFS2` returned PASS after numeric-admission correction.
430 cases per seam (860 outcomes), plus independent 6,020 numeric/186 structural
outcomes, all bounded gates and preservation checks passed. Evidence is in
`roadmap/prototypes/schema/evidence.md` and phase001's updated execution ledger.
This qualifies an ignored prototype only; the narrower numeric profile is not
approved product policy, and nothing was promoted into production source.

At 07:11:45 UTC the tooling-root-cause worker remained busy/nonterminal on the
same external read/search begun about 06:14:24 UTC. Its cause remains unconfirmed;
parent requested human permission-prompt inspection and did not cancel, resume,
replace, widen permissions or mutate runtime state. No commit or push has been made.
The intended checkpoint remains staged; 51 unrelated tracked changes and four
untracked files remain outside it. Resolve that existing worker before exclusive
code or checkpoint-index operations; preserve the staged tree and all unknown data.

Runtime wait observation: root-cause discovery `ses_ef54d50ffffezcQ6dgASvNLs89`
is still submitted/busy with no terminal result; read of `/home/karl/.opencode`
and glob `**/src/skill/skill.ts` under `/home/karl` remain running since about
06:14:24 UTC. Parent inspected only safe tool-target metadata from a private CLI
export and confirmed the OpenCode process is alive. No cause of the wait is proven;
human inspection for external-directory permission prompts was requested. No
cancel/replay/replacement, permission widening or journal maintenance occurred.

Independent progress not relying on skill-name lookup: schema prototype writer
`ses_ef54624e6ffeD4LI60hgCgwJ1l` returned terminal self-check with 43 cases across
two candidate seams (86 outcomes), all bounded gates green and 535 Git-visible
files/index bytes preserved. Artifacts are only `roadmap/prototypes/schema/`.
Maximum reviewer `ses_ef53be358ffePC58OGZ2ioSv6K` is active; progress reports a
numeric round-trip/digest counterexample not covered by the fixed corpus. No
prototype acceptance or production validator completion is claimed pending verdict.

Later checkpoint qualification update: selected tree
`a1a4afc4bf332649146b726fc59fa0e560fbb591` is staged, not committed. Exact-export
review 1 blocked on assignment constraints (tracked dev.env and fixed temp-fixture
paths); those scopes were reconciled without changing source or tests. Review 2
`ses_ef55a982dffeoK5dFUYwiFsgmA` then passed 66 tests, strict docs and assets but
found intermittent noncanonical prototype skill resolution in check-resolved.
An unchanged pass does not erase the failure. Checkpoint qualification is FAIL,
two reviews used, and root-cause discovery is active. All 51 unrelated tracked
changes and four untracked product/design/scaffold files remain unstaged. No
commit, reset, cleanup, journal mutation or global skill change has occurred.

Restarted maximum smoke `ses_ef569164effe3rHjAx7BYPTG11` passed. Complete maximum
reviewer `ses_ef5681593ffe1n0p1ZrXj9xg1u` independently returned PASS on review 1:
66 tooling tests, eight probes and all applicable gates green, no open findings.
The profile tooling is verified; no Raw MVP or Starlight implementation completion
is inferred. Historical restart/qualification-pending statements below are superseded.

User explicitly requests periodic local commits to protect work; no pushes requested.
Read-only checkpoint audit `ses_ef5674424ffeoxhAZWm7WGwu03` identified a 230-path
canonical-tooling bundle (39 additions, ten modifications, 181 existing companion
deletions), excluding product/design/web/minihuron/scaffold work and ignored artifacts.
Parent accepts existing instruction/skill policy adaptations as part of the tooling
checkpoint, preserving their explicit current-versus-target framing, not claiming
authorship or delivered domain behavior. Selected-index validation precedes commit.

### Astra Max bootstrap staged — new restart required

Effort discovery `ses_ef5b3f3d9ffeR5DL19194wlcH1` subsequently completed: actual
registered maximum is `max`, not `xhigh`; prior file-read wait is resolved. The
profile design/probe writer `ses_ef590afc4ffei81X14yro6LxWV`, preparatory review 1
`ses_ef5865f75ffee7YdYyZmAn0ou3`, ignored-probe fix
`ses_ef581dde0ffeMwuNAZAl0Y4Jwr`, and preparatory review 2
`ses_ef57e602affeWD5gkbfOi58iU4` are all terminal. Review 2 PASS cleared the
exclusive parent bootstrap after the draft-only probe assertion was corrected.

Parent implemented the 25-file tooling allowlist in
[astra-effort-profiles.md](plans/astra-effort-profiles.md). All deterministic
self-checks pass: 66 tooling tests, eight prototype tests, strict TypeScript/assets,
strict docs, local links/whitespace, safe five-agent and registered-Max checks.
This is not independent complete qualification. No Low code worker was launched,
no runtime journal migration was performed, and no product behavior is marked shipped.

**Immediate handoff:** quit/restart OpenCode, verify loaded profile selector, run
maximum read-only smoke and maximum independent complete bootstrap qualification.
Then resolve the Starlight checker/template mismatch using a maximum code worker,
re-review the docs design, and resume reviewed docs/schema/SDK prototypes. The
scientific MVP's data/identity/stale-base/NFS/SLO and no-sudo runner issues below
remain explicit. No sudo, commits, user-data deletion or service takeover occurred.

### Resumed preparation and new effort requirement

On resume, the actual loaded tool exposed activity/claims. Two independent
non-code tasks were admitted concurrently, with visible retained progress and
validated ownership. The canonical dictionary is [resource-ledger.md](resource-ledger.md).

- Starlight review 1: `ses_ef5b92a68ffe9m84aKRmItnEmZ`, dispatch
  `293d0e3f-9c4a-45ef-9cda-d85ffba33918`; terminal BLOCKED. All current gates
  passed (11 accepted/9 rejected lifecycle cases; 19 local links), but the checker
  rejects the current canonical `Per-subject serial task slices` heading. Align
  checker/template handling without weakening missing-section rejection, then
  independently re-review (attempt 2). No other Starlight design findings.
- Raw readiness discovery: `ses_ef5b87fabffe8TOncW8DDFbBZd`, dispatch
  `2627dd6c-c037-417f-93ec-d0f2fb023286`; terminal discovery report, not product PASS.
  Schema composition (30 cases) and SDK namespace/install isolation are bounded
  independent next probes. Full 002 symbol/consumer mapping remains incomplete;
  Security must not import Catalog merely to replace foundation names/errors.
  The no-sudo full runner remains unqualified. Existing local image
  `huron-cutover-runner:local` was inventoried but not started; do not substitute
  the shared host Docker socket for the required private rootful Podman engine.
- User now requires Astra maximum supported effort for actual-code subagents and
  final complete qualification. Current preparatory workers remain Low; do not
  launch actual-code or final-qualification workers at Low. The current dispatcher
  hardcodes Low, so a verified profile/configuration cutover and restart are needed.
  Preparatory effort discovery `ses_ef5b3f3d9ffeR5DL19194wlcH1`, dispatch
  `5da56a4d-76ed-41cc-a11e-fc4e419733b4`, is active; no outcome asserted yet.

Effort-discovery observation at 2026-10-05 04:29:59 UTC: still busy/nonterminal,
same read operation running since about 04:23:14 UTC, no retained assistant progress.
OpenCode process is alive; the status API does not identify the cause of this wait.
Parent requested human inspection of that child for a possible permission prompt.
No cancellation, replay, replacement, journal/lock maintenance or profile change
was attempted. Reconcile this existing child before code or runtime changes; do
not infer a completed baseline or maximum-effort capability from partial activity.

No product code, service, data migration or Starlight site implementation occurred
in these preparatory tasks. Earlier "restart pending" statements above describe
the previous concurrency cutover, which is now loaded; effort selection is a new
requirement, not an already activated feature.

User authorizes Raw MVP implementation, Docker and workspace writes without asking,
and adds detailed developer + user documentation built with Starlight under docs.
Never sudo. This authorization supersedes historical tooling/plans-only authority,
but does not approve data destruction, unresolved product decisions or unreviewed
phases. Preserve data by default. No commits, branches, pushes, issues, production
promotion, reset, clean, stash or unknown-data deletion. This worker's bounded
DESIGN-PLAN assignment additionally forbids product/docs/build/agent edits,
prototype execution, delegation and service startup.

The filename is the user-assigned execution label; environment date supplied to
this worker is 2026-10-04. No invented elapsed/date alignment. Current navigation:
[delivery map](README.md), [DOCS design](starlight-design.md), canonical
[Raw-first target](../design/raw-first.md) and [history](../docs/history.md).

Initial `git status --short` and `git ls-files roadmap` captured in writer tool
transcript before edits, HEAD `9082f6b`. Extensive pre-existing user-owned changes:
deleted retired .agents/.claude/.opencode assets; modified retained skills, agent
configuration, AGENTS, CONTEXT, root README, design HTML/Markdown and public docs;
deleted root legacy plans, design/roadmap.html, minihuron files and old agent docs;
modified web README/API README/client/types/fixtures; untracked canonical .agents
tooling/commands/skills/workflows/templates, design/raw-first.md and catalog/interface
scaffolding. All are preserved, including unknown ignored data. No tracked roadmap
files. Existing ignored roadmap README/checker/plans/archive are prior work, not
ours to replace wholesale.

This writer owns ONLY new `roadmap/execution-2026-10-05.md`, new
`roadmap/starlight-design.md`, current-authority/status edits in `roadmap/README.md`,
and the explicit lifecycle-state validation in `roadmap/check_docs.py`. Disposable
checker validation may create/remove its own unique temporary plan under roadmap;
no existing phase status changes. Historical receipts remain intact.

## Dispatch and progress evidence

| Task / role / attempt | Session and evidence | Status |
| --- | --- | --- |
| Prior independent planning review 2 | `ses_ef6f04eecffeCukg30YALrUP8A`, historical README receipt | Prior planning PASS only, not current product proof |
| Parent discovery / verification | `ses_ef626fdecffeIgfmz2dMoAL4vR`, terminal report supplied by parent | Report claims discovery checks pass; no product baseline performed |
| Current design writer / implementation role / attempt 1 | openai/gpt-6-astra; current child ID not exposed to worker, parent must record dispatch ID | No nested agents; independent review count 0 |

Discovery observability limitation: parent reports the tool exposed final assistant
text but no intermediate tools/text. A terminal report is not proof that progress
was observable while work ran. This writer sent initial visible commentary before
inspection and ongoing commentary around 8 and 15 elapsed minutes, including
validation progress; parent must confirm actual delivery, poll at least once/minute
and relay progress. If intermediate visibility still fails, record that limitation
and agree checkpoint/resume rather than pretend the tool has live telemetry.

## Discovery evidence and writer reinspection

Parent-supplied discovery report: root `make docs`, `python roadmap/check_docs.py`
and `git diff --check` pass; no tracked roadmap files. Existing Project, numbered-part
uploads, placeholder search and fixture web mean phases 002–010 are not ready.
No application baseline was run. Exact discovery command logs/exits beyond these
reported checks were not supplied to this worker; do not invent them.

Writer reinspection before edits, cwd `/home/karl/repo/huron`:

| Exact command or source | Observed result |
| --- | --- |
| `make docs` | Exit 0, strict Zensical build, no issues, 0.22 s |
| `git diff --check` | Exit 0, no diagnostics |
| `python roadmap/check_docs.py` | Exit 0, all existing checks pass |
| `git ls-files roadmap` | Exit 0, empty |
| `node --version` | Exit 0, v20.17.0 |
| `/home/karl/.nvm/versions/node/v22.23.2/bin/node --version` | Exit 0, v22.23.2 |
| `id -u` | UID 1000, nonroot |
| `command -v podman` | No executable returned; absent |
| `docker info --format '{{.ServerVersion}}'` | Server responds, 27.2.1 |
| `docker compose ps -a --format json` | Empty; no Huron Compose containers reported |
| `getent hosts keycloak` | No result; hostname unresolved |
| `findmnt -t nfs,nfs4` | No mounts returned; no actual NFS evidence |
| `ss -ltnp` | 5173/8000/9000/5432 listening, plus other services; process ownership not available in this output, do not operate them |
| tests/integration/test_protocol_cutover.py:97–105 | Linux nonroot invokes sudo -n; test forbidden under this user's no-sudo rule, not executed |
| Makefile + docker-compose.yml | Current stack excludes frontend/directory/Raw volume/k6; make hosts invokes sudo and must not run |
| Plans 001–010 read in full | Missing prototype/decision/inventory evidence; authorization text is historical, not proof that slices are ready |

The host probes above were one semicolon-separated read-only command; only its
final npm query's aggregate exit 0 was returned. Individual no-result probe exit
codes were not captured; absence findings are from output, not invented per-command
PASS receipts. No services, migrations, browser sessions or load started.

Registry/API evidence: five npm queries in the DOCS design exited successfully
(initial batch and exact-pin batch); live official Starlight docs fetched. Candidate
Starlight 0.42.5 / Astro 7.3.5 / markdown-remark 7.3.0 is registry-qualified only,
not installed or build-qualified. Node >=22.12.0 and npm >=9.6.5 required by candidate
Astro. Prototype must inspect exact dependencies/exports and lock them.

## Readiness blockers and next serial slices

| Owner | Blocker / disposition | Next evidence |
| --- | --- | --- |
| Data owner/user | Existing datasets/volumes unknown; preserve, no fresh-deployment approval inferred | Inventory, backup/rehearsal and explicit migration/disposition decision before touching existing data |
| Identity owner/user | SDK token issuer/broker and Keycloak role unresolved; host keycloak DNS absent | Compare qualified audience-bound credential providers; no-sudo topology decision, no Google ID-token bearer shortcut |
| Product owner/user | Stale-base policy unresolved | Explicit accept/reject fail-conflict recommendation before publication conflict implementation |
| Operator/user | Actual NFS hardware/capacity unavailable | Nominate mount/topology and capacity; local probes cannot certify NFS |
| Operator/user after baseline | Time SLO deliberately not approved yet | 010 preflight → NFS proof → baseline → approve SLO → rerun; never gate baseline on its own future SLO |
| Environment/test owner | Full integration requires privileged isolated Podman provider; no Podman here and sudo prohibited | Provision an approved isolated runner externally or reviewed no-sudo infrastructure plan; no deselection, skips or weakened contract |
| Prototype owners | Schema/fencing/recovery/freshness/packaging/query/session/k6 evidence and exact cutover inventories absent | Reviewed bounded 001 assignments, isolate owned resources, preserve phase gates |
| DOCS owner | Design/prototype/build/link/search evidence and independent review absent | Review starlight-design, prototype under roadmap/prototypes/starlight, then self-contained named docs plan |
| Parent/runtime owner | Discovery intermediate progress not visible | Confirm writer commentary delivery; record current child ID and agree checkpoints if unavailable |

Broad authorization removes the need to ask again for ordinary in-scope workspace/
Docker work. It does not waive review, resource ownership, missing infrastructure
or substantive user decisions. Parent reconciles historical authorization language
in affected phase contracts through a separately owned planner slice before dispatch.
This writer does not mark any product phase ready or edit its status.

Next slices: independent read-only design/authority/checker review; then DOCS-P
locked site experiment; independently bounded 001 decision/prototype assignments;
application baseline on approved infrastructure before any product edits; phase
planner incorporates evidence and explicit exact scopes/gates. Product 002–010
dependency chain unchanged. DOCS foundation may proceed without those outputs,
but usable scientist/API/operations examples await the respective verified slices.

## Lifecycle checker contract and disposable reproduction

Existing checker is the public CLI; no existing `check_docs` test coverage found by
test-file search. Reuse the real 001 contract as temporary fixture rather than
introducing product pytest fixtures. Accept exactly one explicit line with state
draft / blocked / ready / implementing / verified (case-insensitive), optionally
followed by space + dash/en-dash/em-dash + explanation. Reject missing, duplicate,
unknown and slash-combined states. The old `Status: BLOCKED — DRAFT ...` remains
valid: BLOCKED is the state, remainder explanation. Other section/skill/reference/
link/whitespace/gate checks remain unchanged; 000 historical exception remains.
This validates syntax, not evidence or legal historical transition ordering: a
reviewer must substantiate READY/VERIFIED and record regressions back to BLOCKED.

Reproduction, root cwd; creates a unique disposable plan and removes only that file:

```sh
python - <<'PY'
import pathlib, re, subprocess, tempfile
root = pathlib.Path.cwd()
source = (root / 'roadmap/plans/001-decisions-prototypes.md').read_text()
with tempfile.NamedTemporaryFile(mode='w', suffix='.md', prefix='lifecycle-probe-',
                                 dir=root / 'roadmap/plans', delete=True) as fixture:
    cases = [(s, True) for s in ('draft', 'blocked', 'ready', 'implementing', 'verified',
                                 'DRAFT', 'BLOCKED', 'READY', 'IMPLEMENTING', 'VERIFIED',
                                 'ready — independently reviewed')]
    cases += [(s, False) for s in ('PASS', 'ready/blocked', 'readyish', '',
                                   'ready\nStatus: blocked')]
    for status, accepted in cases:
        text = re.sub(r'^Status:.*$', 'Status: ' + status, source, count=1, flags=re.M)
        fixture.seek(0); fixture.truncate(); fixture.write(text); fixture.flush()
        result = subprocess.run(['python', 'roadmap/check_docs.py'], capture_output=True, text=True)
        assert (result.returncode == 0) == accepted, (status, result.stdout, result.stderr)
        if not accepted:
            assert 'expected one explicit lifecycle Status:' in result.stdout, result.stdout
        print(repr(status), 'exit', result.returncode)
    for old, new, diagnostic in [
        ('Status: BLOCKED', 'State: BLOCKED', 'expected one explicit lifecycle Status:'),
        ('## Skills', '## Missing skills heading', 'missing phase section Skills'),
        ('make docs', 'make absent', 'missing readiness/gate marker make docs'),
        ('.agents/skills/design-plan/SKILL.md', '.agents/skills/nonexistent/SKILL.md', 'missing local skill'),
    ]:
        fixture.seek(0); fixture.truncate(); fixture.write(source.replace(old, new)); fixture.flush()
        result = subprocess.run(['python', 'roadmap/check_docs.py'], capture_output=True, text=True)
        assert result.returncode == 1 and diagnostic in result.stdout, result.stdout
        print(diagnostic, 'exit', result.returncode)
print('PASS: 11 accepted, 9 rejected; existing phase statuses untouched')
PY
```

## Applicable gate and final writer receipt

Root cwd: `make docs`; `git diff --check`; `python roadmap/check_docs.py`;
`git check-ignore -v roadmap/execution-2026-10-05.md roadmap/starlight-design.md`;
`git ls-files roadmap` (must be empty), plus disposable validation above and all
new text's whitespace/local links/fragments. No product Python/frontend or agent
asset changes: no application/agent suite claimed. This self-check cannot substitute
for independent baseline/reviewer execution. Evidence is the writer tool transcript
and this ledger; no fabricated external log paths.

### Writer attempt 1 outcomes (self-check, not independent PASS)

| Cwd | Command | Exit / evidence |
| --- | --- | --- |
| root | `make docs` | 0, strict existing Zensical build, no issues, 0.21 s |
| root | `git diff --check` | 0, no diagnostics; ignored text additionally checked below |
| root | `python roadmap/check_docs.py` | 0, existing links/fragments/whitespace/skills/phase-reference/structure checks retained |
| root | `git check-ignore -v roadmap/execution-2026-10-05.md roadmap/starlight-design.md` | 0, both match .gitignore:40 /roadmap/ |
| root | `git ls-files roadmap` | 0, empty |
| root | Disposable Python heredoc above | 0 aggregate; 11 accepted cases exit 0, 9 rejection cases exit 1 with expected diagnostics; own temporary fixture removed |
| root | Owned text/link Python heredoc below | 0; four owned text files, 18 local links/fragments valid |

Exact additional new-text/link check (external links fetched separately as documented,
not assumed validated by this local check):

```sh
python - <<'PY'
from pathlib import Path
from urllib.parse import urlsplit, unquote
import re
root = Path.cwd()
files = [root / 'roadmap' / name for name in ('README.md', 'execution-2026-10-05.md', 'starlight-design.md', 'check_docs.py')]
count = 0
for path in files:
    text = path.read_text()
    assert all(line == line.rstrip() for line in text.splitlines()), path
    if path.suffix != '.md':
        continue
    scan = re.sub(r'```.*?```', '', text, flags=re.S)
    for link in re.findall(r'!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+[^)]*)?\)', scan):
        url = urlsplit(link)
        if url.scheme or url.netloc:
            continue
        target = (path.parent / unquote(url.path)).resolve() if url.path else path
        assert target.exists(), (path, link)
        if url.fragment:
            body = target.read_text()
            anchors = set(re.findall(r'\b(?:id|name)=["\']([^"\']+)', body))
            seen = {}
            for heading in re.findall(r'^#{1,6}\s+(.+)$', body, re.M):
                slug = re.sub(r'[^\w\- ]', '', heading.replace('`', '').lower()).replace(' ', '-')
                n = seen.get(slug, 0); seen[slug] = n + 1
                anchors.add(slug + (f'-{n}' if n else ''))
            assert unquote(url.fragment) in anchors, (path, link)
        count += 1
print(f'PASS: {len(files)} owned text files; {count} local links/fragments')
PY
```

Acceptance self-audit: current authority supersedes old restrictions without deleting
history; all 14 live docs assets mapped; detailed user/developer/operations content
owned and labelled; explicit dependency/build/CI/deletion ownership; official API
and registry evidence qualified as not installed; bounded prototype happy/error
reproductions assigned; no product execution/completion or docs readiness claim.
No application baseline, independent review or browser evidence produced. Parent
records this child's dispatch ID and reviews before advancing. No prototype promoted.
