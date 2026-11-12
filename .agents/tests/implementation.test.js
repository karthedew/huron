import assert from "node:assert/strict";
import { test } from "node:test";
import { createOpencodeClient } from "@opencode-ai/sdk";
import { tool } from "@opencode-ai/plugin";
import plugin from "../.test-build/implementation.js";
import { mkdtemp, mkdir, readFile, writeFile, unlink, stat } from "node:fs/promises";
import { join } from "node:path";
import { inspect } from "node:util";

const profileEfforts = { preparatory: "low", medium: "medium", maximum: "max" };
const agentEfforts = {
  "markdown-orchestrator": "low", "markdown-implementer": "low", "markdown-reviewer": "low",
  "markdown-implementer-medium": "medium", "markdown-reviewer-medium": "medium",
  "markdown-implementer-max": "max", "markdown-reviewer-max": "max",
};
const variants = () => Object.fromEntries(Object.values(profileEfforts).map(effort => [effort, { reasoningEffort: effort, disabled: false }]));

async function setup() {
  const directory = await mkdtemp("/tmp/opencode/dispatch-test-");
  await mkdir(join(directory, ".agents"));
  const state = {
    children: [], messages: [], statuses: {}, calls: [],
    histories: {}, listed: [], hiddenParents: [], createFailure: false, missing: new Set(),
    configured: true, available: true, dispatchFailure: false, statusFailure: false,
  };
  const client = createOpencodeClient({
    baseUrl: "http://opencode.test",
    fetch: async (request) => {
      const url = new URL(request.url);
      const body = request.method === "POST" ? await request.json() : undefined;
      state.calls.push({ path: url.pathname, method: request.method, body });
      assert.ok(request.signal);
      if (state.failPath === url.pathname) {
        const detail = "synthetic-private-sdk-detail";
        if (state.failureKind === "transport") throw new Error(detail, { cause: { body: detail } });
        if (state.failureKind === "json") return Response.json({ name: "ServerError", data: { message: detail } }, { status: 503 });
        return new Response(detail, { status: 503 });
      }
      assert.equal(url.searchParams.get("directory"), directory);
      const id = url.pathname.split("/")[2];
      if (url.pathname.endsWith("/children")) return Response.json(state.hiddenParents.includes(id) ? [] : state.children.filter(child => child.parentID === id));
      if (url.pathname.endsWith("/message")) return Response.json(state.histories[id] ?? state.messages);
      if (url.pathname === "/session/status") {
        return state.statusFailure ? new Response("unavailable", { status: 503 }) : Response.json(state.statuses);
      }
       if (url.pathname === "/agent") return Response.json(
          Object.entries(agentEfforts).filter(([name]) => name !== "markdown-orchestrator").map(([name, effort]) => {
           const agent = { name, mode: "subagent", variant: effort,
             model: { providerID: "openai", modelID: "gpt-6-astra" },
             options: { reasoningEffort: state.configured ? effort : "high" } };
           if (state.agentMutation) state.agentMutation(agent);
           return agent;
         }));
      if (url.pathname === "/config/providers") return Response.json({
         providers: state.available ? [{ id: "openai", models: { "gpt-6-astra": {
            variants: state.variants ?? variants(),
         } } }] : [],
      });
      if (url.pathname === "/session") {
        if (request.method === "GET") return Response.json(state.listed);
        const child = { id: state.children.length ? `child-${state.children.length + 1}` : "child", parentID: body.parentID, title: body.title, time: { created: 1000 } };
        state.children.push(child);
        if (state.afterCreate) await state.afterCreate();
        if (state.createFailure) throw new Error("lost create response");
        return Response.json(child);
      }
      if (request.method === "GET" && url.pathname.startsWith("/session/")) {
        const child = state.children.find(child => child.id === id);
        return child && !state.missing.has(id) ? Response.json(child) : new Response(null, { status: 404 });
      }
      if (url.pathname.endsWith("/prompt_async")) {
        if (state.dispatchFailure) throw new Error("connection lost after dispatch");
        if (state.afterPrompt) await state.afterPrompt();
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected request ${request.method} ${url.pathname}`);
    },
  });
  const recreate = () => plugin({ client, directory, worktree: directory });
  const hooks = await recreate();
  const context = { sessionID: "parent", agent: "markdown-orchestrator", metadata(value) { state.metadata = value; } };
  return {
    state, hooks, context, directory, recreate,
    start: (role = "implementation", extra = {}) => hooks.tool.implementation_start.execute({ role, title: "slice", prompt: "complete assignment", ...extra }, context),
    poll: (sessionID = "child") => hooks.tool.implementation_status.execute({ sessionID }, context),
  };
}

test("the advertised launch schema preserves explicit classification and all profiles", async () => {
  const { hooks, state } = await setup();
  const schema = tool.schema.object(hooks.tool.implementation_start.args);
  for (const profile of Object.keys(profileEfforts)) {
    const assignment = { role: "verification", title: "review", prompt: "complete assignment",
      activity: "review", profile, claims: [{ resource: "plan:review", mode: "read" }] };
    assert.deepEqual(schema.parse(assignment), assignment);
  }
  assert.deepEqual(state.calls, []);
});

test("launch returns a pollable child with the configured model and role", async () => {
  for (const role of ["implementation", "fix", "verification"]) {
    const { state, start } = await setup();
    const result = JSON.parse(await start(role));
    assert.equal(result.sessionID, "child");
    assert.equal(result.configured.reasoningEffort, "max");
    assert.equal(result.configured.profile, "maximum");
    assert.equal(result.providerAcceptance, "not-proven");
    const dispatched = state.calls.find((call) => call.path.endsWith("/prompt_async"));
    assert.equal(dispatched.body.agent, role === "verification" ? "markdown-reviewer-max" : "markdown-implementer-max");
    assert.deepEqual(dispatched.body.model, { providerID: "openai", modelID: "gpt-6-astra" });
    assert.match(dispatched.body.parts[0].text, /^HURON_DISPATCH_V2/);
    assert.equal(dispatched.body.parts[1].text, "complete assignment");
    assert.equal(result.activity, "legacy-exclusive");
  }
});

test("poll exposes assistant progress and tool activity without tool inputs or reasoning", async () => {
  const { state, start, poll } = await setup();
  await start();
  state.statuses.child = { type: "busy" };
  state.messages = [{ info: { role: "assistant", time: { created: 2000 } }, parts: [
    { type: "text", text: "Two fixes complete; running contracts." },
    { type: "reasoning", text: "private reasoning" },
    { type: "tool", tool: "bash", state: { status: "running", input: { secret: "credential" }, title: "contract tests", time: { start: 3000 } } },
  ] }];
  const output = await poll();
  const result = JSON.parse(output);
  assert.equal(result.terminal, false);
  assert.equal(result.status.type, "busy");
  assert.equal(result.text, "Two fixes complete; running contracts.");
  assert.equal(result.tools[0].title, undefined);
  assert.ok(!output.includes("contract tests"));
  assert.ok(!output.includes("credential"));
  assert.ok(!output.includes("private reasoning"));
});

test("idle and intermediate tool turns cannot be mistaken for a completed assignment", async () => {
  const { state, start, poll } = await setup();
  await start();
  for (const finish of [undefined, "tool-calls", "length"]) {
    state.messages = [{ info: { role: "assistant", time: { created: 1, completed: 2 }, finish }, parts: [] }];
    assert.equal(JSON.parse(await poll()).terminal, false);
    await assert.rejects(start(), /active or indeterminate/);
  }
  state.messages[0].info.finish = "stop";
  state.messages[0].parts = [{ type: "text", text: "FAIL: missing a required test." }];
  assert.equal(JSON.parse(await poll()).terminal, true);
  assert.match(JSON.parse(await poll()).text, /^FAIL/);
  state.statuses.child = { type: "busy" };
  assert.equal(JSON.parse(await poll()).terminal, false);
});

test("dispatch uncertainty preserves discoverable identity and blocks replacement", async () => {
  const { state, start, poll, hooks, context } = await setup();
  state.dispatchFailure = true;
  assert.equal(JSON.parse(await start()).state, "dispatch-indeterminate");
  assert.equal(JSON.parse(await poll()).terminal, false);
  const children = JSON.parse(await hooks.tool.implementation_status.execute({}, context));
  assert.equal(children[0].sessionID, "child");
  await assert.rejects(start(), /active or indeterminate/);
  assert.equal(state.calls.filter((call) => call.path === "/session" && call.method === "POST").length, 1);
});

test("exclusive admission survives plugin recreation and blocks simultaneous instances", async () => {
  const { start, state, recreate, context } = await setup();
  const restored = await recreate();
  const second = () => restored.tool.implementation_start.execute({ role: "implementation", title: "other", prompt: "assignment" }, context);
  const results = await Promise.allSettled([start(), second()]);
  assert.equal(results.filter(result => result.status === "fulfilled").length, 1);
  assert.equal(state.children.length, 1);
  await assert.rejects(second(), /active or indeterminate/);
});

test("status errors fail closed and unrelated session contents are inaccessible", async () => {
  const { state, start, poll } = await setup();
  await start();
  await assert.rejects(poll("unrelated"), /direct children/);
  state.statusFailure = true;
  await assert.rejects(poll());
  await assert.rejects(start());
});

test("a completed child permits the next serial assignment but a resumed user turn does not", async () => {
  const { state, start, poll } = await setup();
  await start();
  state.messages = [{ info: { role: "assistant", time: { created: 1, completed: 2 }, finish: "stop" }, parts: [] }];
  assert.equal(JSON.parse(await start("verification")).state, "submitted");
  state.messages.push({ info: { role: "user", time: { created: 3 } }, parts: [] });
  assert.equal(JSON.parse(await poll()).terminal, false);
  await assert.rejects(start(), /active or indeterminate/);
});

test("retry and aborted responses remain visible without inventing a PASS verdict", async () => {
  const { state, start, poll } = await setup();
  await start();
  state.statuses.child = { type: "retry", attempt: 2, message: "provider unavailable", next: 4000 };
  assert.equal(JSON.parse(await poll()).status.type, "retry");
  await assert.rejects(start(), /active or indeterminate/);
  state.statuses = {};
  state.messages = [{ info: { role: "assistant", time: { created: 1, completed: 2 }, error: { name: "MessageAbortedError", data: { message: "cancelled" } } }, parts: [] }];
  const result = JSON.parse(await poll());
  assert.equal(result.terminal, true);
  assert.equal(result.error, "MessageAbortedError");
  assert.equal(result.text, "");
});

test("invalid agent configuration or unavailable model prevents creation", async () => {
  for (const field of ["configured", "available"]) {
    const { state, start } = await setup();
    state[field] = false;
    await assert.rejects(start(), field === "configured" ? /must match its fixed Astra profile/ : /is unavailable; no child was launched/);
    assert.equal(state.children.length, 0);
  }
});

test("SDK read failures expose only safe diagnostics and never create replacement children", async (t) => {
  for (const failureKind of ["json", "plaintext", "transport"]) {
    for (const [operation, path, message] of [
      ["list", "/session/parent/children", "Unable to read workflow children; status is indeterminate."],
      ["poll", "/session/parent/children", "Unable to read workflow children; status is indeterminate."],
      ["poll", "/session/child/message", "Unable to read workflow messages; status is indeterminate."],
      ["poll", "/session/status", "Unable to read workflow status; status is indeterminate."],
      ["start", "/agent", "Unable to verify workflow agent configuration; no child was launched."],
      ["start", "/config/providers", "Unable to verify workflow model availability; no child was launched."],
    ]) {
      await t.test(`${operation} ${path} ${failureKind}`, async () => {
        const { state, start, poll, hooks, context, directory } = await setup();
        if (operation !== "start") await start();
        state.failPath = path;
        state.failureKind = failureKind;
        const invoke = operation === "start" ? start : operation === "poll" ? poll
          : () => hooks.tool.implementation_status.execute({}, context);
        const [outcome] = await Promise.allSettled([invoke()]);
        // Inspect returned values and non-enumerable Error fields, including nested causes.
        assert.ok(!inspect(outcome, { depth: null, showHidden: true }).includes("synthetic-private-sdk-detail"));
        assert.equal(outcome.status, "rejected");
        assert.equal(outcome.reason.message, message);
        assert.equal(outcome.reason.cause, undefined);
        assert.equal(state.children.length, operation === "start" ? 0 : 1);
        assert.equal(state.calls.filter(call => call.method === "POST").length, operation === "start" ? 0 : 2);
        if (operation === "start") {
          await assert.rejects(readFile(join(directory, ".agents/.dispatch-state/ledger.json")), { code: "ENOENT" });
        }
      });
    }
  }
});

test("nested launch is refused and fixed Astra profiles are enforced only for workflow agents", async () => {
  const { context, start, hooks } = await setup();
  context.agent = "markdown-implementer";
  await assert.rejects(start(), /Only markdown-orchestrator/);
  const output = { options: { reasoningEffort: "high" } };
  await hooks["chat.params"]({ agent: "markdown-reviewer", model: { id: "gpt-6-astra", providerID: "openai" } }, output);
  assert.equal(output.options.reasoningEffort, "low");
  await assert.rejects(hooks["chat.params"]({ agent: "markdown-reviewer", model: { id: "other", providerID: "openai" } }, output), /refusing substitution/);
  output.options.reasoningEffort = "high";
  await hooks["chat.params"]({ agent: "general", model: {} }, output);
  assert.equal(output.options.reasoningEffort, "high");
  for (const [agent, effort] of Object.entries(agentEfforts)) {
    output.options.reasoningEffort = "high";
    await hooks["chat.params"]({ agent, model: { id: "gpt-6-astra", providerID: "openai" } }, output);
    assert.equal(output.options.reasoningEffort, effort);
    await assert.rejects(hooks["chat.params"]({ agent, model: { id: "gpt-6-astra", providerID: "other" } }, output), /refusing substitution/);
    context.agent = agent === "markdown-orchestrator" ? "markdown-unknown" : agent;
    await assert.rejects(start(), /Only markdown-orchestrator/);
  }
  output.options.reasoningEffort = "medium";
  await hooks["chat.params"]({ agent: "markdown-unknown", model: {} }, output);
  assert.equal(output.options.reasoningEffort, "medium");
});

test("project retirement removes only the inherited competing workflow commands", async () => {
  const { hooks } = await setup();
  const config = { command: {
    "architectural-review": { template: "retired workflow" },
    execute_plan: { template: "retired implementation loop" },
    "design-plan": { template: "local design" },
    "implement-markdown": { template: "local implementation" },
    personal: { template: "unrelated user command" },
  } };
  await hooks.config(config);
  assert.deepEqual(Object.keys(config.command), ["design-plan", "implement-markdown", "personal"]);
  await hooks.config({});
});

const classified = (activity, resource = "subject", mode = "write") => ({ activity, claims: [{ resource, mode }] });
const terminal = () => [{ info: { id: "final", role: "assistant", time: { created: 1, completed: 2 }, finish: "stop" }, parts: [] }];

test("profiles select fixed typed agents and persist accurate configured ownership", async () => {
  for (const role of ["implementation", "fix", "verification"]) {
    for (const [profile, effort] of Object.entries(profileEfforts)) {
      const { start, state, poll, recreate, context, directory } = await setup();
      const activity = role === "verification" ? "review" : profile === "preparatory" ? "planning" : "code";
      const result = JSON.parse(await start(role, { ...classified(activity), profile }));
      const agent = `markdown-${role === "verification" ? "reviewer" : "implementer"}${effort === "low" ? "" : `-${effort}`}`;
      assert.deepEqual(result.configured, { profile, agent, model: "openai/gpt-6-astra", reasoningEffort: effort });
      assert.equal(result.reasoningEffort, undefined);
      const payload = state.calls.find(call => call.path.endsWith("prompt_async")).body;
      assert.equal(payload.agent, agent);
      assert.equal(payload.variant, undefined);
      const created = state.calls.find(call => call.path === "/session" && call.method === "POST");
      assert.deepEqual(created.body, { parentID: context.sessionID, title: "slice" });
      assert.equal(state.children[0].parentID, context.sessionID);
      assert.equal(state.metadata.metadata.sessionID, result.sessionID);
      assert.equal(state.metadata.metadata.dispatchID, result.dispatchID);
      const envelope = JSON.parse(payload.parts[0].text.split("\n")[1]);
      assert.equal(envelope.childID, result.sessionID);
      assert.equal(envelope.profile, profile);
      assert.equal(envelope.parentID, context.sessionID);
      const ledger = JSON.parse(await readFile(join(directory, ".agents/.dispatch-state/ledger.json"), "utf8"));
      assert.equal(ledger.version, 1);
      assert.equal(ledger.records[0].version, 2);
      assert.equal(ledger.records[0].profile, profile);
      const initial = JSON.parse(await poll());
      assert.equal(initial.model, undefined);
      assert.deepEqual(initial.ownership.configured, result.configured);
      const restored = await recreate();
      state.messages = [{ info: { role: "assistant", providerID: "openai", modelID: "gpt-6-astra", time: { created: 1, completed: 2 }, finish: "stop" }, parts: [] }];
      const observed = JSON.parse(await restored.tool.implementation_status.execute({ sessionID: "child" }, context));
      assert.equal(observed.model, "openai/gpt-6-astra");
      assert.equal(observed.providerAcceptance, "not-proven");
      assert.equal(observed.ownership.profile, profile);
      assert.equal(observed.terminal, true);
    }
  }
});

test("classified omission selects medium while legacy omission stays maximum for every role", async () => {
  for (const role of ["implementation", "fix", "verification"]) {
    for (const activity of role === "verification" ? ["discovery", "review"] : ["code", "planning", "prototype"]) {
      const { start } = await setup();
      const result = JSON.parse(await start(role, classified(activity)));
      assert.equal(result.configured.profile, "medium");
      assert.equal(result.configured.reasoningEffort, "medium");
    }
    for (const profile of [undefined, "medium", "maximum"]) {
      const { start } = await setup();
      const result = JSON.parse(await start(role, { profile }));
      assert.equal(result.activity, "legacy-exclusive");
      assert.deepEqual(result.claims, [{ resource: "*", mode: "write" }]);
      assert.equal(result.configured.profile, profile ?? "maximum");
      assert.equal(result.configured.reasoningEffort, profileEfforts[profile ?? "maximum"]);
    }
  }
});

test("profile downgrades and malformed selectors reject before all API or journal effects", async () => {
  const { start, state, directory, hooks } = await setup();
  for (const profile of [null, "", "max", " maximum", "Medium", "medium ", "low", "high", 1, {}, []]) {
    assert.equal(hooks.tool.implementation_start.args.profile.safeParse(profile).success, false);
    await assert.rejects(start("implementation", { ...classified("planning"), profile }), /Invalid dispatch/);
  }
  for (const role of ["implementation", "fix", "verification"]) {
    await assert.rejects(start(role, { profile: "preparatory" }), /Invalid dispatch/);
  }
  for (const role of ["implementation", "fix"]) {
    await assert.rejects(start(role, { ...classified("code"), profile: "preparatory" }), /Invalid dispatch/);
  }
  assert.equal(state.calls.length, 0);
  await assert.rejects(readFile(join(directory, ".agents/.dispatch-state/ledger.json")), { code: "ENOENT" });
  await assert.rejects(stat(join(directory, ".agents/.dispatch-state")), { code: "ENOENT" });
});

test("fixed agent and registered variant mismatches fail closed before reservation", async () => {
  for (const [profile, effort] of Object.entries(profileEfforts)) {
    for (const mutate of [agent => { agent.name = "unavailable"; }, agent => { agent.model.providerID = "other"; },
      agent => { agent.model.modelID = "other"; }, agent => { agent.mode = "primary"; },
      agent => { delete agent.variant; }, agent => { agent.variant = "high"; },
      agent => { agent.options.reasoningEffort = "high"; }, agent => { delete agent.options; },
      agent => { agent.options = null; }]) {
      const { start, state, directory } = await setup();
      const selected = `markdown-implementer${effort === "low" ? "" : `-${effort}`}`;
      state.agentMutation = agent => { if (agent.name === selected) mutate(agent); };
      await assert.rejects(start("implementation", { ...classified("planning"), profile }), /fixed Astra profile/);
      assert.equal(state.calls.some(call => call.method === "POST"), false);
      await assert.rejects(readFile(join(directory, ".agents/.dispatch-state/ledger.json")), { code: "ENOENT" });
    }
    for (const variant of [undefined, null, [], "max", {}, ...["low", "medium", "max", "high"].filter(other => other !== effort).map(other => ({ reasoningEffort: other })),
      { reasoningEffort: effort, disabled: true }, { reasoningEffort: effort, disabled: "false" }]) {
      const { start, state, directory } = await setup();
      state.variants = { ...variants(), [effort]: variant };
      await assert.rejects(start("verification", { ...classified("review"), profile }), /variant mapping/);
      assert.equal(state.calls.some(call => call.method === "POST"), false);
      await assert.rejects(readFile(join(directory, ".agents/.dispatch-state/ledger.json")), { code: "ENOENT" });
    }
  }
});

test("historical records retain absence of profile through status and appended dispatches", async () => {
  const { start, state, poll, directory, hooks, context, recreate } = await setup();
  await start("implementation", { ...classified("planning"), profile: "preparatory" });
  const path = join(directory, ".agents/.dispatch-state/ledger.json");
  const ledger = JSON.parse(await readFile(path, "utf8"));
  ledger.records[0].version = 1;
  delete ledger.records[0].profile;
  const historical = structuredClone(ledger.records[0]);
  const bytes = JSON.stringify(ledger);
  await writeFile(path, bytes);
  const snapshot = JSON.parse(await poll());
  assert.equal(snapshot.ownership.profile, "not-recorded");
  assert.equal(snapshot.ownership.configured, null);
  const listed = JSON.parse(await hooks.tool.implementation_status.execute({}, context));
  assert.equal(listed[0].ownership.profile, "not-recorded");
  assert.equal(await readFile(path, "utf8"), bytes);
  state.messages = terminal();
  await start("verification", { ...classified("review"), profile: "maximum" });
  const appended = JSON.parse(await readFile(path, "utf8"));
  assert.deepEqual(appended.records[0], historical);
  assert.equal(appended.records[1].version, 2);
  assert.equal(appended.records[1].profile, "maximum");
  await start("verification", { ...classified("review"), profile: "preparatory" });
  const prior = JSON.parse(await readFile(path, "utf8"));
  await start("verification", { ...classified("review"), profile: "medium" });
  const mixed = JSON.parse(await readFile(path, "utf8"));
  assert.deepEqual(mixed.records.slice(0, 3), prior.records);
  assert.equal(mixed.records[3].profile, "medium");
  const restored = await recreate();
  const children = JSON.parse(await restored.tool.implementation_status.execute({}, context));
  assert.deepEqual(children.map(child => child.ownership.profile), ["not-recorded", "maximum", "preparatory", "medium"]);
  assert.equal(children[0].ownership.configured, null);
  assert.equal(children[3].ownership.configured.reasoningEffort, "medium");
});

test("profile persists before each remote boundary and uncertain reads never invent acceptance", async () => {
  for (const profile of Object.keys(profileEfforts)) {
    const { start, state, directory, poll } = await setup();
    const readRecord = async () => JSON.parse(await readFile(join(directory, ".agents/.dispatch-state/ledger.json"), "utf8")).records[0];
    state.afterCreate = async () => {
      const record = await readRecord();
      assert.equal(record.state, "creating");
      assert.equal(record.profile, profile);
      assert.equal(record.childID, undefined);
    };
    state.afterPrompt = async () => {
      const record = await readRecord();
      assert.equal(record.state, "dispatching");
      assert.equal(record.profile, profile);
      assert.equal(record.childID, "child");
    };
    const result = JSON.parse(await start("implementation", { ...classified("planning"), profile }));
    assert.equal(result.state, "submitted");
    assert.equal((await readRecord()).profile, profile);
    assert.equal((await readRecord()).state, "submitted");
    assert.equal(JSON.parse(await poll()).providerAcceptance, "not-proven");
  }
});

test("concurrent scheduling is unchanged across all profile pairs", async () => {
  for (const first of Object.keys(profileEfforts)) {
    for (const second of Object.keys(profileEfforts)) {
      const { start, state } = await setup();
      await start("implementation", { ...classified("planning", "first"), profile: first });
      await start("verification", { ...classified("review", "second", "read"), profile: second });
      await assert.rejects(start("verification", { ...classified("review", "first", "read"), profile: second }), /active or indeterminate/);
      await assert.rejects(start("implementation", { ...classified("code", "third"), profile: "maximum" }), /active or indeterminate/);
      assert.equal(state.children.length, 2);
      state.messages = terminal();
      await start("implementation", { ...classified("code", "third"), profile: "maximum" });
      state.histories["child-3"] = [];
      await assert.rejects(start("verification", { ...classified("discovery", "other", "read"), profile: first }), /active or indeterminate/);
    }
  }
});

test("all explicit non-code activities overlap only with independent ownership", async () => {
  const { start, state, recreate, context } = await setup();
  for (const [role, activity] of [["implementation", "planning"], ["fix", "prototype"], ["verification", "discovery"], ["verification", "review"]]) {
    const result = JSON.parse(await start(role, classified(activity, activity)));
    assert.equal(result.activity, activity);
    assert.deepEqual(result.claims, classified(activity, activity).claims);
  }
  const restored = await recreate();
  await assert.rejects(restored.tool.implementation_start.execute({ role: "verification", title: "review", prompt: "inspect", ...classified("review", "planning", "read") }, context), /active or indeterminate/);
  assert.equal(state.children.length, 4);
});

test("code and every legacy role exclude non-code in both admission orders", async () => {
  for (const profile of ["medium", "maximum"]) {
    for (const otherProfile of Object.keys(profileEfforts)) {
      for (const role of ["implementation", "fix", "verification"]) {
        for (const explicit of role === "verification" ? [false] : [false, true]) {
          for (const reverse of [false, true]) {
            const { start, state } = await setup();
            const exclusive = () => start(role, { ...(explicit ? classified("code", "unrelated", "read") : {}), profile });
            const independent = () => start("verification", { ...classified("discovery", "other", "read"), profile: otherProfile });
            await (reverse ? independent() : exclusive());
            await assert.rejects(reverse ? exclusive() : independent(), /active or indeterminate/);
            assert.equal(state.children.length, 1);
          }
        }
      }
    }
  }
});

test("exact labels share read claims but writes and wildcards conflict", async () => {
  for (const first of Object.keys(profileEfforts)) {
    for (const second of Object.keys(profileEfforts)) {
      for (const [a, b, left, right, conflict] of [
        ["read", "read", "shared", "shared", false], ["read", "write", "shared", "shared", true],
        ["write", "read", "shared", "shared", true], ["write", "write", "shared", "shared", true],
        ["read", "write", "*", "other", true], ["write", "read", "other", "*", true],
        ["read", "read", "*", "other", false], ["write", "write", "plan", "plan:other", false],
      ]) {
        const { start, state } = await setup();
        await start("implementation", { ...classified("planning", left, a), profile: first });
        const next = start("implementation", { ...classified("planning", right, b), profile: second });
        if (conflict) await assert.rejects(next, /active or indeterminate/); else await next;
        assert.equal(state.children.length, conflict ? 1 : 2);
      }
    }
  }
});

test("invalid explicit requests reject before creation or reservation", async () => {
  const { start, state } = await setup();
  const invalid = [
    { activity: "planning" }, { claims: [{ resource: "a", mode: "read" }] }, classified("unknown"),
    classified("review"), { ...classified("planning"), claims: [] }, classified("planning", "a/*"),
    classified("planning", "A"), classified("planning", "a", "unknown"),
    { ...classified("planning"), claims: [{ resource: "a", mode: "read", extra: true }] },
    { ...classified("planning"), claims: [{ resource: "a", mode: "read" }, { resource: "a", mode: "write" }] },
    { ...classified("planning"), extra: true }, { title: "  " }, { prompt: "\n" },
  ];
  for (const args of invalid) await assert.rejects(start("implementation", args), /Invalid dispatch/);
  await assert.rejects(start("unknown"), /Invalid dispatch/);
  await assert.rejects(start("verification", classified("code")), /Invalid dispatch/);
  assert.equal(state.calls.length, 0);
});

test("create and prompt uncertainty persist without replay across recreation", async () => {
  for (const [profile, effort] of Object.entries(profileEfforts)) {
    for (const failure of ["createFailure", "dispatchFailure"]) {
      const { start, state, recreate, context } = await setup();
      state[failure] = true;
      const result = JSON.parse(await start("implementation", { ...classified("planning"), profile }));
      assert.equal(result.state, failure === "createFailure" ? "creation-indeterminate" : "dispatch-indeterminate");
      assert.equal(result.configured.profile, profile);
      assert.equal(result.configured.reasoningEffort, effort);
      assert.equal(result.providerAcceptance, "not-proven");
      assert.ok(result.dispatchID);
      assert.equal(result.sessionID, failure === "createFailure" ? undefined : "child");
      const restored = await recreate();
      await assert.rejects(restored.tool.implementation_start.execute({ role: "verification", title: "independent", prompt: "read", ...classified("discovery", "other") }, context), /active or indeterminate/);
      assert.equal(state.children.length, 1);
      assert.equal(state.calls.filter(call => call.path.endsWith("prompt_async")).length, failure === "createFailure" ? 0 : 1);
    }
  }
});

test("save failure after remote I/O is uncertainty and preserves child identity", async () => {
  for (const [profile, effort] of Object.entries(profileEfforts)) {
    for (const hook of ["afterCreate", "afterPrompt"]) {
      const { start, state, directory } = await setup();
      state[hook] = () => writeFile(join(directory, ".agents/.dispatch-state/ledger.json"), "corrupt");
      const result = JSON.parse(await start("implementation", { ...classified("planning"), profile }));
      assert.equal(result.state, "dispatch-indeterminate");
      assert.equal(result.sessionID, "child");
      assert.equal(result.configured.profile, profile);
      assert.equal(result.configured.reasoningEffort, effort);
      assert.equal(result.providerAcceptance, "not-proven");
      await assert.rejects(start(), /Invalid dispatch/);
      assert.equal(state.children.length, 1);
    }
  }
});

test("recorded parents and unknown other-parent children are reconciled privately", async () => {
  const { start, state, context, hooks } = await setup();
  await start("implementation", classified("planning", "private-plan"));
  context.sessionID = "second-parent";
  await start("verification", classified("discovery", "other"));
  assert.ok(state.calls.some(call => call.path === "/session/parent/children"));
  const own = JSON.parse(await hooks.tool.implementation_status.execute({}, context));
  assert.deepEqual(own.map(child => child.sessionID), ["child-2"]);
  await assert.rejects(hooks.tool.implementation_status.execute({ sessionID: "child" }, context), /direct children/);
  state.listed = [{ id: "private-child", parentID: "private-parent" }];
  const error = await start("verification", classified("discovery", "independent")).catch(error => error);
  assert.match(error.message, /active or indeterminate/);
  assert.ok(!/private|parent|child-2/.test(error.message));
  state.histories["private-child"] = terminal();
  await start("verification", classified("discovery", "independent"));
});

test("missing recorded children, list outages and children outages block admission", async () => {
  for (const failure of ["missing", "/session", "/session/parent/children", "/session/status"]) {
    const { start, state } = await setup();
    await start("implementation", classified("planning"));
    if (failure === "missing") state.missing.add("child"); else state.failPath = failure;
    await assert.rejects(start("verification", classified("discovery", "other")), /active or indeterminate/);
    assert.equal(state.children.length, 1);
  }
});

test("resumed children reacquire original claims even when omitted from enumeration", async () => {
  const { start, state } = await setup();
  await start("implementation", classified("planning"));
  state.histories.child = terminal();
  await start("verification", classified("review", "subject", "read"));
  state.histories["child-2"] = terminal();
  state.histories.child.push({ info: { role: "user", time: { created: 3 } }, parts: [] });
  state.hiddenParents = ["parent"];
  await assert.rejects(start("verification", classified("review", "subject", "read")), /active or indeterminate/);
  await start("verification", classified("discovery", "other"));
});

test("progress survives empty and user turns with strict windows and safe fields", async () => {
  const { start, state, poll } = await setup();
  await start();
  assert.equal(JSON.parse(await poll()).progress, null);
  state.messages = [{ info: { id: "progress", role: "assistant", time: { created: 123 } }, parts: [
    { type: "text", text: "x".repeat(4100) }, { type: "reasoning", text: "secret-reasoning" },
    ...Array.from({ length: 25 }, (_, i) => ({ id: `tool-${i}`, type: "tool", tool: "bash", state: {
      status: "completed", title: "secret-title", input: { secret: "secret-input" }, output: "secret-output", time: { start: i, end: i + 1 },
    } })),
  ] }, { info: { id: "empty", role: "assistant", time: { created: 124 }, finish: "tool-calls" }, parts: [] }];
  let output = await poll();
  let result = JSON.parse(output);
  assert.equal(result.text, "");
  assert.equal(result.progress.text.length, 4000);
  assert.equal(result.progress.truncated, true);
  assert.equal(result.progress.messageID, "progress");
  assert.equal(result.progress.createdAt, 123);
  assert.equal(result.recentTools.length, 20);
  assert.equal(result.recentTools[0].partID, "tool-5");
  assert.equal(result.recentTools[0].start, 5);
  assert.equal(result.windowMessages, 100);
  assert.ok(Number.isFinite(Date.parse(result.observedAt)));
  assert.ok(!output.includes("secret-"));
  state.messages.push({ info: { id: "user", role: "user", time: { created: 125 } }, parts: [{ type: "text", text: "secret-user" }] });
  state.statuses.child = { type: "retry", attempt: 2, next: 500, message: "secret-retry" };
  output = await poll();
  result = JSON.parse(output);
  assert.equal(result.terminal, false);
  assert.equal(result.text, undefined);
  assert.equal(result.progress.messageID, "progress");
  assert.deepEqual(result.status, { type: "retry", attempt: 2, next: 500 });
  assert.ok(!output.includes("secret-"));
  state.messages.push(...Array.from({ length: 100 }, () => ({ info: { role: "user", time: { created: 126 } }, parts: [] })));
  result = JSON.parse(await poll());
  assert.equal(result.progress, null);
  assert.deepEqual(result.recentTools, []);
  assert.equal(result.observedMessages, 100);
});

test("unknown children cannot regain parallel ownership from an envelope or missing ledger", async () => {
  const { start, state, directory, hooks, context } = await setup();
  await start("implementation", classified("planning"));
  const ledgerPath = join(directory, ".agents/.dispatch-state/ledger.json");
  const ledger = await readFile(ledgerPath, "utf8");
  assert.ok(!ledger.includes("complete assignment"));
  await unlink(ledgerPath); // This fixture owns its fresh worktree; simulate external loss.
  state.messages = [{ info: { role: "user", time: { created: 1 } }, parts: [{ type: "text", text: `HURON_DISPATCH_V1\n${ledger}` }] }];
  await assert.rejects(start("verification", classified("discovery", "other")), /active or indeterminate/);
  const children = JSON.parse(await hooks.tool.implementation_status.execute({}, context));
  assert.equal(children[0].ownership, "unknown");
  assert.equal(state.children.length, 1);
  state.messages = terminal();
  assert.equal(JSON.parse(await start()).state, "submitted");
});

test("dispatch-indeterminate terminal evidence allows reconciliation without replay", async () => {
  const { start, state } = await setup();
  state.dispatchFailure = true;
  await start();
  state.histories.child = terminal();
  state.dispatchFailure = false;
  await start("verification", classified("review"));
  assert.equal(state.children.length, 2);
  assert.equal(state.calls.filter(call => call.path === "/session/child/prompt_async").length, 1);
});

test("contradictory parent enumeration fails closed even when a recorded lookup succeeds", async () => {
  const { start, state } = await setup();
  await start("implementation", classified("planning"));
  state.hiddenParents = ["parent"];
  state.listed = [{ id: "child", parentID: "different-parent" }];
  await assert.rejects(start("verification", classified("discovery", "other")), /active or indeterminate/);
  assert.equal(state.children.length, 1);
});
