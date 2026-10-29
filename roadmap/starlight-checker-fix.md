# Starlight checker fix — attempts 1–3

Status: READY FOR INDEPENDENT REVIEW — attempt 3 completed all 63 CLI cases and
the applicable self-check gate; independent review remains pending.

## Scope and baseline

Attempt 1: exclusive fix/code dispatch `6744a321-fc77-4a8f-b39b-39b08c65246e`, child
`ses_ef199df8dffep8HKccQrm7gNAK`; configured maximum Astra (`openai/gpt-6-astra`,
effort `max`). Provider effort acceptance is not proven by this receipt.

Attempts 1–2 owned only [checker](check_docs.py), [CLI regressions](checks/test_check_docs.py)
and this receipt. The [canonical template](../.agents/templates/phase-plan.md),
all real plans, source and pre-existing user work remain read-only. No restart,
services, delegation, staging, commits or journal maintenance are needed/permitted.

Review 1 `ses_ef5b92a68ffe9m84aKRmItnEmZ` and fresh baseline
`ses_ef19bfcf7ffeAak3AnMfCjbIK8` supplied F1: canonical
`## Per-subject serial task slices` is rejected while historical
`## Serial task slices` passes. This known baseline BLOCKED is the assigned
remediation, not missing infrastructure. No other Starlight design findings
were supplied. Legacy acceptance is explicitly limited to historical local plans.

Attempt 1 recorded reading the required contracts/skills, template/checker/001
and source docs receipt, finding no dedicated checker tests in `tests/`,
`.agents/tests/` or roadmap Python files. The existing 11-positive/9-negative public CLI reproduction
in [the execution receipt](execution-2026-10-05.md) supplies the fixture pattern and
retained lifecycle cases. Application pytest fixtures serve FastAPI/stores, not
this standalone CLI; no pytest discovery or application suites are applicable.

## Initial preservation evidence

Before edits: HEAD `2b2e9c0c9d6b9beafef2e11b840f28535502aa6b`; 51 tracked dirty
paths and four untracked files. No tracked roadmap paths. All remain user-owned.
Python 3.14.0; uv 0.12.19 (x86_64-unknown-linux-gnu).

Attempt 1 before-values (source, 13 real plans, index and status match attempt 2):

- 553 Git-visible paths, including missing tracked paths:
  `2cc49e575ed7f99bf9db20868abf40ac37911b0379146a00d298a1a26c137ed8`
- 13 real plans:
  `671e96125a3488ed90fea44cfd18858d02ffa8598aedf38ae8c49b47a05305b5`
- Raw index:
  `a966503715762ae180e3a8b1d9634fd1f9fd0e8a6f945d4bffc75aed062dc706`
- `git --no-optional-locks status --porcelain=v1 -uall` output:
  `f3f774478e5a4680e68c74f89586a8143822230116c2dc6e877f838ea4c35cf0`
- Real 001 contents:
  `f6b1ee6497b10803166c54a11ebe1d269614a746df8be6e17009e617474b21c7`
- Canonical template contents:
  `b9e5eff86068c529907a1b72c8aa6d181033ed012761e8e652d3b59661a59330`
- Checker before fix:
  `cff54b28220e05bcbc8054563b3ea222538bd28dc21bd8c7529f663231b931c7`

The harness uses ordered relative path + NUL + content SHA-256 (or `missing`) +
NUL for aggregate hashes. It compares HEAD, source, plans, status and index before
and after every run; its unique ignored fixture is removed in `finally` only.

## Results and handoff

### Recovery attempt 2 — 2026-10-06

Dispatch `b447a17b-5c98-4f7d-b232-f3cef1ee6509`, child
`ses_ef17b6306ffeUaHrfMLZu332oJ`: fix/code, exclusive `*:write`, recorded maximum;
configured Astra `openai/gpt-6-astra`, effort `max`, provider acceptance not-proven.
This is a newly authorized bounded attempt, not a replay or resume of attempt 1.
Per parent handoff, attempt 1 ended with terminal APIError and no final report;
its last test tool lasted 120 seconds. No completed regression is inferred from it.

