# Canonical-skill launch contract correction

## Final source qualification and checkpoint

Maximum reviewer `ses_ef39a4415ffeYxgbAgyAK8cuxX` returned PASS on checkpoint
review 3/3 for exact tree `028edc75f61292d3887be71f59f95f7e37625b40`, fresh export
`/tmp/opencode/huron-checkpoint-JC6FJT6r`. Independent full gates passed: 86 tests,
20 focused launcher regressions, canonical assets/typecheck, three first-attempt
flagged inventory processes, safe resolved checks and strict docs. No open source
finding. Source/indexed content and unrelated work preserved; raw index metadata
refresh during cross-worktree diff was diagnosed separately, not claimed unchanged.

Parent committed exactly that tree locally as
`2b2e9c0c9d6b9beafef2e11b840f28535502aa6b`. No push or hook bypass.
Serving-runtime activation is still pending quit/restart through the project
launcher. Earlier self-check/reconciliation blockers below describe prior steps.

## Parent reconciliation after worker terminal

The inventory contract is 11 canonical project skills, not 11 total entries; the
allowed built-in `customize-opencode` is distinct. The worker's failed cardinality
assertion remains historical evidence, not a successful run or a canonical-path failure.

After terminal handoff, the parent ran one corrected fixed three-process sequence
through `sh .agents/scripts/opencode-project.sh debug skill --print-logs`. Every
process exited 0; each of the 11 project names appeared once at its exact canonical
path, one allowed built-in was present, no unexpected entry or duplicate-name
warning appeared. Raw outputs were captured privately and removed only from the
invocation's own scratch directory. No retry-until-green or live assertion change.

Parent inspected the four live-file changes and staged only those additions/updates
on top of the previously audited checkpoint. New tree:
`028edc75f61292d3887be71f59f95f7e37625b40`. Staged whitespace is clean; the same 51
unrelated tracked changes remain unstaged. This resolves the supplemental harness
blocker and permits independent checkpoint review 3. Serving-runtime activation
still requires quitting and restarting through the launcher; no active fix claim.

## Assignment and status

- Dispatch: `7c5bfa7b-91a9-42ec-8a96-4ba6257f5319`.
- Worker: `ses_ef3aee631ffeeUZPnYb0UOks9N`; parent: `ses_ef6299af8ffeNvyg5Eot7KoxyA`.
- Role/activity/attempt: fix / code / 1, after staged-checkpoint review 2.
- Recorded profile: maximum; fixed configured selection is
  `markdown-implementer-max`, `openai/gpt-6-astra`, effort `max`.
  Provider effort acceptance is **not proven** by a prompt or model identity.
- Exclusive cooperative claim: `*:write`, including shared tooling/docs outputs.
- Started: 2026-10-05 13:46:43 UTC. Required contracts and canonical local
  implement-markdown / implementation-plan skills read; built-in
  customize-opencode loaded. No nested agents, staging, commits, branches,
  resets, cleaning, stashing, permission changes or live service operations.
- Current state: **inventory validation blocked on parent reconciliation**.
  All other assigned self-checks are green. This is not independent review.
  The first inventory harness incorrectly asserted 11 total entries rather
  than 11 canonical project entries plus the allowed built-in. Its failure is
  retained below; no replacement inventory process has been launched.
- Independent checkpoint review 3 must use a new staged export and independently
  rerun the complete gate after this worker is terminal. Only the parent may stage.

## Baseline and root cause

Supplied baseline: live Max-profile qualification passed 66 tests, eight resolved
probes, strict docs and full applicable tooling gates. Checkpoint review 2's first
safe resolved check exited 1 for a noncanonical `prototype`; an unchanged second
run exited 0. No other finding was reported. Those unchanged successes did not
disprove the collision race.

