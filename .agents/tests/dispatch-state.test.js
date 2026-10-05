import assert from "node:assert/strict";
import { test } from "node:test";
import { randomUUID } from "node:crypto";
import { mkdtemp, mkdir, readFile, writeFile, stat, symlink } from "node:fs/promises";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { DispatchJournal, normalizeDispatch, claimsConflict } from "../.test-build/dispatch-state.js";

async function setup() {
  const worktree = await mkdtemp("/tmp/opencode/journal-test-");
  await mkdir(join(worktree, ".agents"));
  const journal = await DispatchJournal.at(worktree);
  const root = join(worktree, ".agents/.dispatch-state");
  const record = { version: 1, dispatchID: randomUUID(), worktree, parentID: "parent", role: "implementation",
    activity: "planning", claims: [{ resource: "plan", mode: "write" }], createdAt: "2026-01-01T00:00:00.000Z", state: "creating" };
  return { worktree, journal, root, record };
}

test("normalization preserves assignment text and validates activity, roles and label boundaries", () => {
  const args = { role: "implementation", title: " title ", prompt: " assignment " };
  assert.deepEqual(normalizeDispatch(args), { ...args, title: "title", profile: "maximum", activity: "legacy-exclusive", claims: [{ resource: "*", mode: "write" }] });
  for (const length of [1, 32]) {
    const claims = Array.from({ length }, (_, i) => ({ resource: `label-${i}`, mode: "read" }));
    assert.equal(normalizeDispatch({ ...args, activity: "planning", claims }).claims.length, length);
  }
  for (const resource of ["a", "*", "a".repeat(96), "plan:one._-1"]) {
    assert.equal(normalizeDispatch({ ...args, activity: "planning", claims: [{ resource, mode: "write" }] }).claims[0].resource, resource);
  }
  for (const resource of ["", "a".repeat(97), " a", "a/b", "a*", "A", "é"]) {
    assert.throws(() => normalizeDispatch({ ...args, activity: "planning", claims: [{ resource, mode: "read" }] }));
  }
  assert.throws(() => normalizeDispatch({ ...args, activity: "planning", claims: Array.from({ length: 33 }, (_, i) => ({ resource: `a${i}`, mode: "read" })) }));
  for (const role of ["implementation", "fix", "verification"]) {
    for (const activity of ["code", "planning", "prototype", "discovery", "review"]) {
      const valid = (["discovery", "review"].includes(activity)) === (role === "verification");
      const action = () => normalizeDispatch({ ...args, role, activity, claims: [{ resource: "a", mode: "read" }] });
      if (valid) assert.equal(action().activity, activity); else assert.throws(action);
    }
  }
});

test("claim conflict is symmetric and does not infer path or prefix aliases", () => {
  const classified = (resource, mode = "read", activity = "planning") => ({ activity, claims: [{ resource, mode }] });
  for (const [a, b, expected] of [
    [classified("x"), classified("x"), false], [classified("x"), classified("x", "write"), true],
    [classified("*"), classified("y", "write"), true], [classified("*"), classified("y"), false],
    [classified("plan", "write"), classified("plan:child", "write"), false],
    [classified("x", "read", "code"), classified("y"), true],
    [classified("x", "read", "legacy-exclusive"), classified("y"), true],
  ]) {
    assert.equal(claimsConflict(a, b), expected);
    assert.equal(claimsConflict(b, a), expected);
  }
});

test("mixed historical and profiled records retain values across all durable states", async () => {
  const { worktree, journal, root, record } = await setup();
  const old = structuredClone(record);
  const current = { ...record, version: 2, dispatchID: randomUUID(), profile: "maximum", activity: "code" };
  await journal.withAdmission(async locked => {
    for (const state of ["creating", "dispatching", "submitted"]) {
      current.state = state;
      if (state !== "creating") current.childID = "new-child";
      await locked.saveRecords([record, current]);
      const restored = await DispatchJournal.at(worktree);
      const bytes = await readFile(join(root, "ledger.json"), "utf8");
      assert.deepEqual(await restored.readRecords(), [old, current]);
      assert.equal(await readFile(join(root, "ledger.json"), "utf8"), bytes);
    }
  });
  assert.equal(Object.hasOwn((await journal.readRecords())[0], "profile"), false);
});