Inspected and retained the inherited checker and harness **without edits**. The
checker counts exactly one canonical or explicitly permitted legacy full heading
outside backtick/tilde fences. The harness defines 43 heading/fence cases plus
the retained 20 lifecycle/other validation cases: 19 accepting and 44 rejecting.
Other section, status, link, skill and gate-marker checks are unchanged. No code
defect was identified by inspection; this is not complete acceptance evidence.

Contrary to the supplied absent-fixture inventory, a directory read found
`roadmap/plans/check-docs-kvh8xxjk.md` and this existing attempt-1 receipt.
The fixture matches the harness's `invalid lifecycle 'ready/blocked'` case
byte-for-byte; its sole difference from real 001 is that invalid status line.
`pgrep -af '[t]est_check_docs.py|[r]oadmap/check_docs.py'` exited 1, no matches.
The pre-existing fixture is outside this attempt's three named edit paths and
was left intact; no automatic cleanup, rollback or journal changes were made.

All commands below ran from `/home/karl/repo/huron`:

| Command | Exit / outcome |
| --- | --- |
| `python roadmap/checks/test_check_docs.py` (tool timeout 300000 ms) | 1: baseline rejects the pre-existing fixture; **0 of 63 cases executed**, no new fixture created. Preservation assertions succeeded. |
| `python roadmap/check_docs.py` | 1: only `check-docs-kvh8xxjk.md: expected one explicit lifecycle Status: draft/blocked/ready/implementing/verified`. |
| `git diff --check` | 0, no diagnostics. |
| `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` | 0: strict Zensical build, `No issues found`, 0.22 s. |
| `git check-ignore -v roadmap/check_docs.py roadmap/checks/test_check_docs.py roadmap/starlight-checker-fix.md` | 0: all three ignored by `.gitignore:40:/roadmap/`. |
| `git ls-files roadmap` | 0, empty. |
| `git diff --cached --exit-code` | 0, index remains clean. |
| `git diff --no-index -- roadmap/plans/001-decisions-prototypes.md roadmap/plans/check-docs-kvh8xxjk.md` | 1, exactly the status-line difference described above. |

Versions: Python CLI 3.14.0; docs interpreter 3.12.4; uv 0.12.19;
Zensical 0.0.57; Git 2.43.0; GNU Make 4.3. Product Python, frontend and agent npm
gates do not apply to this ignored checker-only boundary; no thresholds changed.

Before/after validation: HEAD, all 553 Git-visible paths, 51 tracked changes,
four untracked files and raw index match the hashes above. The 13 real-plan hash
also matches attempt 1. Including the untouched leftover, all 14 plan-directory
Markdown files hash to
`6f9ef442d86757fd9693766879260eb1edc407ff5cf604a0bcddff7e2cafe7f1`.
The harness's label “14 real plans” includes that fixture; it is not a new real plan.
Attempt 2 changed only this receipt. Ignored-text checks:

```sh
git diff --no-index --check /dev/null roadmap/check_docs.py
git diff --no-index --check /dev/null roadmap/checks/test_check_docs.py
git diff --no-index --check /dev/null roadmap/starlight-checker-fix.md
```

Each exited 1 (new content differs from `/dev/null`), with empty stdout/stderr:
zero whitespace diagnostics. Adding `--no-exit-code` yielded the same result.
An initial auxiliary Python command wrapper had a quoting SyntaxError before
invoking Git; direct reruns and a corrected wrapper produced these results.
Manual receipt-link review found four existing local targets, no fragments.

**Next action:** parent must reconcile and explicitly authorize cleanup of the
exact leftover fixture, then dispatch the full regression with at least a
300000 ms timeout. Do not weaken lifecycle validation or filter the fixture out
of the checker. Independent review 2 of the combined Starlight design/checker
must follow a successful writer terminally. This is BLOCKED, not READY FOR REVIEW,
independent PASS, site migration or MVP completion.

### Narrow expectation correction, attempt 3 — 2026-10-06