Reused completed discovery `ses_ef54d50ffffezcQ6dgASvNLs89`, not a new toolchain
investigation: installed OpenCode 1.18.34 parses all discovered skill files with
unbounded concurrency and assigns its name map after awaiting Markdown parsing.
The home `.agents` prototype, the home `.claude` symlink to that file, and the
project's canonical prototype share one name. Name-based permissions do not
enforce canonical path selection. The supported `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`
skips automatic external home/project scans while leaving explicit `skills.paths`
outside that branch. A Claude-only flag does not exclude the home `.agents` copy.

Sources consulted during this fix:

- Official CLI documentation: <https://opencode.ai/docs/cli/> (serving versus
  attaching, CLI/debug/version commands). Its displayed environment-variable
  table is not treated as complete evidence of the installed flag's behavior.
- Official schema: <https://opencode.ai/config.json>; `skills` has `paths` and
  `urls`, with no project-level external-discovery disable field.
- Built-in customize-opencode guidance and the supplied installed-loader discovery.
- Installed binary identity independently matched:
  `9ca0b9953d49997601655e54f846a3efa464f237e47c6f1b04716d0f2e64c4c2`.

This is a supported launch contract, not an upstream loader patch. It does not
mutate `process.env` in a config hook, rename skills, edit home assets, change
models/permissions, add unsupported schema fields, or silently inject the flag
only into a checker. Normal OpenCode skill directories and additional configured
paths remain possible sources of collisions; this fix addresses the present
external home-skill collision, not universal duplicate resolution.

## Exact ownership and implementation

Only four live files changed:

1. New `.agents/scripts/opencode-project.sh`: POSIX `sh`, `set -eu`, exports the
   required flag as `1`, and `exec opencode "$@"`. Invoked from the repository
   root with `sh .agents/scripts/opencode-project.sh`; no chmod was performed.
2. `.agents/README.md`: actual startup requirement, serving-process environment,
   quiesce/quit/restart instructions, attach limitation, safe checker invocation,
   and honest remaining collision boundary.
3. `.agents/scripts/check-resolved.mjs`: only an eight-line preflight guard was
   inserted, before diagnostics directory creation and before any CLI subprocess.
   Every existing canonical/model/profile/permission assertion remains intact.
4. New `.agents/tests/launcher.test.js`: isolated temporary worktrees and a
   controlled-PATH executable stub, reusing the existing Node/subprocess fixture
   pattern and shared canonical inventory/workflow constants.

The optional `.agents/tests/assets.test.js` and `.agents/scripts/check-assets.mjs`
were not edited. No dependencies, lockfiles, plugin/journal code, global assets,
binary, config schemas, skill names, application code or historical assertions
were changed. No obsolete paths/tests were removed. No backward-compatibility
shim was introduced. The only owned local receipt is this ignored file.

Regression evidence (20 new tests, including subtests):

- Launcher overrides unset, empty, `0`, `false`, `true` and `1` to the exact `1`.
- Arguments retain empty values, spaces, quotes, shell metacharacters, substitutions
  as literal text, glob characters, embedded newline, `--` and leading hyphens.
- Exit statuses 0 and 23 are preserved; a self-terminating stub exposes SIGTERM
  rather than an intermediate shell exit status. No test starts an OpenCode server.
- Checker rejects unset, empty, `0`, `false`, `true`, and `01` with exit 1 and an
  actionable launch message, without invoking the stub or creating diagnostics.
- Explicit `1` reaches all preserved checks on a valid simulated inventory;
  wrong default primary, downgraded maximum, and noncanonical prototype still fail.
- Existing 66 tests, including permission/profile/history behavior, all remain green.

## Commands and outcomes

Root cwd is `/home/karl/repo/huron`; tooling cwd is `/home/karl/repo/huron/.agents`.
All commands below completed unless explicitly marked blocked. Terminal outputs
contain only test data or safe summaries; raw provider configuration is not copied
into this receipt. Resolved-check private diagnostics and owned inventory scratch
were removed by their own invocation cleanup, not by cleaning unknown files.