test("profile record versions and unsafe persisted downgrades are rejected without repair", async () => {
  for (const edit of [
    value => { value.profile = "maximum"; },
    value => { value.version = 2; },
    value => { value.version = 2; value.profile = null; },
    value => { value.version = 2; value.profile = "max"; },
    value => { value.version = 3; value.profile = "maximum"; },
    value => { value.version = 2; value.profile = "preparatory"; value.activity = "code"; },
    value => { value.version = 2; value.profile = "preparatory"; value.activity = "legacy-exclusive";
      value.claims = [{ resource: "*", mode: "write" }]; },
  ]) {
    const { journal, root, worktree, record } = await setup();
    await journal.withAdmission(locked => locked.saveRecords([record]));
    edit(record);
    const bytes = JSON.stringify({ version: 1, worktree, records: [record] });
    await writeFile(join(root, "ledger.json"), bytes);
    await assert.rejects(journal.readRecords(), /Invalid dispatch/);
    assert.equal(await readFile(join(root, "ledger.json"), "utf8"), bytes);
  }
});

test("journal persists private validated records across recreation and rejects writes without ownership", async () => {
  const { worktree, journal, root, record } = await setup();
  assert.deepEqual(await journal.readRecords(), []);
  await assert.rejects(journal.saveRecords([record]));
  await journal.withAdmission(async locked => {
    await locked.saveRecords([record]);
    assert.equal((await stat(root)).mode & 0o777, 0o700);
    assert.equal((await stat(join(root, "ledger.json"))).mode & 0o777, 0o600);
    assert.equal((await stat(join(root, "admission.lock"))).mode & 0o777, 0o600);
    record.childID = "child";
    record.state = "submitted";
    await locked.saveRecords([record]);
  });
  const restored = await DispatchJournal.at(worktree);
  assert.deepEqual(await restored.readRecords(), [record]);
  await assert.rejects(restored.saveRecords([record]));
  await assert.rejects(stat(join(root, "admission.lock")), { code: "ENOENT" });
});

test("invalid records, versions, duplicates and crash artifacts are never reset", async () => {
  const mutations = [
    ledger => { ledger.version = 2; }, ledger => { ledger.extra = true; },
    ledger => { ledger.worktree = "/wrong"; }, ledger => { ledger.records[0].worktree = "/wrong"; },
    ledger => { ledger.records[0].dispatchID = "../path"; }, ledger => { ledger.records[0].createdAt = "yesterday"; },
    ledger => { ledger.records[0].childID = "child"; }, ledger => { ledger.records[0].state = "submitted"; },
    ledger => { ledger.records[0].state = "done"; }, ledger => { ledger.records[0].extra = "secret"; },
    ledger => { ledger.records[0].state = ["submitted"]; ledger.records[0].childID = "child"; },
    ledger => { ledger.records[0].claims = []; }, ledger => { ledger.records[0].activity = "unknown"; },
    ledger => { ledger.records.push({ ...ledger.records[0] }); },
    ledger => { ledger.records[0].state = "submitted"; ledger.records[0].childID = "child";
      ledger.records.push({ ...ledger.records[0], dispatchID: randomUUID() }); },
    ledger => { ledger.records[0].activity = "legacy-exclusive"; },
  ];
  for (const mutate of mutations) {
    const { journal, worktree, root, record } = await setup();
    await journal.withAdmission(locked => locked.saveRecords([record]));
    const ledger = { version: 1, worktree, records: [record] };
    mutate(ledger);
    const original = JSON.stringify(ledger);
    await writeFile(join(root, "ledger.json"), original);
    await assert.rejects(journal.withAdmission(async () => assert.fail("must not admit")), /Invalid dispatch/);
    assert.equal(await readFile(join(root, "ledger.json"), "utf8"), original);
  }
  const { journal, root } = await setup();
  await journal.withAdmission(async () => {});
  await writeFile(join(root, "ledger-abandoned.tmp"), "interrupted", { mode: 0o600 });
  await assert.rejects(journal.withAdmission(async () => assert.fail("must not admit")), /Invalid dispatch/);
  assert.equal(await readFile(join(root, "ledger-abandoned.tmp"), "utf8"), "interrupted");
});

