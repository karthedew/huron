# M8 verification — attempt 2

Date: 2026-09-12. HEAD `e22d0003cfd97f0f75df01c04b3c493bef5eeaf8`, branch
`p3/integrity-and-raw-flows`. Scope: the fix pass applied after attempt 1's FAIL, which
changed only `p3-evidence/m1b-authority/m8-final/report.md`.

## Verdict: PASS

## Tree unchanged since attempt 1 — no full gate rerun

- `source-inventory.sha256` (243 files under `src/huron` and `tests`) is byte-identical to
  the implementation's `m8-final/source-inventory.sha256` (`source-inventory-diff.log`).
- `git status --porcelain` is byte-identical to both `m8-final/git-status.log` and
  `m8-final/verification1/git-status.log`.
- `git log -1` is still `e22d000`; `git diff -- pyproject.toml` is the single
  `fail_under = 95.88` -> `95.92` line (`pyproject-diff.log`).
- `find . -newer m8-final/verification1/collect.log` outside `p3-evidence` returns only
  docs-build cache files this run produced. Inside `p3-evidence`, only
  `m8-final/report.md` and the new `m7-docs/verification1/` changed.

Attempt 1's full-gate receipts in `m8-final/verification1/` therefore stand.

## Cheap checks rerun

| Check | Exit | Result |
| --- | --- | --- |
| `make docs` | 0 | `zensical build --strict`: "No issues found" |
| `git diff --check` | 0 | empty |
| `uv run pydoclint src` | 0 | silent |
| `--co` unit / contract / integration | — | 1677; 49/1741 (1692 deselected); 14/1741 (1727 deselected) — equal to attempt 1 |

## The three attempt-1 defects

1. §1 (M7 receipts): fixed. §1 now states the ordering explicitly and lists the fourteen
   files in `m7-docs/verification1/`; that directory exists on disk with `docs.exit` 0,
   `grep-status.exit` 0, `grep-banned-sense.exit` 0, `diff-check.exit` 0, a
   `source-inventory-diff.log` showing identity with M6 (243 files), and a dated
   `report.md` whose verdict line is `## Verdict: PASS`. All of M0–M8 have a
   `verification1/` directory.
2. §9 (pydoclint deviation): fixed and matches the code. All seven `ports.py` stubs are
   `...`-bodied at lines 109/127/139/154/172/182/193 (`ports-stubs.log`) with prose raise
   descriptions and no `Raises:` section; `pyproject.toml:125` is
   `skip-checking-raises = false`; `maintenance.py` lines 54/73/101 are the `Raises:`
   sections of the concrete `PostgresRoleExclusion` (class at `:37`), each with a real
   `raise ValueError` in the body; `uv run pydoclint src` exits 0 silently. The T4 §5
   second-bullet cross-reference matches `P3_M1B_AUTHORITY_DESIGN.md:2662-2665`.
3. §3 (coverage transcription): fixed. Every row equals its milestone's
   `coverage.json` `percent_covered` to five decimals (`coverage-percentages.log`),
   including M1 = 95.8990075890251 -> 95.89901%.

## Remainder of the report re-checked

§2 summary lines, §4 duplication numbers, §5 acceptance and fixture cleanup, §6
environment gap, §7 repro node ids, §8 T4 decision, §10 file list and the closing
statement all match their evidence files. §10's block equals `git-status.log` minus
rule 7's untouched user files exactly (33 lines, no additions or omissions).
