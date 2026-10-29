import assert from "node:assert/strict";
import { test } from "node:test";
import { spawnSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { createOpencodeClient } from "../../../.agents/node_modules/@opencode-ai/sdk/dist/index.js";
import { select, agentFor, capability, profileSchema, submit } from "./probe-api.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
const fixture = (name, effort) => ({ name, mode: "subagent", variant: effort,
  model: { providerID: "openai", modelID: "gpt-6-astra" }, options: { reasoningEffort: effort } });
const model = { variants: { low: { reasoningEffort: "low" }, max: { reasoningEffort: "max" } } };

function assertLifecycleStatus(text) {
  // Match the local docs checker's case-sensitive label and case-insensitive value.
  const statuses = [...text.matchAll(/^Status:[ \t]*(.*)$/gm)];
  assert.equal(statuses.length, 1, "expected exactly one lifecycle Status:");
  assert.match(statuses[0][1], /^(?:draft|blocked|ready|implementing|verified)(?:[ \t]+[—–-][ \t]+\S.*)?$/i);
}

test("fixed-agent request is typed against the installed original SDK", () => {
  const version = JSON.parse(readFileSync(resolve(root, ".agents/node_modules/@opencode-ai/sdk/package.json"), "utf8")).version;
  assert.equal(version, "1.17.18");
  const result = spawnSync(process.execPath, [resolve(root, ".agents/node_modules/typescript/bin/tsc"),
    "--noEmit", "--allowJs", "--checkJs", "--strict", "--target", "ES2023", "--module", "NodeNext",
    "--moduleResolution", "NodeNext", "--skipLibCheck", resolve(here, "probe-api.mjs")], { cwd: here, encoding: "utf8" });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test("real SDK serializes both fixed agents without an untyped variant field", async () => {
  for (const role of ["implementation", "fix", "verification"]) {
    for (const profile of ["preparatory", "maximum"]) {
      const expected = agentFor(role, profile);
      const requests = [];
      const client = createOpencodeClient({ baseUrl: "https://probe.invalid", fetch: async request => {
        assert.equal(request.method, "POST");
        assert.equal(new URL(request.url).pathname, "/session/synthetic-child/prompt_async");
        assert.equal(new URL(request.url).searchParams.get("directory"), "/isolated/probe");
        requests.push(await request.json());
        return new Response(null, { status: 204 });
      } });
      const effort = profile === "maximum" ? "max" : "low";
      assert.equal(capability(fixture(expected, effort), model, expected, profile), effort);
      await submit(client, expected);
      assert.equal(requests.length, 1);
      assert.equal(requests[0].agent, expected);
      assert.deepEqual(requests[0].model, { providerID: "openai", modelID: "gpt-6-astra" });
      assert.equal("variant" in requests[0], false);
    }
  }
});

test("generated profile schema rejects invalid values and code cannot downgrade", () => {
  for (const value of [null, "", "low", "max", "Maximum", " maximum ", false, 0, [], {}, { profile: "maximum" }]) {
    assert.equal(profileSchema.safeParse(value).success, false);
    assert.throws(() => select(value, "planning"));
  }
  for (const activity of ["code", "legacy-exclusive", "planning", "prototype", "discovery", "review"]) {
    assert.equal(select(undefined, activity), "maximum");
    assert.equal(select("maximum", activity), "maximum");
    if (["code", "legacy-exclusive"].includes(activity)) assert.throws(() => select("preparatory", activity));
    else assert.equal(select("preparatory", activity), "preparatory");
  }
});

test("capability drift fails before any synthetic reservation or HTTP request", () => {
  const name = "markdown-implementer-max";
  const cases = [
    [undefined, model], [fixture("markdown-implementer", "low"), model],
    [{ ...fixture(name, "max"), mode: "primary" }, model],
    [{ ...fixture(name, "max"), variant: undefined }, model],
    [{ ...fixture(name, "max"), options: { reasoningEffort: "high" } }, model],
    [{ ...fixture(name, "max"), model: { providerID: "other", modelID: "gpt-6-astra" } }, model],
    [fixture(name, "max"), {}], [fixture(name, "max"), { variants: { max: { reasoningEffort: "high" } } }],
    [fixture(name, "max"), { variants: { max: { reasoningEffort: "max", disabled: true } } }],
  ];
  let reservations = 0;
  for (const [agent, registered] of cases) assert.throws(() => {
    capability(agent, registered, name, "maximum");
    reservations += 1;
  });
  assert.equal(reservations, 0);
});

test("historical profile absence stays absent rather than becoming maximum", () => {
  // A projection experiment, NOT production record validation or filesystem durability.
  const historical = Object.freeze({ version: 1, dispatchID: "old", role: "implementation", activity: "code" });
  const bytes = JSON.stringify(historical);
  const receipt = { profile: historical.version === 1 ? "not-recorded" : "maximum", configured: null };
  assert.deepEqual(receipt, { profile: "not-recorded", configured: null });
  assert.equal(JSON.stringify(historical), bytes);
  assert.equal("profile" in historical, false);
});

test("lifecycle status accepts every state with optional rationale and case-insensitive values", () => {
  for (const state of ["draft", "blocked", "ready", "implementing", "verified"]) {
    for (const value of [state, state.toUpperCase(), state[0].toUpperCase() + state.slice(1)]) {
      for (const rationale of ["", " — reviewed evidence", " – reviewed evidence", " - reviewed evidence"]) {
        assert.doesNotThrow(() => assertLifecycleStatus(`# Plan\nStatus: ${value}${rationale}\n\n## Context\n`));
      }
    }
  }
  assert.doesNotThrow(() => assertLifecycleStatus("Status:\tREADY\t—\tEvidence\n"));
  assert.doesNotThrow(() => assertLifecycleStatus("Status:ready\n"));
});

test("lifecycle status rejects missing, malformed and duplicate declarations", () => {
  for (const text of ["", "# Plan\n", "status: ready\n", "STATUS: ready\n", " Status: ready\n",
    "Status:\n", "Status: complete\n", "Status: draft / ready\n", "Status: ready extra\n",
    "Status: ready— reason\n", "Status: ready —reason\n", "Status: ready — \n",
    "Status: ready \n", "Status: ready\nStatus: ready\n", "Status: draft\nStatus: verified\n",
    "Status: ready\nStatus: invalid\n", "Status: invalid\nStatus: ready\n"]) {
    assert.throws(() => assertLifecycleStatus(text), { name: "AssertionError" }, JSON.stringify(text));
  }
});

test("owned documents have existing local links, complete plan sections and clean whitespace", () => {
  for (const path of [resolve(root, "roadmap/plans/astra-effort-profiles.md"),
    resolve(root, "roadmap/effort-profile-design.md"), resolve(here, "probe-api.mjs"), fileURLToPath(import.meta.url)]) {
    const text = readFileSync(path, "utf8");
    assert.ok(text.endsWith("\n"), path);
    assert.ok(!/[\t ]+$/m.test(text), path);
    if (!path.endsWith(".md")) continue;
    for (const [, target] of text.matchAll(/\[[^\]\n]*\]\(([^)\s]+)\)/g)) {
      if (/^[a-z]+:/i.test(target)) continue;
      assert.ok(existsSync(resolve(dirname(path), target.split("#")[0])), `${path}: ${target}`);
    }
    if (path.endsWith("astra-effort-profiles.md")) {
      for (const section of ["Context and outcome", "Prototype evidence", "Exact scope and ownership",
        "Interfaces and implementation examples", "Serial task slices", "Skills", "Acceptance and complete applicable gates",
        "Blockers and readiness", "Execution ledger", "Escalation / final receipt"]) assert.ok(text.includes(`## ${section}\n`), section);
      assertLifecycleStatus(text);
    }
  }
});