| Cwd | Exact command | Exit / result |
| --- | --- | --- |
| root | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --version` | 0; v22.23.2 |
| root | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm --version` | 0; 10.9.8 |
| tooling | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --test tests/launcher.test.js` | 0; 20 tests, 20 pass, no failures/skips/cancellations |
| tooling | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check` | 0; strict TypeScript and 11 canonical skill/four-command/template/reference checks |
| tooling | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test` | 0; 86 tests, 86 pass, 52 top-level cases, no failures/skips/cancellations |
| tooling | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs` | 0; eight fresh CLI probes, canonical commands/prompts/skills, five fixed agents, bounded permissions and registered low/max mappings |
| tooling | `sh scripts/opencode-project.sh --version` | 0; OpenCode 1.18.34; CLI only |
| root | `git diff --check` | 0 |
| root | `python roadmap/check_docs.py` | 0; links/fragments, ignored-plan independence, owned/untracked whitespace, phase references/skills/structures |
| root | `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` | 0; `uv run --group docs zensical build --strict`, no issues, build 0.21s |
| root | `git ls-files roadmap` | 0; empty |
| root | `git check-ignore roadmap/canonical-skill-launch-fix.md .agents/.test-build` | 0; both ignored |
| root | `git diff --cached --exit-code a1a4afc4bf332649146b726fc59fa0e560fbb591 --` | 0 before and after edits/checks; staged checkpoint unchanged |
| root | `sh -n .agents/scripts/opencode-project.sh` | 0; POSIX shell syntax check |

After writing this receipt, `git diff --check`, `python roadmap/check_docs.py`,
`git ls-files roadmap` and the exact cached-checkpoint comparison were rerun and
exited 0. A read-only Python assertion reconstructed the four-file zero-context
diff via the Git commands below, compared it byte-for-byte with the fenced patch
in this receipt, and verified the recorded SHA-256; exit 0.

Python application, PostgreSQL, HTTP, Svelte and browser gates are not applicable:
no application boundary changed. No missing infrastructure or source-gate failure
was observed. The inventory harness failure below is new worker validation error,
not a baseline failure or a hidden source failure.

### Bounded inventory sequence: stopped after harness failure

The first fresh flagged CLI itself exited 0, and the parsed name inventory contained
the 11 expected project names **and** the supported built-in `customize-opencode`.
The wrapper exited 1 because it erroneously compared the complete name list with
only the project-skill list. It stopped before checking canonical locations or
duplicate warnings, so that invocation is not counted as a successful inventory
gate. No second or third attempt and no retry-until-green followed.

The failing probe was this exact root command:

```sh
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node --input-type=module -e '
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { closeSync, mkdtempSync, openSync, readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { root, skills } from "./.agents/scripts/check-assets.mjs";
assert.equal(process.env.OPENCODE_DISABLE_EXTERNAL_SKILLS, "1");
const scratch = mkdtempSync(resolve(root, ".agents/.test-build/skill-inventory-"));
try {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const output = resolve(scratch, `inventory-${attempt}.json`);
    const fd = openSync(output, "wx", 0o600);
    let result;
    try {
      result = spawnSync("sh", [".agents/scripts/opencode-project.sh", "debug", "skill"], {
        cwd: root, stdio: ["ignore", fd, "pipe"], timeout: 60_000,
      });
    } finally { closeSync(fd); }
    assert.ok(!result.error && result.status === 0, `Inventory ${attempt} CLI failed; raw output withheld`);
    let inventory;
    try { inventory = JSON.parse(readFileSync(output, "utf8")); }
    catch { throw new Error(`Inventory ${attempt} JSON incomplete; raw output withheld`); }
    assert.ok(Array.isArray(inventory), `Inventory ${attempt} shape differs`);
    assert.deepEqual(inventory.map(item => item.name).sort(), skills);
    for (const name of skills) {
      assert.ok(inventory.find(item => item.name === name)?.location === resolve(root, `.agents/skills/${name}/SKILL.md`),
        `Inventory ${attempt} noncanonical location: ${name}`);
    }
    const externalHomeLocations = inventory.filter(item => /^\/home\/karl\/\.(?:agents|claude)\//.test(item.location)).length;
    const duplicateWarnings = /duplicate.*skill|skill.*duplicate/i.test(result.stderr.toString());
    assert.equal(externalHomeLocations, 0, `Inventory ${attempt} external home skill present`);
    assert.equal(duplicateWarnings, false, `Inventory ${attempt} duplicate skill warning`);
    console.log(JSON.stringify({ attempt, exit: result.status, canonicalSkills: inventory.length, externalHomeLocations, duplicateWarnings,
      locations: skills.map(name => ({ name, location: inventory.find(item => item.name === name).location })) }));
  }
} finally { rmSync(scratch, { recursive: true }); }
'
```

