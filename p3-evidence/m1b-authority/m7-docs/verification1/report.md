# M7 — Documentation reconciliation (T6): independent verification 1

Date: 2026-09-12. Repository: `/home/karl/repo/huron`, branch `p3/integrity-and-raw-flows`,
HEAD `e22d000` with the plan's uncommitted working tree. Attempt 1 of 3.

## Verdict: PASS

Every `P3_M1B_AUTHORITY_DESIGN.md` "Design: T6" §1.1–§1.9 passage was applied literally,
nothing outside the edit list changed, both §2 invariant greps match the expected residual
list, `make docs` builds strict-clean, and no `src`/`tests` file moved. Receipts in this
directory; the passage-by-passage evidence is `passages.log`.

Scope note: this report covers the tree as M7 left it. M8 subsequently appended one dated
line to `P3_EXECUTION.md` under the 2026-09-12 section; that line is M8's, expected, and
out of this verification's scope.

## Per-document confirmation

| Document | Passages checked | Deviations |
| --- | --- | --- |
| `P3_DESIGN.md` | `:3`, `:72`, step 1, step 4 last sentence, step 6, texts A/B/C; `:258–264` and `:290–296` left unchanged | None. All texts verbatim (line rewrapping only); `git diff` is exactly four hunks, all inside the listed passages |
| `docs/operations/controlled-cutover.md` | `:37–38`, `:100`, text D (`:113–116`), text E as two new `##` sections inserted before `## Verification evidence`; `:117–120` and `:122–128` unchanged | None. Headings now `:137 Verification epoch`, `:182 Recovering a lost reply`, `:200 Verification evidence` |
| `P3_M1B_VALIDATION.md` | `:3–7`, `:26–33`; `:15` "1,628 passed" kept per open question 3 | None. Two hunks only; dated tense preserved with a superseding note |
| `P3_EXECUTION.md` | text F (M1b row), text G (M1c row), `:45`, `:85`, `:269–270`, appended `## Architectural review and authority design — 2026-09-12` | None. Four hunks; the new section is at end of file |
| `P3_IMPLEMENTATION_PLAN.md` | `:5–7`, item 6, `:182–183`, `:184`, `:197–199`, M1c item 1, `:538`, `### Resolution` at the end of `## Escalation`; `:486–534` and `:548` untouched | None. Escalation history bytes unchanged |
| `design/layer-raw.html` | `:166` `<p class="note">`, `:291` `<strong>` | None. Two hunks only |
| `design/core-map.html` (staged `A`) | all seven rows: `:165` symbols + description, `:336`, `:339`, `:340`, `:343`, `:346`, `:363`, `:391` | Replacement texts all verbatim; index matches worktree. Two formatting/pin notes below, neither a content deviation |
| `CONTEXT.md` | `:31` glossary line | None. One line |

`design/core-map.html` notes: (a) the `:165` symbol list is rendered as one `<code>`
element per symbol, matching the table's existing convention rather than the design cell's
single backtick span — content identical; (b) `establish` and `exclude` now sit at `:338`
and `:339` where T6 pinned `:339`/`:340`, while `:165`, `:336`, `:343`, `:345`, `:346`,
`:363` and `:391` land exactly. The `:343` replacement is a whole `<li>` element, so one
list-item boundary inside the same `<ol>` moved. The file is untracked with no HEAD blob
and no scratch copy anywhere on disk, so this cannot be diffed; every original sentence
(authenticate, claim, `_Fence.check`/`monitor`, `GenerationVerifier`, the scan,
`resolve`/`_publish`) is still present, so no content was lost.

## Invariant-grep residual comparison

Status grep (`grep-status.log`, exit 0) — four matches, exactly T6 §2's expected other
senses (design pins in brackets):

