import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { spawnSync } from "node:child_process";
import { discoveryIssues, dispatchIssues, inspectAssets, modelVariantIssues, normalizedPermissionRules, registrationIssues, root, skills, skillLocations, sourcePath, trackedArtifactIssues } from "../scripts/check-assets.mjs";

const load = name => JSON.parse(readFileSync(resolve(root, name), "utf8"));

test("canonical assets resolve without local roadmap files or installed frontend dependencies", () => {
  assert.deepEqual(inspectAssets(), []);
});

test("runtime journals, recovery archives and compiled checks cannot enter version control", () => {
  const source = [".agents/plugins/dispatch-state.ts", ".agents/tests/dispatch-state.test.js", ".agents/.gitignore"];
  const generated = [".agents/.dispatch-state/ledger.json", ".agents/.dispatch-state/admission.lock",
    ".agents/.dispatch-archive/recovery/ledger.json", ".agents/.test-build/implementation.js", "roadmap/plans/probe.md"];
  assert.deepEqual(trackedArtifactIssues([]), []);
  assert.deepEqual(trackedArtifactIssues(source), []);
  assert.deepEqual(trackedArtifactIssues([...source, ...generated]),
    generated.map(path => `Agent runtime artifact must not be tracked: ${path}`));
});

test("roadmaps and normal tooling output remain ignored without hiding source files", () => {
  for (const path of ["roadmap/", "roadmap/plans/probe.md", ".agents/.test-build/implementation.js",
    ".agents/.dispatch-state/ledger.json", ".agents/.dispatch-state/admission.lock", ".agents/.dispatch-archive/recovery/ledger.json"]) {
    const result = spawnSync("git", ["check-ignore", "-v", "--", path], { cwd: root, encoding: "utf8" });
    assert.equal(result.status, 0, path);
    assert.ok(result.stdout.includes(path));
  }
  const tracked = spawnSync("git", ["ls-files", "--", "roadmap"], { cwd: root, encoding: "utf8" });
  assert.equal(tracked.status, 0);
  assert.equal(tracked.stdout, "");
  const source = spawnSync("git", ["check-ignore", "--no-index", "--", ".agents/plugins/implementation.ts"], { cwd: root });
  assert.equal(source.status, 1);
});

test("only approved narrow skill sources and names are permitted with portable home resolution", () => {
  const config = load("opencode.json");
  const lock = load("skills-lock.json");
  assert.deepEqual(registrationIssues(config, lock, skills, () => true), []);
  assert.equal(sourcePath("~/.agents/skills/writing-for-agents/SKILL.md", "/project", "/another-home"),
    "/another-home/.agents/skills/writing-for-agents/SKILL.md");
  const locations = skillLocations("/project", "/another-home");
  assert.equal(locations["writing-for-agents"], "/another-home/.agents/skills/writing-for-agents/SKILL.md");
  assert.equal(locations["asd-ste100"], "/project/.claude/skills/asd-ste100/SKILL.md");
  assert.equal(locations["huron-prototype"], "/project/.agents/skills/huron-prototype/SKILL.md");
  for (const path of ["~/.agents/skills", "~/.claude/skills", ".claude/skills", "/home/other/skills"]) {
    const changed = structuredClone(config);
    changed.skills.paths.push(path);
    assert.ok(registrationIssues(changed, lock, skills, () => true).some(issue => issue.includes("explicit source directories")));
  }
  for (const name of ["writing-for-agents", "asd-ste100"]) {
    const missing = registrationIssues(config, lock, skills, path => !path.includes(name));
    assert.ok(missing.some(issue => issue.includes(`Required skill source missing: ${name}`) && issue.includes("restart")));
    const denied = structuredClone(config);
    denied.permission.skill[name] = "deny";
    assert.ok(registrationIssues(denied, lock, skills, () => true).includes(`Required skill is not allowed: ${name}`));
  }
  for (const name of ["asd=ste100", "unknown-skill", "design-plan", "prototype", "implementation-plan", "implement-markdown"]) {
    const changed = structuredClone(config);
    changed.permission.skill[name] = "allow";
    assert.ok(registrationIssues(changed, lock, skills, () => true).some(issue => issue.includes("allowlist")));
  }
});

test("auto-discovery rejects legacy plugins and lifecycle commands but permits unrelated assets", async (t) => {
  for (const folder of ["plugin", "plugins", "command", "commands"]) {
    const names = folder.startsWith("plugin") ? ["implementation.ts", "implementation.js"]
      : ["design-plan.md", "prototype.md", "implementation-plan.md", "implement-markdown.md"];
    for (const name of names) await t.test(`${folder}/${name}`, (t) => {
      const directory = mkdtempSync("/tmp/opencode/asset-discovery-");
      t.after(() => rmSync(directory, { recursive: true }));
      const target = resolve(directory, ".opencode", folder);
      mkdirSync(target, { recursive: true });
      writeFileSync(resolve(target, folder.startsWith("plugin") ? "unrelated.ts" : "unrelated.md"), "unrelated\n");
      assert.deepEqual(discoveryIssues(directory), []);
      writeFileSync(resolve(target, name), "legacy\n");
      assert.deepEqual(discoveryIssues(directory), [
        `Legacy auto-discovered registration overrides canonical assets: .opencode/${folder}/${name}`,
      ]);
    });
  }
});

test("registration rejects global skill permission drift and obsolete lock entries", () => {
  const config = load("opencode.json");
  config.permission.skill["wayfinder"] = "allow";
  const lock = load("skills-lock.json");
  lock.skills["wayfinder"] = { source: "obsolete" };
  const issues = registrationIssues(config, lock, skills, () => true);
  assert.ok(issues.some(issue => issue.includes("allowlist")));
  assert.ok(issues.some(issue => issue.includes("Obsolete skill lock entry: wayfinder")));
});

