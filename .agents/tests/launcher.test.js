import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { lifecycle, root, skills, workflowAgents } from "../scripts/check-assets.mjs";

const launcher = resolve(root, ".agents/scripts/opencode-project.sh");

async function setup(t, body = "process.exitCode = Number(process.env.STUB_EXIT ?? 0);") {
  const worktree = await mkdtemp("/tmp/opencode/launcher-test-");
  t.after(() => rm(worktree, { recursive: true }));
  const bin = join(worktree, "bin");
  await mkdir(bin);
  const calls = join(worktree, "calls.jsonl");
  await writeFile(join(bin, "opencode"), `#!${process.execPath}
const { appendFileSync, readFileSync } = require("node:fs");
const args = process.argv.slice(2);
appendFileSync(process.env.STUB_CALLS, JSON.stringify({
  args, flag: process.env.OPENCODE_DISABLE_EXTERNAL_SKILLS, cwd: process.cwd()
}) + "\\n");
${body}
`, { mode: 0o700 });
  // No fallback PATH entry can invoke a real OpenCode process or start a server.
  const env = { PATH: bin, STUB_CALLS: calls };
  return {
    worktree, env, calls,
    observed: async () => (await readFile(calls, "utf8")).trim().split("\n").map(line => JSON.parse(line)),
  };
}

async function checkerSetup(t) {
  const fixture = await setup(t, `
const responses = JSON.parse(readFileSync(process.env.STUB_RESPONSES, "utf8"));
const response = responses[args.join(" ")];
if (response === undefined) throw new Error("Unexpected stub CLI arguments");
process.stdout.write(typeof response === "string" ? response : JSON.stringify(response));`);
  for (const path of [
    ".agents/scripts/check-resolved.mjs", ".agents/scripts/check-assets.mjs",
    ...lifecycle.map(name => `.agents/commands/${name}.md`),
    ...["orchestrator", "implementer", "reviewer"].map(role => `.agents/prompts/${role}.md`),
  ]) {
    const target = join(fixture.worktree, path);
    await mkdir(dirname(target), { recursive: true });
    await copyFile(resolve(root, path), target);
  }
  const config = JSON.parse(await readFile(resolve(root, "opencode.json"), "utf8"));
  const responses = { "debug config": { default_agent: config.default_agent, command: {} } };
  for (const name of lifecycle) {
    responses["debug config"].command[name] = {
      ...config.command[name], template: await readFile(resolve(root, `.agents/commands/${name}.md`), "utf8"),
    };
  }
  for (const [name, { role }] of Object.entries(workflowAgents)) {
    const agent = config.agent[name];
    const rules = { ...config.permission, ...agent.permission };
    responses[`debug agent ${name}`] = {
      ...agent, model: { providerID: "openai", modelID: "gpt-6-astra" },
      prompt: await readFile(resolve(root, `.agents/prompts/${role}.md`), "utf8"),
      permission: Object.entries(rules).flatMap(([permission, value]) =>
        Object.entries(typeof value === "string" ? { "*": value } : value)
          .map(([pattern, action]) => ({ permission, pattern, action }))),
    };
  }
  responses["models openai --verbose"] = "openai/gpt-6-astra\n" + JSON.stringify({
    id: "gpt-6-astra", providerID: "openai",
    variants: { low: { reasoningEffort: "low" }, max: { reasoningEffort: "max" } },
  }) + "\n";
  responses["debug skill"] = skills.map(name => ({
    name, location: join(fixture.worktree, `.agents/skills/${name}/SKILL.md`),
  }));
  fixture.env.STUB_RESPONSES = join(fixture.worktree, "responses.json");
  return {
    ...fixture, responses,
    check: async () => {
      await writeFile(fixture.env.STUB_RESPONSES, JSON.stringify(responses));
      return spawnSync(process.execPath, [join(fixture.worktree, ".agents/scripts/check-resolved.mjs")], {
        cwd: join(fixture.worktree, ".agents"), env: fixture.env, encoding: "utf8", timeout: 10_000,
      });
    },
  };
}