Dispatch `59d08e16-8f37-425a-8e3c-93e68f411ac2`, child
`ses_ef171179affeMuxdERKAWkRZX6`: fix/code, exclusive `*:write`, recorded maximum;
configured Astra `openai/gpt-6-astra`, effort `max`, provider acceptance not-proven.
Only the CLI harness and this receipt changed. The inherited F1 checker remained
byte-identical; no additional checker defect or out-of-scope blocker was found.

Parent reconciliation moved the interrupted worker's exact fixture to
`roadmap/checks/recovery/check-docs-kvh8xxjk.fixture`, preserving SHA-256
`39b944d904a1a544afb5e8f8ecdd10eacd46e44ee7b22f52ca6f1946ee9a827e`.
This attempt did not move, edit or delete it or its recovery README. The initial
13-plan/source/index/status hashes matched the recorded legitimate baseline above;
no unknown changes were rebaselined. The real-tree checker initially exited 0.

The parent's preceding 300000 ms-timeout run exposed a harness expectation bug:
the empty lifecycle case deliberately writes literal `Status: `, so its exact
stdout must contain a trailing-whitespace diagnostic before the lifecycle error.
The harness now derives the status line number from the source match and expects
both diagnostics only for that existing case. It keeps the literal input, exact
exit/stdout/stderr equality, all other expectations and `finally` cleanup intact.
No whitespace/status rule, skip, threshold or assertion was weakened.

An in-memory comparison reconstructed the original harness, verified its recorded
SHA-256 `c0fda49b5693f41c958dac93c45a0ce82feeae2e91cdf17a753df9b0d25e2b12`,
and proved all 63 case names and inputs identical, with exactly one expectation
changed. A source shifted by two blank lines correctly changed the expected
whitespace line from 3 to 5. This auxiliary assertion command exited 0.

All gate commands ran from `/home/karl/repo/huron`:

| Command | Exit / outcome |
| --- | --- |
| `python roadmap/checks/test_check_docs.py` (wrapped with shell `time`; tool timeout 300000 ms) | 0: **19 accepted + 44 rejected = 63 CLI cases**; baseline exit 0; 135.875 s real. |
| `python roadmap/check_docs.py` | 0: documentation links/fragments, ignored-plan dependency prohibition, whitespace, cross-references/skills and phase structures passed. |
| `git diff --check` | 0, no diagnostics. |
| `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` | 0: strict Zensical build, `No issues found`, 0.37 s. |
| `git check-ignore -v roadmap/check_docs.py roadmap/checks/test_check_docs.py roadmap/starlight-checker-fix.md` | 0: all three ignored by `.gitignore:40:/roadmap/`. |
| `git ls-files roadmap` | 0, empty. |
| `git diff --cached --exit-code` | 0, no staged changes. |

The full run executed all 43 heading/fence cases and all 20 retained lifecycle/
other-validation cases. Its unique temporary fixture was removed, and its final
preservation assertions passed for HEAD, all 553 Git-visible paths, 13 real plans,
raw index and dirty inventory (51 tracked changes, four untracked files), matching
the hashes above. Checker SHA-256 remained
`e74d7708b2d5468c48a76829d4fb066d87a4814fc5707d1abbeb9ef873f8a77e`.

Final auxiliary Python assertions exited 0: all three checker/harness/receipt
files are whitespace-clean, all four receipt link targets exist, and source,
plans, HEAD, raw index, dirty inventory, canonical template, checker, quarantine
fixture and recovery README still match the pre-edit preservation values.

Python CLI 3.14.0, uv 0.12.19 and Git 2.43.0 were reconfirmed. No application
Python, frontend or agent npm gate applies to this ignored checker/harness-only
boundary. No service, configuration, real-plan, source, index, global asset or
quarantine mutation was authorized or performed. No restart is needed.

**Handoff:** READY FOR INDEPENDENT REVIEW, not independent PASS. Parent should
terminally sequence the assigned fresh review after this fix; earlier interrupted
or blocked attempts remain historical non-PASS results, not completed regression
evidence. This receipt does not qualify Starlight migration or MVP completion.