test("registration rejects broken command bodies, wrong dispatch and missing prompt files", () => {
  const config = load("opencode.json");
  config.command.prototype.agent = "build";
  config.command.prototype.template = "{file:./missing.md}";
  const issues = registrationIssues(config, load("skills-lock.json"), skills, path => !path.includes("missing"));
  assert.ok(issues.some(issue => issue.includes("Command must use orchestrator: prototype")));
  assert.ok(issues.some(issue => issue.includes("Command body must be canonical: prototype")));
  assert.ok(issues.some(issue => issue.includes("Missing config file reference")));
});

test("registration rejects missing local skills and reviewer permission weakening", () => {
  const config = load("opencode.json");
  config.agent["markdown-reviewer"].permission.edit = "allow";
  config.agent["markdown-reviewer"].permission.implementation_start = "allow";
  const issues = registrationIssues(config, load("skills-lock.json"), skills.filter(name => name !== "playwright-cli"), () => true);
  assert.ok(issues.some(issue => issue.includes("Local skill inventory")));
  assert.ok(issues.some(issue => issue.includes("Reviewer edit must be denied")));
  assert.ok(issues.some(issue => issue.includes("Worker delegation must be denied")));
});

test("fixed medium and maximum agents require exact effort, identity, prompts and permission parity", () => {
  for (const suffix of ["medium", "max"]) {
    for (const mutate of [
      config => { delete config.agent[`markdown-implementer-${suffix}`]; },
      config => { config.agent["markdown-extra"] = config.agent["markdown-implementer"]; },
      config => { config.agent[`markdown-implementer-${suffix}`].variant = "xhigh"; },
      config => { config.agent[`markdown-implementer-${suffix}`].options.reasoningEffort = "low"; },
      config => { config.agent[`markdown-implementer-${suffix}`].model = "openai/other"; },
      config => { config.agent[`markdown-reviewer-${suffix}`].mode = "primary"; },
      config => { config.agent[`markdown-reviewer-${suffix}`].prompt = "custom prompt"; },
      config => { config.agent[`markdown-reviewer-${suffix}`].permission.edit = "allow"; },
      config => { config.agent[`markdown-implementer-${suffix}`].permission.bash = "allow"; },
      config => { config.agent[`markdown-reviewer-${suffix}`].permission.implementation_start = "allow"; },
    ]) {
      const config = load("opencode.json");
      mutate(config);
      assert.ok(registrationIssues(config, load("skills-lock.json"), skills, () => true).length > 0);
    }
  }
});

test("registered variant checks reject absent, disabled and mismatched capabilities", () => {
  const baseline = { id: "gpt-6-astra", providerID: "openai", variants: {
    low: { reasoningEffort: "low" }, medium: { reasoningEffort: "medium" }, max: { reasoningEffort: "max", disabled: false },
  } };
  assert.deepEqual(modelVariantIssues(baseline), []);
  for (const effort of ["low", "medium", "max"]) {
    for (const mutate of [model => { model.id = "other"; }, model => { model.providerID = "other"; },
      model => { delete model.variants; }, model => { delete model.variants[effort]; },
      model => { model.variants[effort] = []; }, model => { model.variants[effort].reasoningEffort = "xhigh"; },
      model => { model.variants[effort].disabled = true; }, model => { model.variants[effort].disabled = "false"; }]) {
      const model = structuredClone(baseline);
      mutate(model);
      assert.ok(modelVariantIssues(model).length > 0);
    }
  }
});

test("resolved permission comparison permits only commuting same-action neighbors", () => {
  const rules = [
    { permission: "external_directory", pattern: "*", action: "ask" },
    { permission: "external_directory", pattern: "/a/*", action: "allow" },
    { permission: "external_directory", pattern: "/b/*", action: "allow" },
    { permission: "external_directory", pattern: "/a/private/*", action: "deny" },
    { permission: "edit", pattern: "*", action: "deny" },
  ];
  const original = structuredClone(rules);
  assert.deepEqual(normalizedPermissionRules(rules), normalizedPermissionRules([rules[0], rules[2], rules[1], rules[3], rules[4]]));
  assert.deepEqual(rules, original);
  for (const changed of [
    [rules[0], rules[3], rules[1], rules[2], rules[4]],
    [...rules, { permission: "external_directory", pattern: "/a/private/*", action: "allow" }],
    rules.map((rule, i) => i === 3 ? { ...rule, action: "allow" } : rule),
    rules.map((rule, i) => i === 1 ? { ...rule, pattern: "/extra/*" } : rule),
    rules.slice(0, -1),
  ]) assert.notDeepEqual(normalizedPermissionRules(rules), normalizedPermissionRules(changed));
});

test("dispatch documentation checks reject missing ownership, progress and recovery rules", () => {
  const read = path => readFileSync(resolve(root, path), "utf8");
  assert.deepEqual(dispatchIssues(read), []);
  const issues = dispatchIssues(path => path === ".agents/workflows/orchestration.md" ? "plugin serializes all children" : read(path));
  for (const required of ["activity", "claims", "progress interval", "polling interval", "terminal separation", "recovery authorization", "restart", "Obsolete blanket exclusion"]) {
    assert.ok(issues.some(issue => issue.includes(required)), required);
  }
  const config = load("opencode.json");
  config.plugin = [];
  assert.ok(registrationIssues(config, load("skills-lock.json"), skills, () => true).some(issue => issue.includes("plugin registration")));
});
