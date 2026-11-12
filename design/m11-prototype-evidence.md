# M11 prototype evidence: bounded results, not production qualification

Date: 2026-11-09. Status: **narrow preparatory evidence independently reviewed**.
The replacement [phase plan](../IMPLEMENTATION_PLAN_LATEST.md) carries the remaining gates.
The [architecture](m11-production-architecture.md) states the intended protocol; the
[review record](m11-review-evidence.md) retains discovery, initial dirt, and design history.
Original complete plan reviews remain **FAIL/FAIL/FAIL**. The later R3-1 reconciliation received
PASS in the one user-authorized independent maximum review, as recorded in
[plan §14](../IMPLEMENTATION_PLAN_LATEST.md#14-parent-acceptance-receipt-after-authorized-independent-review-2026-11-09).
That accepts the planning contract through prerequisite gates, not new experiments or product evidence.

## 1. Authority and review history

This durable record preserves the essential conclusions even if ignored scratch is lost.
It does not promote a probe into product code. This synthesis ran no probe or service.
Its dispatch is `f33fd29c-853a-4abd-8cb6-41d03ddacda7`, child
`ses_e416d6114ffeSnhTOmiw4wDVwF`, implementation/planning, attempt 1, configured maximum
Astra. The environment names `openai/gpt-6-astra`; provider effort was not measured.
The parent supplied the terminal review outcomes below. The writer also read the reports,
both attempt2 scripts, the review2 results, and the verification command log.

| Work | Child | Recorded result and limit |
| --- | --- | --- |
| Discovery | `ses_e41c0ac7fffenvXnJq83K0pRBh` | Maximum; seven correctness findings and operational drift confirmed statically. No product test run. |
| Architecture writer | `ses_e41a6e784ffeeewx93Xn6wbl72` | Maximum planning; proposal, not acceptance. |
| Architecture review 1 | `ses_e41912c8effefzK43sk1bh9L4w` | Preparatory FAIL: destructive database helper and missing mkdir/rmdir parent-sync ordering. |
| Architecture fix | `ses_e418f28b5ffe4YOAVFr7gf3YAW` | Preparatory planning; preserve failed databases, add containing-directory sync and retry rules. |
| Architecture review 2 | `ses_e418d3df1ffemcl49SpFu2Fxh7` | Preparatory PASS for bounded architecture/prototype handoff, not complete design validation. |
| Prototype attempt 1 | `ses_e418afe08ffeZsw6A4Sev8ItbX` | Maximum prototype; BLOCKED at endpoint setup, before any behavior probe. |
| Prototype attempt 2 | `ses_e417b817dffeIue88PU914fPDa` | Preparatory prototype; selected counterexamples and tiny model ran. |
| Prototype review 1 | `ses_e417596feffe0nPZoj4GhNFbVj` | Preparatory; independent rerun exit 0, but FAIL: allocation manifest file was synced without both containing-directory syncs. |
| Prototype fix | `ses_e4172c685ffe81WFgbWSbBeALc` | Preparatory prototype; both syncs, two allocation fault checks, and run-specific verifier selection. |
| Prototype review 2 | `ses_e41701208ffeePja0AkjkcfOrw` | Preparatory terminal PASS for narrow evidence. Full probe `review2` and run-specific stop verifier exited 0. |
| Replacement-plan review1 | `ses_e414a07b4ffeiXZm8gPW2sUSqu` | Maximum FAIL: P07 gate/caller transition and missing durable CLI instance/principal binding. |
| Replacement-plan fix1 | `ses_e413f9417ffeT4PMGHHwxXjNpM` | Preparatory planning only; writer-fixed proposal awaiting maximum review2. No additional probe evidence. |
| Replacement-plan review2 | `ses_e41375e91ffeReJef3Uy9rhbnM` | Maximum terminal FAIL: credentials could leave before destination approval; context command registry/panel ownership missing. Review1 P07 and instance binding resolved. |
| Replacement-plan fix2 | `ses_e412f6ce4ffer6joD6no6pwOVR` | Preparatory Low planning; both findings writer-fixed pending final maximum review3. No new experiment or product evidence. |
| Replacement-plan review3 | `ses_e412ba125ffeV3Y9o1hLnuYhTi` | Maximum terminal FAIL: R3-1, external development credential producer/caller cutover has no owner. Earlier P07, binding, local trust and context registry corrections confirmed. Original cycle exhausted; phase-plan §12 retained. |
| R3-1 substantive reconciliation writer | `ses_e410c833fffesQVUD7YKqcsdDO` | Implementation/planning attempt1, configured maximum, dispatch 74172ff5-25cb-4bbc-b53a-e76fab96563e. Replaces the proposed shell producer with shared fresh-login/approval/atomic-state adapter and assigns callers/gates in prose only. No probe or independent verdict. |

All subjects were serial, under conservative `*:write` coordination. Claims do not grant
edit or cleanup rights. Historical v1 records with no profile remain **not-recorded**;
neither prose nor a later maximum dispatch supplies missing historical provenance.

## 2. Reproduction record and infrastructure failure

All historical commands below used cwd `/home/karl/repo/huron-tusd`. They are receipts,
**not instructions to restart retained resources now**. A new run needs parent admission,
fresh output names, verified ownership, and an explicit resource/cleanup assignment.

Attempt1's exact setup entry point:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/resources.py setup
```

It exited **1**. Docker 27.2.1 created the private internal network, volume, and cached
PostgreSQL container, but did not publish the requested ephemeral loopback port:

```text
HostConfig.PortBindings = {"5432/tcp":[{"HostIp":"127.0.0.1","HostPort":""}]}
NetworkSettings.Ports = {}
docker port huron-m11-production-a1 5432/tcp
  exit 1: No public port '5432/tcp' published for huron-m11-production-a1
```

Read-only diagnosis found PostgreSQL 16.14 accepting connections, all three durability
settings on, default databases only, and no other client backends. No migration or behavior
probe ran. The unfinished attempt1 `probe.py` refuses suites; its four advertised suite
commands in the earlier specification are not executed evidence. Four `blocked_evidence.py`
runs (no suffix, `finalcheck`, `handoff`, `final`) exited 0 **as diagnostics of the blocker**.

The parent then authorized access to the **same** owned container's private bridge address.
No network was changed, no second server was created, and setup was not replayed.
Attempt2's first invocation failed on a missing test-helper import path before run allocation.
The ignored script was fixed; the same `run1` command then exited 0. Review1 also ran to
exit 0 but correctly rejected the resource-manifest durability claim. That failure remains.

The corrected independent review2 commands were:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/attempt2/probe.py review2
HURON_PROBE_RUN=review2 PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/attempt2/verify.py review2final --stop
```

Both exited **0**. `HURON_PROBE_RUN=review2` is essential: the original verifier default
selected `run1`, not whichever run happened last. Existing run directories and database names
are collisions, not reusable inputs. There is no database drop in the corrected probe.

Recorded bounds: runner alarm 900 s; PG connection 3 s, command 5 s; Docker commands 15 s
in the probe and 30 s in verification; process barriers/join 5 s; preflight at least 8 GiB
free and 1,000 free inodes. Only a few small files were generated, below the 2 GiB allocation
cap. Successful invocations completed within the terminal's 60 s bound. No workload-size
qualification, download, install, or product gate ran.

## 3. Observed current behavior

| Observation | Actual exercised boundary | Exact decisive result | Not proved |
| --- | --- | --- | --- |
| Same-size foreign replay | Actual `Placer` and `PosixStorage`, using the existing `prepared` fixture | Missing source gives `measure(...) is None`; `measure_destination` accepts unrelated X bytes of the declared size. SHA-256 `5b09369749b5240d619e70883c4c89030708917c1b2f5f81e2dc1094c451fff9`. Different-size control refuses. | No hook receipt or real PG commit was invoked. |
| Backup removed before acceptance | Actual POSIX `Placer.link` and `drop_backup` | X bytes are replaced by DATA; backup first contains X, then is absent. DATA stays public with no collection acceptance call. | Not a full application PG reproduction of committed A, stale B rejection, or revocation. |
| Local lost intent | Actual `StateDir`, two processes | Parent holds `locked('c')`; child uses public read/write methods without it. Parent adds `parent`; final removes are `['initial', 'child']`. Child exit 0. | Not two complete CLI commands, fixed-temp collision, or process-crash recovery. |
| Removal-only false success | Actual CLI private helper `_recover`, remote API answers faked at the network boundary | Base 1, remote version 2, removal still listed: returns `{'version': 2, 'file_count': 1}`. Version 1 control raises the original error. | No real lost request, full push, or subsequent stage-clear was executed. |

These results support the inspected mechanisms in F1/F3/F5/F7. They do not turn all seven
findings into executed end-to-end reproductions. F2/F4/F6 still have static evidence and
required adversarial application tests in the plan. No containment escape was found or claimed.

## 4. Tiny candidate PG/filesystem result

The candidate creates **its own** logged tables, not Huron tables: `operation`, `collection`,
and `audit`. It uses real asyncpg sessions, a collection row lock, UUID request primary key,
pending foreign key, and unique audit key. Its payload digest is the literal `digest`, not
the proposed canonicalizer. It handles one synthetic collection and one actor.

Two sessions submitted the same UUID/digest concurrently: one durable accepted operation.
A different digest returned `identity-conflict`; a distinct request while pending returned
`busy`. Public A remained A at acceptance. Each row below reconnected to PostgreSQL, loaded
persisted state, and called materialization again:

| Boundary | First result | After reconnect and repeat |
| --- | --- | --- |
| `mkdir-before-sync` | `interrupted` | succeeded once |
| `mkdir-sync-error` | `sync-blocked`; no acknowledgment | succeeded once |
| `mkdir-after-sync` | `interrupted` | succeeded once |
| `replace-before-sync` | `interrupted` | succeeded once |
| `before-finalize` | `interrupted` | succeeded once |
| `after-finalize` | `succeeded` | same success, no new audit/version |

For each completed case: public B, retained old A, sentinel `untouched`, version 2, pending
cleared, and exactly one audit row. An extra operation (UUID integer 999) replaced the target
with a **foreign inode holding the same B bytes**: `identity-blocked`, pending retained, no
success audit. This was intentional retained evidence, not a live task.

The final independent SQL observation was:

```text
select * from collection;
1|2|00000000-0000-0000-0000-0000000003e7|new
select count(*) from audit;
6
select state,count(*) from operation group by state;
succeeded|6
accepted|1
```

The eligibility experiment was **only a pure predicate**:

```python
def finish(state, now, expiry):
    return 'ready' if state == 'sealing' and now < expiry else state
```

It kept `superseded` and `consumed` terminal, refused ready at exact expiry, and allowed ready
one tick earlier. It did not release a delayed hook, call actual upload adapters, or test tusd.

### Resource-manifest correction

The corrected ignored prototype performs this allocation ordering before CREATE DATABASE:

```python
def prepare_run(root, manifest):
    root.mkdir()
    syncdir(root.parent)
    save(root / 'manifest.json', manifest)

def save(path, data):
    with path.open('x') as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    syncdir(path.parent)
```

Each of the first and second directory fsyncs was independently forced to raise `OSError`.
The error propagated. Real PG catalog queries before and after proved that neither
`huron_m11_attempt2_review2_syncfault1` nor `huron_m11_attempt2_review2_syncfault2` existed.
The failed directories/manifests were retained. This tests allocation ordering and error
propagation, not persistence after power failure. The excerpt is evidence, not a product helper.

### Limits that block broader claims

No worker was killed in the candidate. The six cases are **logical interruption/reconnect**,
not process death, database restart, kernel crash, power loss, or an actual lost HTTP answer.
The candidate trusts its fresh private directory namespace. It does not persist directory
identity or reject adversarial replacement of that directory. Retained hard links make its
inode comparison useful locally; inode numbers alone are not durable object identities.

Not tested: two-file overwrite/remove, directory-to-file changes, private copy/seal manifests,
rmdir retry, actor scope, canonical digest, saved semantic rejection, real application adapters,
quota/reference conservation, cleanup, full CLI locking/spooling, runtime drain/readiness,
duplicate independent API runtimes, writable-FD behavior of tusd, cancellation during PATCH,
NFS/ONTAP behavior, fencing, throughput, or 50-user capacity. The plan treats these as
prerequisite validation or mandatory pre-release acceptance, not optional later hardening.
The plan-review correction adds explicit instance/principal/endpoint binding experiments to P03
and real application tests to P29. The tiny one-actor candidate did not test such binding, endpoint
replacement, logout/login recovery, TLS policy or the P07 test-composition transition. None of the
earlier narrow PASS results qualifies these newly specified contracts.
Review2 further requires local destination approval and stored issuer/client/API credential
provenance BEFORE identity, refresh or exchange. Valid/expiring credentials, first login, ordinary
API calls, provider discovery changes and aborted endpoint acceptance remain untested here.
P03/P23/P25/P27b/P29 own that evidence; the existing probe cannot establish non-disclosure.
R3-1 adds no observation to those results. The proposed repository helper, explicit approval-file
and stdin-password interface, shared FreshLogin/credential writer, full CLI subprocess identity
switches and failed/interrupted save preservation have **not** been exercised. Neither full e2e,
cached NOAA_RAW offline idempotent rerun nor separately approved host/pod deployment authentication
ran here. P23/P27b/P29/P33/P34 must supply their specified public/real-adapter evidence. Seven hashes
below and all six logical reconnect observations are unchanged; none establishes process-crash,
tusd, NFS/ONTAP, quotas or workload proof. The user's one later independent maximum review exception
is review admission after substantive planning, not evidence that any of these tests passed.

## 5. Retained artifacts, hashes, and ownership

Scratch base: `roadmap/prototypes/m11-production/__pycache__/`. Concrete children matched
`.gitignore:2:__pycache__/`; no `roadmap/` file was tracked. Hashes below are SHA-256,
captured by this planning writer with `sha256sum` (exit 0), relative to that base:

| Artifact | SHA-256 |
| --- | --- |
| `REPORT.md` | `1bd3190ca9a0984940a56ce0d68421bebc1df9f0854a5a85c0e0c6b9225495f2` |
| `resource-events.jsonl` | `e14ffa5b450c0fe6fcde872c9b74c4da7259c078cda5004feebffeba9a400942` |
| `attempt2/REPORT.md` | `85c08bd45b251eea800fc0157b3be7c6593bf1be2fe565131046333017075a0a` |
| `attempt2/probe.py` | `b20a06a8eac84db443843713c362772d532f6eb3837e8e7ed8b17e87ef6b579b` |
| `attempt2/verify.py` | `ca8377241ce6dea98f9884a7f2db2ddadaad8382e339a517f3744068a29ca741` |
| `attempt2/review2/results.json` | `69063b017b211263f0bbd3d959989ecfd3320c98baacddb074f5279d2f21af42` |
| `attempt2/review2final.json` | `1e38d9b688c3163ddfb6e56e234b40ed237d92c8e7d232c15ab3e734b759eb7f` |

`review2final.json` retains exact commands, exit status, stdout, and stderr, including normal
stop after a zero-client check. All database/inspection commands exited 0. Root whitespace
check exited 2 only for pre-existing `web/src/lib/api/openapi.ts:170`; cached check exited 0.
Owned scratch text checks returned 1 for a difference from `/dev/null`, with no whitespace
diagnostics. The verifier checked the selected runner PID 2325046 and child PID 2325110 absent.

| Resource | Last independently recorded state |
| --- | --- |
| Container | `huron-m11-production-a1`, ID `ca0aac2e123e4f18dea1ece653ca62f4c6555a46059a46271cd9ca63ec206936`, stopped, PID 0, exit 0 at `2026-11-09T04:28:43.057783209Z` |
| Image | `sha256:88a36c64c1003dad93f56daa12d1f8916ec66d1fa3e5fb1fb0ae7cb77efd56d1` |
| Network | `huron-m11-production-a1-net`, ID `8539e2f1e3755d5d92c9ac4fb168ee68c247c92b33e1a32b023bd205ff847ec3`, internal, retained |
| Volume | `huron-m11-production-a1-pg`, retained |
| Label | All three: `huron.probe=m11-production-a1` |
| Databases | `huron_m11_attempt2_run1`, `huron_m11_attempt2_review1`, `huron_m11_attempt2_fix3`, `huron_m11_attempt2_review2`, plus the three defaults; retained |
| Probe processes | None remaining in the review2 receipt; this prose writer started none |

The parent owns eventual cleanup. **No deletion is authorized by this document.** Do not run
the unfinished attempt1 cleanup scaffold, force-drop databases, prune Docker, restart on the
strength of a name, or discard a failed run. Reconcile IDs, processes, connections, and ownership
before any separately authorized action.

Preserved baseline: HEAD `0dcdf1ff6a8689f704a73a0758a886c18b5d3584`, branch
`tusd-integration`, reference branch `m11.5-escalated`; old-plan Git blob
`862e1bafc54c5ca88b0351ff7ee723662a1ac7f8`, 0003 blob
`83757f7e73640356639ae07c45d7885660b9a6e3`. The complete initial status is in the
review record. No historical green count qualifies the current dirty application.

## 6. Decision

Retain the focused direction: private copy-and-seal, explicit request/object identity,
acceptance before public effects, recoverable roll-forward, retained old/new bytes, and one
fenced writer. The probe supports these choices without proving their full implementation.
The next plan may be executable **through prerequisite gates**, not declared fully ready.
Design validated, plan ready, implementation complete, and production qualified are four
different states. Only the last requires complete maximum-profile independent qualification
on representative infrastructure, including the external ONTAP and workload evidence.