Required reconciliation: permit a new fixed three-process sequence that distinguishes
the built-in while requiring every one of the 11 project names to resolve exactly
once to its canonical path, rejecting home locations and duplicate warnings. No
live source assertion or permission needs weakening to correct this harness.

## Preservation fingerprints

Initial tracked/untracked state was inspected before edits. The supplied parent
inventory was 535 visible paths with the 230-raw-path staged tooling checkpoint;
this worker did not take ownership of broader dirty application/design work.
Existing untracked `design/raw-first.md` and catalog interface files were preserved.
Original export `/tmp/opencode/huron-checkpoint-Uhqf4Vzn` was not edited.

SHA-256 fingerprints, before / after (optional owned files remained unchanged):

| Path | Before | After |
| --- | --- | --- |
| `.git/index` | `53998d200d18ee33dbebebc0aef391c4a4972ed0c8ba6afc23d052846c1283f8` | same |
| `.agents/README.md` | `984455cdc8230db987c586614a54cbcc1b82f1bedbb846e713199efc4ba5fc06` | `16ad7da92f3b5fd670616ab0b2bf9ef1f373b1ad7d9407e875c4e20db604011b` |
| `.agents/scripts/check-resolved.mjs` | `7646cb7b7bab25ab5c5711eac232f78344356b9cbc134a3da3a7ae3281c9607f` | `9198922eae2f4862ed188bb1439bf14a9ed27c2a4a20329b0c60ae96670cc03c` |
| `.agents/scripts/opencode-project.sh` | absent | `ded295386ba0ed1e521fbd32c55525a9cc64e9f0b6a6ba677bcf6954dd40dc59` |
| `.agents/tests/launcher.test.js` | absent | `bc869e0b2158cda6e2b104254fd7b5c62810f03d36e87d9d189c3570cbbdee00` |
| `.agents/scripts/check-assets.mjs` | `a004ee879b634d56f6d3001b9bd3ff5130b5a33fd46da66bb76cd794fe86b6d3` | same |
| `.agents/tests/assets.test.js` | `215748d0b90ad3ef6e30acfdf69c7018baab8a16bdd73e4fe973a452c8748152` | same |

`git ls-files --stage -z | sha256sum` before and after:
`39ac6c24059abdaae820fb4baa2bfbe5cbaab7f75f1f3905c192ecf426825f01`.
Unowned tracked working diff fingerprint before and after:

```sh
git diff --binary -- . ':!.agents/README.md' ':!.agents/scripts/check-resolved.mjs' ':!.agents/scripts/check-assets.mjs' ':!.agents/tests/assets.test.js' | sha256sum
```

Result in both cases:
`8fc596fb692cd39f337e1ff7e91c25c260730be83f5c73db713b1dfa91d7424a`.
The original untracked-name inventory also remained unchanged after excluding
the two new owned files: `git ls-files --others --exclude-standard -z -- .
':!.agents/scripts/opencode-project.sh' ':!.agents/tests/launcher.test.js' |
sha256sum` returned the original
`e582d452cc87936ff7be69f456a2d397231820279cd82e51e4c3f6be2941eb5c`.
This is a name-inventory check, not a new claim that every untracked file's bytes
were independently rehashed. No broader preservation rebaseline was performed.
The new launcher/test are non-executable (filesystem mode 664, Git mode 100644);
only fixture stub executables have executable mode in owned disposable worktrees.