| Match | Expected |
| --- | --- |
| `P3_DESIGN.md:510` "An interrupted operation is pending" | yes (`:488`, +22 = this file's cumulative diff delta) |
| `P3_EXECUTION.md:187` "Its verdict is pending" | yes (`:188`, −1) |
| `design/layer-raw.html:344` "(under validation; …)" | yes |
| `design/layer-raw.html:703` "pending removal" | yes |

Banned-sense grep (`grep-banned-sense.log`, exit 0) — eighteen matches:

| Match | Expected |
| --- | --- |
| `P3_M1B_VALIDATION.md:36,37,38,40` | yes — pinned `:26–33` (+8), rewritten as attempt-3 history |
| `P3_EXECUTION.md:231,244,259,260` | yes — pinned `:232,245,260–261` (−1), dated verification history |
| `P3_IMPLEMENTATION_PLAN.md:507,509,514,522,543` | yes — pinned `:494–531` (+13), escalation history |
| `P3_DESIGN.md:501`, `P3_IMPLEMENTATION_PLAN.md:349` | yes — the out-of-scope M3-recovery sense of "indeterminate" (`:479`, `:336`) |
| `P3_EXECUTION.md:274` | new, accepted — T6 §1.4's mandated 2026-09-12 entry names `validate_certificate` and `CertificationIndeterminateError` verbatim |
| `P3_IMPLEMENTATION_PLAN.md:598` | new, accepted — T6 §1.5's mandated `### Resolution` text contains "nothing is re-endorsed" |

Both new lines were diffed against the design's literal replacement texts before being
accepted; neither is an editorial addition.

T6 §3 deletions: all 26 probed strings absent (`passages.log` section D). The single
residual, `CertificationIndeterminateError` in `P3_EXECUTION.md`, is the mandated entry
above; §3 scopes that symbol's deletion to `design/core-map.html:165`, which is clean.

## Gate results

- `make docs` (= `uv run --group docs zensical build --strict` over `docs/` per
  `Makefile:72–73` and `zensical.toml` nav): exit 0, "No issues found" (`docs.log`).
  The built page carries `id="verification-epoch"`, `id="recovering-a-lost-reply"`, one
  rendered `admonition note`, and the ADR link resolving to `../../adr/0001-…/`.
- `git diff --check` and `git diff --cached --check`: clean, exit 0 (`diff-check.log`).
- Message strings verified against source: `pkg/metastore/maintenance.py:60`
  "maintenance database is not a primary", `:125` "maintenance database identity differs
  from the fence", `applications/lakectl/exclusion.py:148` "controller closed the
  connection without a reply", `applications/lakectl/server.py:52` `CONTROLLER_REFUSED`.
  Exit codes: `main.py:54,57` print canonical bytes (0); `:59–63` one fixed stderr line
  then `SystemExit(1)` for `ValueError`/`OSError`/`ExceptionGroup`/`PostgresError`/
  `HTTPError` (both `ConnectionError` and `PermissionError` are `OSError`);
  `cutover.error(...)` gives argparse's 2. The documented
  `--validate --config … --sequence N` invocation matches the parser's mutually exclusive
  action group.
- Numbering invariant: stated only in `P3_DESIGN.md:293–294` and
  `controlled-cutover.md:142`, identically, and consistent with `controller.py`
  (fresh state `generation=0`, `__init__`'s `_advance()` → 1, first `establish` → 2,
  `_advance` at every epoch end).
- Status rule: no document claims M1b implemented or verified; historical dated receipts
  keep their tense with superseding notes only. The operator document contains no
  milestone/plan-mechanics reference other than "No M1c activation is implemented here.",
  which is inside T6's literal text E.
- `grep -c "M1c item 1"` = 3 cross-references (`P3_DESIGN.md`, `P3_EXECUTION.md`,
  `P3_IMPLEMENTATION_PLAN.md` `### Resolution`) and exactly one
  `**Roadmap drift (2026-09-12):**` statement, in M1c item 1.
- No `src`/`tests` change: `source-inventory.sha256` (243 files) is identical to
  `m6-containers/source-inventory.sha256` (`source-inventory-diff.log`, diff exit 0), and
  `find src tests -newermt "2026-09-12 16:00"` was empty at verification time. M7's carried
  `unit.log/.exit`, `lint.log/.exit`, `duplication.log/.exit` and `coverage.json` are
  byte-identical to M6's; `collect.log` differs only in timing (1677 / 49 / 14 unchanged).
- `git status --porcelain` (`git-status.log`) = execution rule 7's user files + M1–M6's
  files + the eight documents (`design/core-map.html` as `A`) + `p3-evidence/m1b-authority/`.
  `design/index.html` (08:35), `design/roadmap.html` (12:45), `.opencode/*` (07:36) and
  `scripts/main.py` (08:47) all pre-date M7's edit window (16:25–16:30) and are untouched.
- M7 evidence completeness: `head.txt`, `git-status.log`, `coverage.json`,
  `source-inventory.sha256`, `collect.log`, and `unit`/`lint`/`duplication`/`docs`/
  `diff-check`/`grep-status`/`grep-banned-sense` each with a `.exit` (0/2/1/0/0/0/0). The
  §5 recipe pairs no `.exit` with `collect.log`.

## Residual risks

1. `design/core-map.html` has no baseline anywhere on disk, so "nothing outside the seven
   rows changed" rests on row-text equality plus pin alignment, not on a diff. Committing
   the file would remove this blind spot for later milestones.
2. "The controller mints generation 1 at every start" is strictly true only for a first
   start with no persisted state; after a restart the start advance is from the stored
   value. The sentence is T6's mandated literal wording (T5b ruling 2) and appears
   identically in both places, so it was not corrected here — a T5b/T3a wording follow-up,
   not an M7 defect.
3. `P3_EXECUTION.md:120` "## M1b implementation in progress" survives as a dated
   historical heading. The §2 status grep is case-sensitive and does not match it, and T6
   §1.4 lists only the `:28` row for that phrase, so this is by design.
4. M8 owes `P3_EXECUTION.md` one dated line under the new 2026-09-12 section (plan task
   M8.2). It was appended after this verification and is out of scope here.
