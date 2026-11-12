import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { closeSync, mkdirSync, mkdtempSync, openSync, readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { discoveryIssues, lifecycle, modelVariantIssues, normalizedPermissionRules, requiredSkills, resolvedPluginIssues, root, skillLocations, skillPaths, sourcePath, workflowAgents } from "./check-assets.mjs";

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
  const discovery = discoveryIssues(root);
  assert.ok(discovery.length === 0, discovery.join("; "));
  const config = debug(["config"]);
  assert.ok(JSON.stringify((config.skills?.paths ?? []).map(path => sourcePath(path)).sort()) ===
    JSON.stringify(skillPaths.map(path => sourcePath(path)).sort()) && !config.skills?.urls?.length,
    "Resolved skill sources must be exactly the approved explicit directories. Preserve explicit source registrations");
  const plugins = resolvedPluginIssues(config);
  assert.ok(plugins.length === 0, plugins.join("; "));
  assert.ok(config.default_agent === "markdown-orchestrator", "Resolved default primary differs");
  for (const name of lifecycle) {
    assert.ok(config.command?.[name]?.agent === "markdown-orchestrator", `Resolved command agent differs: ${name}`);
    assert.ok(config.command[name].template.trim() === readFileSync(resolve(root, `.agents/commands/${name}.md`), "utf8").trim(),
      `Resolved command is not canonical: ${name}`);
  }
  for (const name of ["architectural-review", "execute_plan"]) {
    assert.ok(!config.command?.[name], `Retired inherited command remains: ${name}`);
  }
  assert.ok(config.command["implement-markdown"].model === "openai/gpt-6-astra" &&
    config.command["implement-markdown"].variant === "low", "Resolved implementation command profile differs");
  console.log("Resolved config: one canonical dispatcher, canonical lifecycle, default orchestrator, retired competing commands absent");

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
    for (const skill of [...requiredSkills, "customize-opencode"]) {
      assert.ok(action(agent, "skill", skill) === "allow", `Required skill denied: ${name}/${skill}`);
    }
    for (const skill of ["*", ...lifecycle, "wayfinder", "to-spec", "to-tickets", "grilling", "code-review", "asd=ste100", "unknown-skill"]) {
      assert.ok(action(agent, "skill", skill) === "deny", `Rejected global skill allowed: ${name}/${skill}`);
    }
    if (effort !== "low") {
      const counterpart = resolved.get(`markdown-${role}`);
      assert.ok(agent.prompt === counterpart.prompt &&
        JSON.stringify(normalizedPermissionRules(agent.permission)) === JSON.stringify(normalizedPermissionRules(counterpart.permission)),
        `Resolved profile counterpart prompt/permissions differ: ${name}`);
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
  console.log("Registered openai/gpt-6-astra: low -> low, medium -> medium, max -> max. Provider acceptance remains not proven");

  const inventory = debug(["skill"]);
  assert.ok(Array.isArray(inventory), "Unexpected resolved skill inventory shape");
  for (const [name, location] of Object.entries(skillLocations())) {
    const matches = inventory.filter(item => item.name === name);
    assert.ok(matches.length === 1 && matches[0].location === location,
      `Skill did not resolve to approved source: ${name}. Supply ${location}. Then restart OpenCode`);
  }
  console.log(`Resolved skills: all ${requiredSkills.length} required skills use approved explicit sources. Unrelated external skills are permitted in discovery`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  // Remove only this invocation's private temporary diagnostics, never user data.
  rmSync(scratch, { recursive: true });
}