test("symlinked state components and files are rejected without touching targets", async () => {
  for (const component of [".agents", ".dispatch-state", "ledger.json"]) {
    const worktree = await mkdtemp("/tmp/opencode/symlink-test-");
    const target = await mkdtemp("/tmp/opencode/symlink-target-");
    if (component === ".agents") {
      await symlink(target, join(worktree, ".agents"));
      await assert.rejects(DispatchJournal.at(worktree));
      continue;
    }
    await mkdir(join(worktree, ".agents"));
    const root = join(worktree, ".agents/.dispatch-state");
    if (component === ".dispatch-state") await symlink(target, root);
    else {
      await mkdir(root, { mode: 0o700 });
      await writeFile(join(target, "private"), "untouched", { mode: 0o600 });
      await symlink(join(target, "private"), join(root, "ledger.json"));
    }
    const journal = await DispatchJournal.at(worktree);
    await assert.rejects(journal.withAdmission(async () => assert.fail("must not admit")));
    if (component === "ledger.json") assert.equal(await readFile(join(target, "private"), "utf8"), "untouched");
  }
});

test("release never removes a lock whose token changed", async () => {
  const { journal, root } = await setup();
  await assert.rejects(journal.withAdmission(async () => {
    await writeFile(join(root, "admission.lock"), JSON.stringify({ version: 1, token: "another-owner", startedAt: "2026-01-01T00:00:00.000Z" }));
  }), /Invalid dispatch/);
  assert.match(await readFile(join(root, "admission.lock"), "utf8"), /another-owner/);
  await assert.rejects(journal.withAdmission(async () => {}), /admission-busy/);
});

test("a separate process owns admission and a crash-held lock is never stolen", async () => {
  const { journal, worktree, root } = await setup();
  const module = new URL("../.test-build/dispatch-state.js", import.meta.url).href;
  const script = `import { DispatchJournal } from ${JSON.stringify(module)};
    const journal = await DispatchJournal.at(${JSON.stringify(worktree)});
    await journal.withAdmission(async () => {
      process.send('locked');
      await new Promise(resolve => process.on('message', message => {
        if (message === 'crash') process.exit(7);
        if (message === 'release') resolve();
      }));
    }); process.disconnect();`;
  for (const command of ["release", "crash"]) {
    const child = spawn(process.execPath, ["--input-type=module", "-e", script], { stdio: ["ignore", "pipe", "pipe", "ipc"] });
    const exited = once(child, "exit");
    const message = await Promise.race([once(child, "message"), exited.then(() => { throw new Error("lock holder exited before handshake"); })]);
    assert.equal(message[0], "locked");
    const lock = await readFile(join(root, "admission.lock"), "utf8");
    await assert.rejects(journal.withAdmission(async () => assert.fail("must not admit")), /admission-busy/);
    assert.equal(await readFile(join(root, "admission.lock"), "utf8"), lock);
    child.send(command);
    assert.equal((await exited)[0], command === "crash" ? 7 : 0);
    if (command === "release") await journal.withAdmission(async () => {});
    else {
      await assert.rejects(journal.withAdmission(async () => {}), /admission-busy/);
      assert.equal(await readFile(join(root, "admission.lock"), "utf8"), lock);
    }
  }
});
