import assert from "node:assert/strict";
import { test } from "node:test";
import { createOpencodeClient } from "@opencode-ai/sdk";
import plugin from "../plugins/implementation.ts";

async function setup() {
  const state = {
    children: [], messages: [], statuses: {}, calls: [],
    configured: true, available: true, dispatchFailure: false, statusFailure: false,
  };
  const client = createOpencodeClient({
    baseUrl: "http://opencode.test",
    fetch: async (request) => {
      const url = new URL(request.url);
      const body = request.method === "POST" ? await request.json() : undefined;
      state.calls.push({ path: url.pathname, method: request.method, body });
      assert.equal(url.searchParams.get("directory"), "/workspace");
      if (url.pathname.endsWith("/children")) return Response.json(state.children);
      if (url.pathname.endsWith("/message")) return Response.json(state.messages);
      if (url.pathname === "/session/status") {
        return state.statusFailure ? new Response("unavailable", { status: 503 }) : Response.json(state.statuses);
      }
      if (url.pathname === "/agent") return Response.json([
        { name: "markdown-implementer", model: { providerID: "openai", modelID: "gpt-6-astra" }, options: { reasoningEffort: state.configured ? "low" : "high" } },
        { name: "markdown-reviewer", model: { providerID: "openai", modelID: "gpt-6-astra" }, options: { reasoningEffort: "low" } },
      ]);
      if (url.pathname === "/config/providers") return Response.json({
        providers: state.available ? [{ id: "openai", models: { "gpt-6-astra": {} } }] : [],
      });
      if (url.pathname === "/session") {
        const child = { id: "child", parentID: body.parentID, title: body.title, time: { created: 1000 } };
        state.children.push(child);
        return Response.json(child);
      }
      if (url.pathname.endsWith("/prompt_async")) {
        if (state.dispatchFailure) throw new Error("connection lost after dispatch");
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected request ${request.method} ${url.pathname}`);
    },
  });
  const hooks = await plugin({ client, directory: "/workspace" });
  const context = { sessionID: "parent", agent: "markdown-orchestrator", metadata() {} };
  return {
    state, hooks, context,
    start: (role = "implementation") => hooks.tool.implementation_start.execute({ role, title: "slice", prompt: "complete assignment" }, context),
    poll: (sessionID = "child") => hooks.tool.implementation_status.execute({ sessionID }, context),
  };
}

test("launch returns a pollable child with the configured model and role", async () => {
  for (const role of ["implementation", "fix", "verification"]) {
    const { state, start } = await setup();
    const result = JSON.parse(await start(role));
    assert.equal(result.sessionID, "child");
    assert.equal(result.reasoningEffort, "low");
    const dispatched = state.calls.find((call) => call.path.endsWith("/prompt_async"));
    assert.equal(dispatched.body.agent, role === "verification" ? "markdown-reviewer" : "markdown-implementer");
    assert.deepEqual(dispatched.body.model, { providerID: "openai", modelID: "gpt-6-astra" });
    assert.equal(dispatched.body.parts[0].text, "complete assignment");
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
  assert.equal(result.tools[0].title, "contract tests");
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
  assert.equal(state.calls.filter((call) => call.path === "/session").length, 1);
});

test("serial launch guard survives plugin recreation and blocks simultaneous launch", async () => {
  const { start, state } = await setup();
  const first = start();
  await assert.rejects(start(), /already in progress/);
  await first;
  const restored = await setup();
  restored.state.children = state.children;
  await assert.rejects(restored.start(), /active or indeterminate/);
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
    await assert.rejects(start());
    assert.equal(state.children.length, 0);
  }
});

test("nested launch is refused and Astra Low is enforced only for workflow agents", async () => {
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
});
