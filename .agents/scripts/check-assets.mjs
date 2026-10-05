import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const root = fileURLToPath(new URL("../../", import.meta.url));
export const lifecycle = ["design-plan", "prototype", "implementation-plan", "implement-markdown"];
export const capabilities = [
  "oop-design", "fastapi", "postgresql-table-design", "svelte-code-writer",
  "svelte-core-bestpractices", "tailwind-design-system", "playwright-cli",
];
export const skills = [...capabilities, ...lifecycle].sort();
export const workflowAgents = {
  "markdown-orchestrator": { role: "orchestrator", effort: "low" },
  "markdown-implementer": { role: "implementer", effort: "low" },
  "markdown-reviewer": { role: "reviewer", effort: "low" },
  "markdown-implementer-max": { role: "implementer", effort: "max" },
  "markdown-reviewer-max": { role: "reviewer", effort: "max" },
};

export function modelVariantIssues(model) {
  const issues = [];
  if (model?.id !== "gpt-6-astra" || model?.providerID !== "openai") issues.push("Registered Astra identity differs");
  for (const effort of ["low", "max"]) {
    const variant = model?.variants?.[effort];
    if (!variant || Array.isArray(variant) || variant.reasoningEffort !== effort ||
        (variant.disabled !== undefined && variant.disabled !== false)) {
      issues.push(`Registered Astra ${effort} mapping is unavailable`);
    }
  }
  return issues;
}

// Discovery order can vary for adjacent inherited allow rules. Only same-action,
// same-permission neighbors commute; never sort across an action/permission boundary.
export function normalizedPermissionRules(rules) {
  const blocks = [];
  for (const rule of rules) {
    const last = blocks.at(-1);
    if (last && last[0].permission === rule.permission && last[0].action === rule.action) last.push(rule);
    else blocks.push([rule]);
  }
  return blocks.flatMap(block => [...block].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
}

export function registrationIssues(config, lock, available, exists) {
  const issues = [];
  const check = (condition, message) => { if (!condition) issues.push(message); };
  const same = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
  check(same(available, skills), "Local skill inventory differs from the retained capability/lifecycle set");
  check(same(config.skills?.paths ?? [], [".agents/skills"]), "Skills must use only the canonical local path");
  check(!config.skills?.urls?.length, "Project skills must not depend on remote skill URLs");
  const rules = config.permission?.skill ?? {};
  check(Object.keys(rules)[0] === "*" && rules["*"] === "deny", "Skill rules must begin with deny-all");
  check(same(Object.keys(rules), ["*", ...skills, "customize-opencode"]), "Skill allowlist differs from retained skills and built-in config skill");
  for (const name of [...skills, "customize-opencode"]) {
    check(rules[name] === "allow", `Required skill is not allowed: ${name}`);
  }
  for (const name of Object.keys(lock.skills ?? {})) {
    check(skills.includes(name), `Obsolete skill lock entry: ${name}`);
  }
  check(same(Object.keys(config.command ?? {}), lifecycle), "Project commands must be exactly the four lifecycle commands");
  for (const name of lifecycle) {
    const command = config.command?.[name];
    check(command?.agent === "markdown-orchestrator", `Command must use orchestrator: ${name}`);
    check(command?.template === `{file:./.agents/commands/${name}.md}`, `Command body must be canonical: ${name}`);
  }
  check(config.default_agent === "markdown-orchestrator", "Default primary must be the orchestrator");
  check(config.agent?.[config.default_agent]?.mode === "primary", "Default agent must have primary mode");
  check(same(Object.keys(config.agent ?? {}).filter(name => name.startsWith("markdown-")), Object.keys(workflowAgents)),
    "Workflow agents must be exactly the five fixed Astra agents");
  for (const [name, { role, effort }] of Object.entries(workflowAgents)) {
    const agent = config.agent?.[name];
    check(agent?.model === "openai/gpt-6-astra" && agent.variant === effort &&
      agent.options?.reasoningEffort === effort, `Fixed Astra profile configuration drift: ${name}`);
    check(agent?.mode === (role === "orchestrator" ? "primary" : "subagent"), `Workflow mode differs: ${name}`);
    check(agent?.prompt === `{file:./.agents/prompts/${role}.md}`, `Workflow prompt differs: ${name}`);
    check(agent?.permission?.task === "deny", `Blocking/nested Task must be denied: ${name}`);
    if (role !== "orchestrator") {
      check(agent?.permission?.implementation_start === "deny", `Worker delegation must be denied: ${name}`);
    }
    if (role === "reviewer") check(agent?.permission?.edit === "deny", `Reviewer edit must be denied: ${name}`);
    if (effort === "max") check(JSON.stringify(agent?.permission) === JSON.stringify(config.agent?.[`markdown-${role}`]?.permission),
      `Maximum counterpart permissions differ: ${name}`);
  }
  check(config.agent?.["markdown-reviewer"]?.permission?.edit === "deny", "Reviewer edit must be denied");
  check(config.plugin?.includes("./.agents/plugins/implementation.ts"), "Dispatch plugin registration must remain canonical");
  for (const match of JSON.stringify(config).matchAll(/\{file:([^}]+)\}/g)) {
    check(exists(match[1]), `Missing config file reference: ${match[1]}`);
  }
  return issues;
}

