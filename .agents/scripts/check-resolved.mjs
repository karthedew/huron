import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { closeSync, mkdirSync, mkdtempSync, openSync, readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { lifecycle, modelVariantIssues, normalizedPermissionRules, root, skills, workflowAgents } from "./check-assets.mjs";

if (process.env.OPENCODE_DISABLE_EXTERNAL_SKILLS !== "1") {
  console.error("Resolved checks require OPENCODE_DISABLE_EXTERNAL_SKILLS=1 before invoking OpenCode. " +
    "Quit/restart the serving process from the repository root with sh .agents/scripts/opencode-project.sh; " +
    "a flagged attached client is insufficient. From .agents/, run " +
    "OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs (fresh CLI only, not serving-process verification).");
  process.exit(1);
}

// OpenCode can exit before large pipe writes drain. A private regular file also
// keeps raw resolved provider configuration out of terminal/log output.
const build = resolve(root, ".agents/.test-build");
mkdirSync(build, { recursive: true });
const scratch = mkdtempSync(resolve(build, "resolved-"));
function capture(args) {
  const path = resolve(scratch, "output.json");
  const fd = openSync(path, "w", 0o600);
  let result;
  try {
    result = spawnSync("opencode", args, {
      cwd: root, stdio: ["ignore", fd, "pipe"], timeout: 60_000,
    });
  } finally {
    closeSync(fd);
  }
  assert.ok(result.status === 0 && !result.error, `OpenCode ${args[0]} failed; raw diagnostics withheld`);
  return readFileSync(path, "utf8");
}

function debug(args) {
  try { return JSON.parse(capture(["debug", ...args])); }
  catch { throw new Error(`OpenCode debug ${args[0]} failed or did not produce complete JSON; raw output withheld`); }
}

function action(agent, permission, pattern = "*") {
  return agent.permission.filter(rule =>
    (rule.permission === permission || rule.permission === "*") &&
    (rule.pattern === "*" || rule.pattern === pattern)).at(-1)?.action;
}

try {
  const config = debug(["config"]);
  assert.ok(config.default_agent === "markdown-orchestrator", "Resolved default primary differs");
  for (const name of lifecycle) {
    assert.ok(config.command?.[name]?.agent === "markdown-orchestrator", `Resolved command agent differs: ${name}`);
    assert.ok(config.command[name].template.trim() === readFileSync(resolve(root, `.agents/commands/${name}.md`), "utf8").trim(),
      `Resolved command is not canonical: ${name}`);
  }
  for (const name of ["architectural-review", "execute_plan"]) {
    assert.ok(!config.command?.[name], `Retired inherited command remains: ${name}`);
  }
  console.log("Resolved config: canonical lifecycle, default orchestrator, retired competing commands absent");

  const resolved = new Map();
  for (const [name, { role, effort }] of Object.entries(workflowAgents)) {
    const agent = debug(["agent", name]);
    assert.ok(agent.model?.providerID === "openai" && agent.model.modelID === "gpt-6-astra" &&
      agent.variant === effort && agent.options?.reasoningEffort === effort, `Resolved fixed Astra profile differs: ${name}`);
    assert.ok(agent.mode === (role === "orchestrator" ? "primary" : "subagent"), `Resolved agent mode differs: ${name}`);
    assert.ok(agent.prompt.trim() === readFileSync(resolve(root, `.agents/prompts/${role}.md`), "utf8").trim(),
      `Resolved prompt is not canonical: ${name}`);
    assert.ok(action(agent, "task") === "deny", `Task permission differs: ${name}`);
    if (role !== "orchestrator") assert.ok(action(agent, "implementation_start") === "deny", `Worker can delegate: ${name}`);
    if (role === "reviewer") assert.ok(action(agent, "edit") === "deny", "Reviewer can edit");
    for (const skill of [...skills, "customize-opencode"]) {
      assert.ok(action(agent, "skill", skill) === "allow", `Required skill denied: ${name}/${skill}`);
    }
    for (const skill of ["wayfinder", "to-spec", "to-tickets", "grilling", "code-review", "writing-for-agents", "unknown-skill"]) {
      assert.ok(action(agent, "skill", skill) === "deny", `Rejected global skill allowed: ${name}/${skill}`);
    }
    if (effort === "max") {
      const counterpart = resolved.get(`markdown-${role}`);
      assert.ok(agent.prompt === counterpart.prompt &&
        JSON.stringify(normalizedPermissionRules(agent.permission)) === JSON.stringify(normalizedPermissionRules(counterpart.permission)),
        `Resolved maximum counterpart prompt/permissions differ: ${name}`);
    }
    resolved.set(name, agent);
    console.log(`Resolved ${name}: canonical prompt, Astra ${effort} and bounded permissions OK`);
  }

  const listing = capture(["models", "openai", "--verbose"]);
  const entry = listing.match(/(?:^|\n)openai\/gpt-6-astra\r?\n([\s\S]*?)(?=\nopenai\/[^\n]+\n|$)/);
  let astra;
  try { astra = JSON.parse(entry?.[1] ?? ""); }
  catch { throw new Error("Registered Astra metadata could not be parsed; raw output withheld"); }
  const modelIssues = modelVariantIssues(astra);
  assert.ok(modelIssues.length === 0, modelIssues.join("; "));
  console.log("Registered openai/gpt-6-astra: low -> low, max -> max; provider acceptance not proven");

  const inventory = debug(["skill"]);
  assert.ok(Array.isArray(inventory), "Unexpected resolved skill inventory shape");
  for (const name of skills) {
    const skill = inventory.find(item => item.name === name);
    assert.ok(skill?.location === resolve(root, `.agents/skills/${name}/SKILL.md`),
      `Skill did not resolve to canonical local path: ${name}`);
  }
  console.log(`Resolved skills: all ${skills.length} project skills use canonical local paths`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  // Remove only this invocation's private temporary diagnostics, never user data.
  rmSync(scratch, { recursive: true });
}