## Activation and remaining evidence

Current parent/serving runtime remains unflagged with previously loaded skill state.
Its selected maximum worker profile was not changed. Successful fresh flagged CLI
checks do **not** prove activation in that existing serving process. After worker
quiescence, the owner must quit/stop the old owned serving instance, launch from
the repository root through `sh .agents/scripts/opencode-project.sh` (preserving
the intended server arguments if applicable), and verify after restart. Flagging
only an attached client is insufficient. No serving-runtime activation is claimed.

Pending: parent-authorized corrected bounded inventories and independent
checkpoint review 3. Local receipt whitespace and preservation checks completed.
Without the corrected bounded inventory gate, this worker returns **BLOCKED**, not
READY FOR INDEPENDENT REVIEW or PASS. No additional inventory attempt is made;
the next invocation requires the parent's explicit reconciliation of the harness.

## Exact owned live diff

This zero-context patch includes the two untracked additions and is relative to
the untouched staged checkpoint. It contains no provider output or other dirty
work. SHA-256 (patch bytes including final newline):
`5a58ad6faf3538a9da1d527fa7d5e343cd07747af0334fcd0a57b8ee2377f0a1`.
Generated with `git diff --no-ext-diff --no-textconv --unified=0 --` for README and
checker (exit 0), followed in the displayed order by `git diff --no-ext-diff
--no-textconv --no-index --unified=0 -- /dev/null PATH` for each new file (expected
exit 1 means a diff exists). No index changes are involved.