export function dispatchIssues(read) {
  const issues = [];
  const contracts = [
    ".agents/README.md", ".agents/workflows/orchestration.md", ".agents/workflows/implement-markdown.md",
    ".agents/workflows/verification.md", ".agents/templates/assignment.md", ".agents/templates/design-plan.md",
    ".agents/templates/prototype.md", ".agents/templates/phase-plan.md",
    ...lifecycle.map(name => `.agents/skills/${name}/SKILL.md`),
  ];
  for (const path of contracts) {
    const text = read(path);
    for (const [pattern, label] of [[/activity/, "activity"], [/claims/, "claims"], [/profile/, "profile"], [/maximum/, "maximum policy"], [/check-output|check\s+output/, "check-output ownership"], [/not a\s+sandbox/, "cooperative boundary"]]) {
      if (!pattern.test(text)) issues.push(`Missing dispatch ${label}: ${path}`);
    }
    if (/plugin serializes all|one writer\/reviewer is active/.test(text)) issues.push(`Obsolete blanket exclusion: ${path}`);
  }
  const orchestration = read(".agents/workflows/orchestration.md");
  for (const [pattern, label] of [[/Actual code is exclusive against ALL/, "code exclusion"],
    [/legacy-exclusive/, "legacy default"], [/15 minutes/, "progress interval"],
    [/once per minute/, "polling interval"], [/actual-last-response|actual-last-assistant/, "terminal separation"],
    [/human authorization/, "recovery authorization"], [/Quit and restart OpenCode/, "restart"]]) {
    if (!pattern.test(orchestration)) issues.push(`Missing dispatch ${label}: orchestration`);
  }
  for (const name of ["implementer", "reviewer"]) {
    const text = read(`.agents/prompts/${name}.md`);
    if (!/claims/.test(text) || !/classification/.test(text) || !/credentials in progress/.test(text)) {
      issues.push(`Missing worker ownership/progress protections: ${name}`);
    }
  }
  return issues;
}

export function inspectAssets(directory = root) {
  const issues = [];
  const files = [];
  function walk(path) {
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) {
      issues.push(`Canonical asset is a symlink: ${relative(directory, path)}`);
    } else if (stat.isDirectory()) {
      for (const name of readdirSync(path)) walk(resolve(path, name));
    } else files.push(path);
  }
  for (const path of [".agents/commands", ".agents/prompts", ".agents/workflows", ".agents/templates", ".agents/skills", "docs/agents"]) {
    walk(resolve(directory, path));
  }
  files.push(resolve(directory, "AGENTS.md"), resolve(directory, ".agents/README.md"));
  const available = files.filter(path => path.endsWith("/SKILL.md")).map(path => {
    const name = relative(resolve(directory, ".agents/skills"), path).split("/")[0];
    const body = readFileSync(path, "utf8");
    if (!body.startsWith("---\n") || !body.includes(`\nname: ${name}\n`) || !/^description: .+/m.test(body)) {
      issues.push(`Invalid skill frontmatter: ${name}`);
    }
    return name;
  });
  const config = JSON.parse(readFileSync(resolve(directory, "opencode.json"), "utf8"));
  const lock = JSON.parse(readFileSync(resolve(directory, "skills-lock.json"), "utf8"));
  issues.push(...registrationIssues(config, lock, available, path => existsSync(resolve(directory, path))));
  issues.push(...dispatchIssues(path => readFileSync(resolve(directory, path), "utf8")));
  for (const name of ["assignment", "design-plan", "prototype", "phase-plan"]) {
    if (!existsSync(resolve(directory, `.agents/templates/${name}.md`))) issues.push(`Missing reusable template: ${name}`);
  }
  for (const path of files.filter(path => path.endsWith(".md"))) {
    const body = readFileSync(path, "utf8");
    const label = relative(directory, path);
    for (const match of body.matchAll(/\[[^\]\n]*\]\(([^)\s]+)\)/g)) {
      const target = match[1].split("#")[0];
      if (!target || /^[a-z]+:/i.test(target)) continue;
      if (!existsSync(resolve(dirname(path), target))) issues.push(`Broken local link: ${label} -> ${target}`);
    }
    for (const match of body.matchAll(/`(\.agents\/(?:commands|skills|workflows|templates|prompts)\/[^`]+)`/g)) {
      if (/[<>*]/.test(match[1])) continue;
      if (!existsSync(resolve(directory, match[1]))) issues.push(`Broken asset path: ${label} -> ${match[1]}`);
    }
    if (/svelte-file-editor|\.claude\/skills|~\/\.agents\/skills/.test(body)) {
      issues.push(`Unavailable agent or home-skill dependency: ${label}`);
    }
    if (/\S[ \t]+$/m.test(body)) issues.push(`Trailing whitespace: ${label}`);
  }
  for (const folder of ["plugins", "tests", "scripts"]) {
    for (const name of readdirSync(resolve(directory, `.agents/${folder}`))) {
      if (!/\.(ts|js|mjs)$/.test(name)) continue;
      const body = readFileSync(resolve(directory, `.agents/${folder}`, name), "utf8");
      if (/[ \t]+$/m.test(body) || !body.endsWith("\n")) issues.push(`Invalid text whitespace: .agents/${folder}/${name}`);
    }
  }
  return issues;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const issues = inspectAssets();
  for (const issue of issues) console.error(issue);
  if (issues.length) process.exitCode = 1;
  else console.log(`Agent assets: ${skills.length} canonical skills, four commands, templates and local references OK`);
}
