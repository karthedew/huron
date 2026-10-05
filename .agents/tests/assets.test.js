import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { dispatchIssues, inspectAssets, modelVariantIssues, normalizedPermissionRules, registrationIssues, root, skills } from "../scripts/check-assets.mjs";

const load = name => JSON.parse(readFileSync(resolve(root, name), "utf8"));

test("canonical assets resolve without local roadmap files or installed frontend dependencies", () => {
  assert.deepEqual(inspectAssets(), []);
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

test("fixed maximum agents require exact effort, identity, prompts and permission parity", () => {
  for (const mutate of [
    config => { delete config.agent["markdown-implementer-max"]; },
    config => { config.agent["markdown-extra"] = config.agent["markdown-implementer"]; },
    config => { config.agent["markdown-implementer-max"].variant = "xhigh"; },
    config => { config.agent["markdown-implementer-max"].options.reasoningEffort = "low"; },
    config => { config.agent["markdown-implementer-max"].model = "openai/other"; },
    config => { config.agent["markdown-reviewer-max"].mode = "primary"; },
    config => { config.agent["markdown-reviewer-max"].prompt = "custom prompt"; },
    config => { config.agent["markdown-reviewer-max"].permission.edit = "allow"; },
    config => { config.agent["markdown-implementer-max"].permission.bash = "allow"; },
    config => { config.agent["markdown-reviewer-max"].permission.implementation_start = "allow"; },
  ]) {
    const config = load("opencode.json");
    mutate(config);
    assert.ok(registrationIssues(config, load("skills-lock.json"), skills, () => true).length > 0);
  }
});

test("registered variant checks reject absent, disabled and mismatched maximum capability", () => {
  const baseline = { id: "gpt-6-astra", providerID: "openai", variants: {
    low: { reasoningEffort: "low" }, max: { reasoningEffort: "max", disabled: false },
  } };
  assert.deepEqual(modelVariantIssues(baseline), []);
  for (const mutate of [model => { model.id = "other"; }, model => { model.providerID = "other"; },
    model => { delete model.variants; }, model => { delete model.variants.max; },
    model => { model.variants.max = []; }, model => { model.variants.max.reasoningEffort = "xhigh"; },
    model => { model.variants.max.disabled = true; }, model => { model.variants.max.disabled = "false"; }]) {
    const model = structuredClone(baseline);
    mutate(model);
    assert.ok(modelVariantIssues(model).length > 0);
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