```diff
diff --git a/.agents/README.md b/.agents/README.md
index 83dbb50..52fb467 100644
--- a/.agents/README.md
+++ b/.agents/README.md
@@ -50 +50,27 @@ Use a Node version satisfying `package.json`'s engine range (required by the loc
-tool dependencies). Run `npm ci --ignore-scripts` from `.agents/`, then quit and restart OpenCode.
+tool dependencies). Run `npm ci --ignore-scripts` from `.agents/`. After workers and
+owned processes are quiescent, quit and restart OpenCode **from the repository root
+through the project launcher**:
+
+```sh
+sh .agents/scripts/opencode-project.sh
+```
+
+The launcher exports the supported `OPENCODE_DISABLE_EXTERNAL_SKILLS=1` before
+`exec opencode "$@"`, forwarding arguments, exit status and signals without a wrapper
+process. No executable-bit change is needed. In OpenCode 1.18.34, discovered skill
+files are parsed concurrently and same-name resolution is not reliable precedence:
+a home `prototype` can replace the canonical project skill even with `skills.paths`
+configured. The flag disables automatic external `.agents`/`.claude` scans at home
+and project scopes; the explicit `.agents/skills` registration still loads all 11
+canonical skills. Global assets remain untouched. This addresses the current
+external home-skill collision, not all possible duplicates: normal OpenCode skill
+directories and additional configured skill paths can still introduce collisions.
+
+**The flag must apply to the serving OpenCode process.** If using `serve` or `web`,
+start that process through the launcher with its existing arguments after quiescing
+and stopping the old owned instance; do not start a competing server. Attaching a
+flagged client to an unflagged server does not change the server environment or its
+cached skills. Installing the launcher or checking a fresh CLI does not activate
+the fix in an already running session; serving-runtime activation remains pending
+until quit/restart through the launcher and verification after restart.
+
@@ -53 +79,2 @@ access to `gpt-6-astra`; this project does not install credentials or substitute
-another model. Inspect configuration with `opencode debug agent markdown-orchestrator`
+another model. Inspect configuration from the repository root with
+`sh .agents/scripts/opencode-project.sh debug agent markdown-orchestrator`
@@ -167,8 +194,17 @@ After changing registration, inspect the resolved commands and workflow agents w
-`opencode debug config` and `opencode debug agent markdown-orchestrator`. Keep any
-credential-bearing provider configuration out of shared diagnostic output.
-
-`node scripts/check-resolved.mjs` from `.agents/` checks actual resolved config,
-workflow agents and canonical skill locations while printing only safe summaries.
-It invokes the installed OpenCode CLI and makes no child/model calls. Always quit
-and restart OpenCode after config, plugin, prompt or skill changes; the running
-session keeps the previously loaded tools and permissions.
+the project launcher and `debug config` / `debug agent markdown-orchestrator` arguments.
+Keep any credential-bearing provider configuration out of shared diagnostic output;
+prefer the safe checker below.
+
+From `.agents/`:
+
+```sh
+OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs
+```
+
+This checks actual resolved config, workflow agents and canonical skill locations
+while printing only safe summaries. It rejects a missing or different flag before
+any CLI invocation rather than silently setting it. It invokes fresh installed
+OpenCode CLI processes and makes no child/model calls; success proves their
+environment and inventory, not the active serving process or its cached skills.
+Always quit and restart OpenCode through the launcher after config, plugin, prompt
+or skill changes; the running session keeps the previously loaded tools and permissions.
diff --git a/.agents/scripts/check-resolved.mjs b/.agents/scripts/check-resolved.mjs
index b9517d5..d77ecad 100644
--- a/.agents/scripts/check-resolved.mjs
+++ b/.agents/scripts/check-resolved.mjs
@@ -6,0 +7,8 @@ import { lifecycle, modelVariantIssues, normalizedPermissionRules, root, skills,
+if (process.env.OPENCODE_DISABLE_EXTERNAL_SKILLS !== "1") {
+  console.error("Resolved checks require OPENCODE_DISABLE_EXTERNAL_SKILLS=1 before invoking OpenCode. " +
+    "Quit/restart the serving process from the repository root with sh .agents/scripts/opencode-project.sh; " +
+    "a flagged attached client is insufficient. From .agents/, run " +
+    "OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs (fresh CLI only, not serving-process verification).");
+  process.exit(1);
+}
+
diff --git a/.agents/scripts/opencode-project.sh b/.agents/scripts/opencode-project.sh
new file mode 100644
index 0000000..52fab9a
--- /dev/null
+++ b/.agents/scripts/opencode-project.sh
@@ -0,0 +1,5 @@
+#!/bin/sh
+set -eu
+
+export OPENCODE_DISABLE_EXTERNAL_SKILLS=1
+exec opencode "$@"
diff --git a/.agents/tests/launcher.test.js b/.agents/tests/launcher.test.js
new file mode 100644
index 0000000..6e5bec5
--- /dev/null
+++ b/.agents/tests/launcher.test.js
@@ -0,0 +1,159 @@
+import assert from "node:assert/strict";
+import { spawnSync } from "node:child_process";
+import { copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
+import { dirname, join, resolve } from "node:path";
+import { test } from "node:test";
+import { lifecycle, root, skills, workflowAgents } from "../scripts/check-assets.mjs";
+
+const launcher = resolve(root, ".agents/scripts/opencode-project.sh");
+
+async function setup(t, body = "process.exitCode = Number(process.env.STUB_EXIT ?? 0);") {
+  const worktree = await mkdtemp("/tmp/opencode/launcher-test-");
+  t.after(() => rm(worktree, { recursive: true }));
+  const bin = join(worktree, "bin");
+  await mkdir(bin);
+  const calls = join(worktree, "calls.jsonl");
+  await writeFile(join(bin, "opencode"), `#!${process.execPath}
+const { appendFileSync, readFileSync } = require("node:fs");
+const args = process.argv.slice(2);
+appendFileSync(process.env.STUB_CALLS, JSON.stringify({
+  args, flag: process.env.OPENCODE_DISABLE_EXTERNAL_SKILLS, cwd: process.cwd()
+}) + "\\n");
+${body}
+`, { mode: 0o700 });
+  // No fallback PATH entry can invoke a real OpenCode process or start a server.
+  const env = { PATH: bin, STUB_CALLS: calls };
+  return {
+    worktree, env, calls,
+    observed: async () => (await readFile(calls, "utf8")).trim().split("\n").map(line => JSON.parse(line)),
+  };
+}
+
+async function checkerSetup(t) {
+  const fixture = await setup(t, `
+const responses = JSON.parse(readFileSync(process.env.STUB_RESPONSES, "utf8"));
+const response = responses[args.join(" ")];
+if (response === undefined) throw new Error("Unexpected stub CLI arguments");
+process.stdout.write(typeof response === "string" ? response : JSON.stringify(response));`);
+  for (const path of [
+    ".agents/scripts/check-resolved.mjs", ".agents/scripts/check-assets.mjs",
+    ...lifecycle.map(name => `.agents/commands/${name}.md`),
+    ...["orchestrator", "implementer", "reviewer"].map(role => `.agents/prompts/${role}.md`),
+  ]) {
+    const target = join(fixture.worktree, path);
+    await mkdir(dirname(target), { recursive: true });
+    await copyFile(resolve(root, path), target);
+  }
+  const config = JSON.parse(await readFile(resolve(root, "opencode.json"), "utf8"));
+  const responses = { "debug config": { default_agent: config.default_agent, command: {} } };
+  for (const name of lifecycle) {
+    responses["debug config"].command[name] = {
+      ...config.command[name], template: await readFile(resolve(root, `.agents/commands/${name}.md`), "utf8"),
+    };
+  }
+  for (const [name, { role }] of Object.entries(workflowAgents)) {
+    const agent = config.agent[name];
+    const rules = { ...config.permission, ...agent.permission };
+    responses[`debug agent ${name}`] = {
+      ...agent, model: { providerID: "openai", modelID: "gpt-6-astra" },
+      prompt: await readFile(resolve(root, `.agents/prompts/${role}.md`), "utf8"),
+      permission: Object.entries(rules).flatMap(([permission, value]) =>
+        Object.entries(typeof value === "string" ? { "*": value } : value)
+          .map(([pattern, action]) => ({ permission, pattern, action }))),
+    };
+  }
+  responses["models openai --verbose"] = "openai/gpt-6-astra\n" + JSON.stringify({
+    id: "gpt-6-astra", providerID: "openai",
+    variants: { low: { reasoningEffort: "low" }, max: { reasoningEffort: "max" } },
+  }) + "\n";
+  responses["debug skill"] = skills.map(name => ({
+    name, location: join(fixture.worktree, `.agents/skills/${name}/SKILL.md`),
+  }));
+  fixture.env.STUB_RESPONSES = join(fixture.worktree, "responses.json");
+  return {
+    ...fixture, responses,
+    check: async () => {
+      await writeFile(fixture.env.STUB_RESPONSES, JSON.stringify(responses));
+      return spawnSync(process.execPath, [join(fixture.worktree, ".agents/scripts/check-resolved.mjs")], {
+        cwd: join(fixture.worktree, ".agents"), env: fixture.env, encoding: "utf8", timeout: 10_000,
+      });
+    },
+  };
+}
+
+test("project launch overrides inherited skill flags and preserves every argument and exit status", async (t) => {
+  const args = ["--session", "name with spaces", "", "semi;colon", "$HOME", "$(printf literal)",
+    "`printf literal`", "'single' \"double\"", "*?[abc]", "line one\nline two", "--", "-n"];
+  for (const flag of [undefined, "", "0", "false", "true", "1"]) {
+    await t.test(`inherited flag ${JSON.stringify(flag) ?? "unset"}`, async (t) => {
+      const fixture = await setup(t);
+      if (flag !== undefined) fixture.env.OPENCODE_DISABLE_EXTERNAL_SKILLS = flag;
+      for (const status of [0, 23]) {
+        fixture.env.STUB_EXIT = String(status);
+        const result = spawnSync("/bin/sh", [launcher, ...args], {
+          cwd: root, env: fixture.env, encoding: "utf8", timeout: 10_000,
+        });
+        assert.equal(result.error, undefined);
+        assert.equal(result.status, status, result.stderr);
+        assert.equal(result.signal, null);
+      }
+      assert.deepEqual(await fixture.observed(), Array.from({ length: 2 }, () => ({ args, flag: "1", cwd: resolve(root) })));
+    });
+  }
+});
+
+test("project launch exposes the exec target's termination signal", async (t) => {
+  const fixture = await setup(t, 'process.kill(process.pid, "SIGTERM");');
+  const result = spawnSync("/bin/sh", [launcher], {
+    cwd: root, env: fixture.env, encoding: "utf8", timeout: 10_000,
+  });
+  assert.equal(result.error, undefined);
+  assert.equal(result.status, null);
+  assert.equal(result.signal, "SIGTERM");
+  assert.deepEqual(await fixture.observed(), [{ args: [], flag: "1", cwd: resolve(root) }]);
+});
+
+test("resolved checks reject missing or wrong flags before invoking any CLI or creating diagnostics", async (t) => {
+  for (const flag of [undefined, "", "0", "false", "true", "01"]) {
+    await t.test(`checker flag ${JSON.stringify(flag) ?? "unset"}`, async (t) => {
+      const fixture = await checkerSetup(t);
+      if (flag !== undefined) fixture.env.OPENCODE_DISABLE_EXTERNAL_SKILLS = flag;
+      const result = await fixture.check();
+      assert.equal(result.error, undefined);
+      assert.equal(result.status, 1);
+      assert.equal(result.stdout, "");
+      assert.match(result.stderr, /require OPENCODE_DISABLE_EXTERNAL_SKILLS=1/);
+      assert.match(result.stderr, /sh \.agents\/scripts\/opencode-project\.sh/);
+      assert.match(result.stderr, /serving process/);
+      await assert.rejects(stat(fixture.calls), { code: "ENOENT" });
+      await assert.rejects(stat(join(fixture.worktree, ".agents/.test-build")), { code: "ENOENT" });
+    });
+  }
+});
+
+test("an explicitly flagged checker still enforces resolved configuration, profiles and canonical skills", async (t) => {
+  for (const [name, mutate, error] of [
+    ["valid inventory", () => {}, undefined],
+    ["wrong primary", responses => { responses["debug config"].default_agent = "other"; }, /Resolved default primary differs/],
+    ["downgraded maximum", responses => { responses["debug agent markdown-implementer-max"].variant = "low"; }, /Resolved fixed Astra profile differs/],
+    ["noncanonical prototype", responses => { responses["debug skill"].find(skill => skill.name === "prototype").location = "/external/prototype/SKILL.md"; }, /Skill did not resolve to canonical local path: prototype/],
+  ]) {
+    await t.test(name, async (t) => {
+      const fixture = await checkerSetup(t);
+      fixture.env.OPENCODE_DISABLE_EXTERNAL_SKILLS = "1";
+      mutate(fixture.responses);
+      const result = await fixture.check();
+      assert.equal(result.error, undefined);
+      assert.equal(result.status, error ? 1 : 0, result.stderr);
+      if (error) assert.match(result.stderr, error);
+      else {
+        assert.equal(result.stderr, "");
+        assert.match(result.stdout, /Registered openai\/gpt-6-astra: low -> low, max -> max/);
+        assert.match(result.stdout, /Resolved skills: all 11 project skills use canonical local paths/);
+      }
+      const observed = await fixture.observed();
+      assert.ok(observed.length > 0);
+      assert.ok(observed.every(call => call.flag === "1"));
+    });
+  }
+});
```