test("project launch overrides inherited skill flags and preserves every argument and exit status", async (t) => {
  const args = ["--session", "name with spaces", "", "semi;colon", "$HOME", "$(printf literal)",
    "`printf literal`", "'single' \"double\"", "*?[abc]", "line one\nline two", "--", "-n"];
  for (const flag of [undefined, "", "0", "false", "true", "1"]) {
    await t.test(`inherited flag ${JSON.stringify(flag) ?? "unset"}`, async (t) => {
      const fixture = await setup(t);
      if (flag !== undefined) fixture.env.OPENCODE_DISABLE_EXTERNAL_SKILLS = flag;
      for (const status of [0, 23]) {
        fixture.env.STUB_EXIT = String(status);
        const result = spawnSync("/bin/sh", [launcher, ...args], {
          cwd: root, env: fixture.env, encoding: "utf8", timeout: 10_000,
        });
        assert.equal(result.error, undefined);
        assert.equal(result.status, status, result.stderr);
        assert.equal(result.signal, null);
      }
      assert.deepEqual(await fixture.observed(), Array.from({ length: 2 }, () => ({ args, flag: "1", cwd: resolve(root) })));
    });
  }
});

test("project launch exposes the exec target's termination signal", async (t) => {
  const fixture = await setup(t, 'process.kill(process.pid, "SIGTERM");');
  const result = spawnSync("/bin/sh", [launcher], {
    cwd: root, env: fixture.env, encoding: "utf8", timeout: 10_000,
  });
  assert.equal(result.error, undefined);
  assert.equal(result.status, null);
  assert.equal(result.signal, "SIGTERM");
  assert.deepEqual(await fixture.observed(), [{ args: [], flag: "1", cwd: resolve(root) }]);
});

test("resolved checks reject missing or wrong flags before invoking any CLI or creating diagnostics", async (t) => {
  for (const flag of [undefined, "", "0", "false", "true", "01"]) {
    await t.test(`checker flag ${JSON.stringify(flag) ?? "unset"}`, async (t) => {
      const fixture = await checkerSetup(t);
      if (flag !== undefined) fixture.env.OPENCODE_DISABLE_EXTERNAL_SKILLS = flag;
      const result = await fixture.check();
      assert.equal(result.error, undefined);
      assert.equal(result.status, 1);
      assert.equal(result.stdout, "");
      assert.match(result.stderr, /require OPENCODE_DISABLE_EXTERNAL_SKILLS=1/);
      assert.match(result.stderr, /sh \.agents\/scripts\/opencode-project\.sh/);
      assert.match(result.stderr, /serving process/);
      await assert.rejects(stat(fixture.calls), { code: "ENOENT" });
      await assert.rejects(stat(join(fixture.worktree, ".agents/.test-build")), { code: "ENOENT" });
    });
  }
});

test("an explicitly flagged checker still enforces resolved configuration, profiles and canonical skills", async (t) => {
  for (const [name, mutate, error] of [
    ["valid inventory", () => {}, undefined],
    ["wrong primary", responses => { responses["debug config"].default_agent = "other"; }, /Resolved default primary differs/],
    ["downgraded maximum", responses => { responses["debug agent markdown-implementer-max"].variant = "low"; }, /Resolved fixed Astra profile differs/],
    ["noncanonical prototype", responses => { responses["debug skill"].find(skill => skill.name === "prototype").location = "/external/prototype/SKILL.md"; }, /Skill did not resolve to canonical local path: prototype/],
  ]) {
    await t.test(name, async (t) => {
      const fixture = await checkerSetup(t);
      fixture.env.OPENCODE_DISABLE_EXTERNAL_SKILLS = "1";
      mutate(fixture.responses);
      const result = await fixture.check();
      assert.equal(result.error, undefined);
      assert.equal(result.status, error ? 1 : 0, result.stderr);
      if (error) assert.match(result.stderr, error);
      else {
        assert.equal(result.stderr, "");
        assert.match(result.stdout, /Registered openai\/gpt-6-astra: low -> low, max -> max/);
        assert.match(result.stdout, /Resolved skills: all 11 project skills use canonical local paths/);
      }
      const observed = await fixture.observed();
      assert.ok(observed.length > 0);
      assert.ok(observed.every(call => call.flag === "1"));
    });
  }
});
