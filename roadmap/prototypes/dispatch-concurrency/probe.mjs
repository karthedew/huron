// Throwaway experiment. Never imported by the live plugin; no model/server calls.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdir, mkdtemp, open, readFile, rename, unlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { createOpencodeClient } from '../../../.agents/node_modules/@opencode-ai/sdk/dist/index.js';
const home = fileURLToPath(new URL('./', import.meta.url));
const model = { providerID: 'openai', modelID: 'gpt-6-astra' };
const exclusive = a => ['code', 'legacy-exclusive'].includes(a.activity);
const conflict = (a, b) => exclusive(a) || exclusive(b) || a.claims.some(x =>
  b.claims.some(y => (x.resource === y.resource || x.resource === '*' || y.resource === '*') &&
    (x.mode === 'write' || y.mode === 'write')));

function normalize(args) {
  const activity = args.activity ?? 'legacy-exclusive';
  assert.ok(['code', 'discovery', 'planning', 'prototype', 'review', 'legacy-exclusive'].includes(activity));
  assert.ok(['implementation', 'fix', 'verification'].includes(args.role));
  if (args.activity) {
    assert.ok(args.claims?.length > 0 && args.claims.length <= 32);
    assert.equal(['discovery', 'review'].includes(activity), args.role === 'verification');
    for (const c of args.claims) {
      assert.match(c.resource, /^(\*|[a-z][a-z0-9:._-]{0,95})$/);
      assert.ok(['read', 'write'].includes(c.mode));
    }
    assert.equal(new Set(args.claims.map(c => c.resource)).size, args.claims.length);
  } else assert.equal(args.claims, undefined);
  return { role: args.role, activity, claims: args.claims ?? [{ resource: '*', mode: 'write' }] };
}

export function progress(messages, status = { type: 'idle' }) {
  const last = messages.at(-1)?.info;
  const assistants = messages.slice(-100).filter(m => m.info.role === 'assistant');
  const meaningful = assistants.findLast(m => m.parts.some(p => p.type === 'text' && p.text.trim()));
  const text = meaningful?.parts.filter(p => p.type === 'text').map(p => p.text).join('\n').slice(0, 4000);
  return {
    terminal: status.type === 'idle' && last?.role === 'assistant' && last.time.completed !== undefined &&
      (last.finish === 'stop' || last.error !== undefined),
    error: last?.role === 'assistant' ? last.error?.name : undefined,
    progress: meaningful ? { messageID: meaningful.info.id, createdAt: meaningful.info.time.created, text } : null,
    tools: assistants.flatMap(m => m.parts.filter(p => p.type === 'tool').map(p => ({
      messageID: m.info.id, createdAt: m.info.time.created, tool: p.tool,
      status: p.state.status, time: p.state.time,
    }))).slice(-20),
  };
}

// Real local filesystem exclusion and journal. No stale-lock stealing or leases.
async function locked(path, fn) {
  const lock = await open(`${path}/admission.lock`, 'wx', 0o600);
  try { return await fn(); }
  finally { await lock.close(); await unlink(`${path}/admission.lock`); }
}
async function save(path, ledger) {
  const tmp = await open(`${path}/ledger.next`, 'wx', 0o600);
  try { await tmp.writeFile(JSON.stringify(ledger)); await tmp.sync(); }
  finally { await tmp.close(); }
  await rename(`${path}/ledger.next`, `${path}/ledger.json`);
  const dir = await open(path, 'r');
  try { await dir.sync(); } finally { await dir.close(); }
}
async function load(path) {
  try { return JSON.parse(await readFile(`${path}/ledger.json`, 'utf8')); }
  catch (e) { if (e.code === 'ENOENT') return []; throw e; }
}

function dispatcher(client, path) {
  const query = { directory: '/workspace' };
  const messages = async id => (await client.session.messages({ path: { id }, query, throwOnError: true })).data;
  return {
    async start(args, parentID = 'parent', agent = 'markdown-orchestrator') {
      assert.equal(agent, 'markdown-orchestrator', 'nested delegation denied');
      const request = normalize(args);
      return locked(path, async () => {
        const ledger = await load(path);
        const children = (await client.session.children({ path: { id: parentID }, query, throwOnError: true })).data;
        const sessions = (await client.session.list({ query, throwOnError: true })).data;
        const statuses = (await client.session.status({ query, throwOnError: true })).data;
        for (const child of [...children, ...sessions.filter(s => s.parentID)]) {
          const row = ledger.find(r => r.childID === child.id && r.parentID === child.parentID);
          const snap = progress(await messages(child.id), statuses[child.id]);
          if (!row && !snap.terminal) throw Error('unknown existing child');
        }
        for (const row of ledger) {
          if (!row.childID) throw Error('creation indeterminate');
          const snap = progress(await messages(row.childID), statuses[row.childID]);
          if (snap.terminal) continue;
          if (row.state !== 'submitted') throw Error('dispatch indeterminate');
          if (conflict(row, request)) throw Error('ownership conflict');
        }
        const row = { version: 1, parentID, ...request, state: 'creating' };
        ledger.push(row);
        await save(path, ledger);
        try {
          const child = await client.session.create({ query, body: { parentID, title: 'probe' }, throwOnError: true });
          row.childID = child.data.id;
          row.state = 'dispatching';
          await save(path, ledger);
          await client.session.promptAsync({ path: { id: row.childID }, query, throwOnError: true,
            body: { agent: request.role === 'verification' ? 'markdown-reviewer' : 'markdown-implementer',
              model, parts: [{ type: 'text', text: `HURON_DISPATCH_V1\n${JSON.stringify(row)}\nAssignment` }] } });
          row.state = 'submitted';
          await save(path, ledger);
          return { childID: row.childID, state: row.state };
        } catch { return { childID: row.childID, state: 'indeterminate' }; }
      });
    },
    async poll(id, parentID = 'parent') {
      const children = (await client.session.children({ path: { id: parentID }, query, throwOnError: true })).data;
      if (!children.some(c => c.id === id)) throw Error('direct children only');
      const statuses = (await client.session.status({ query, throwOnError: true })).data;
      return progress(await messages(id), statuses[id]);
    },
  };
}

async function setup() {
  await mkdir(`${home}runs`, { recursive: true });
  const path = await mkdtemp(`${home}runs/probe-`);
  const state = { children: [], messages: {}, statuses: {}, prompts: [], fail: '', count: 0 };
  const client = createOpencodeClient({ baseUrl: 'http://opencode.test', fetch: async request => {
    const url = new URL(request.url);
    assert.equal(url.searchParams.get('directory'), '/workspace');
    const body = request.method === 'POST' ? await request.json() : undefined;
    if (url.pathname === '/session' && request.method === 'GET') return Response.json(state.children);
    if (url.pathname.endsWith('/children')) return Response.json(state.children.filter(c => c.parentID === url.pathname.split('/')[2]));
    if (url.pathname.endsWith('/message')) return Response.json(state.messages[url.pathname.split('/')[2]] ?? []);
    if (url.pathname === '/session/status') {
      if (state.fail === 'status') return new Response(null, { status: 503 });
      return Response.json(state.statuses);
    }
    if (url.pathname === '/session') {
      const c = { id: `child${++state.count}`, parentID: body.parentID };
      state.children.push(c);
      if (state.fail === 'create') throw Error('lost create response');
      return Response.json(c);
    }
    if (url.pathname.endsWith('/prompt_async')) {
      state.prompts.push(body);
      if (state.fail === 'dispatch') throw Error('lost dispatch response');
      return new Response(null, { status: 204 });
    }
    throw Error(`Unexpected boundary ${url.pathname}`);
  } });
  return { state, path, fresh: () => dispatcher(client, path), client };
}
const request = (activity, resource = 'scope:a', mode = 'write') => ({
  role: ['discovery', 'review'].includes(activity) ? 'verification' : 'implementation',
  activity, claims: [{ resource, mode }],
});
const final = (role = 'assistant', finish = 'stop') => ({ info: { id: 'm2', role, time: { created: 2, completed: 3 }, finish }, parts: [] });

test('independent non-code work overlaps and durable classification survives recreation', async () => {
  const { fresh, state } = await setup();
  await fresh().start(request('planning'));
  await fresh().start(request('prototype', 'scope:b'));
  await fresh().start(request('discovery', 'scope:c', 'read'));
  await fresh().start(request('review', 'scope:d', 'read'));
  assert.equal(state.children.length, 4);
  assert.deepEqual(state.prompts[0].model, model);
  assert.match(state.prompts[0].parts[0].text, /^HURON_DISPATCH_V1/);
});
test('code and legacy requests exclude every other active worker in both orders', async () => {
  for (const code of [request('code'), { role: 'fix' }, { role: 'verification' }]) {
    for (const pair of [[code, request('planning', 'scope:b')], [request('discovery', 'scope:b', 'read'), code]]) {
      const { fresh, state } = await setup();
      await fresh().start(pair[0]);
      await assert.rejects(fresh().start(pair[1]), /ownership conflict/);
      assert.equal(state.children.length, 1);
    }
  }
});
test('read sharing is allowed but read/write, write/write and wildcard overlap are denied', async () => {
  const { fresh } = await setup();
  await fresh().start(request('discovery', 'scope:a', 'read'));
  await fresh().start(request('review', 'scope:a', 'read'));
  await assert.rejects(fresh().start(request('planning')), /ownership conflict/);
  await assert.rejects(fresh().start(request('prototype', '*')), /ownership conflict/);
  const second = await setup();
  await second.fresh().start(request('planning'));
  await assert.rejects(second.fresh().start(request('prototype')), /ownership conflict/);
});
test('concurrent starts through different dispatcher instances admit only one exclusive child', async () => {
  const { fresh, state } = await setup();
  const outcomes = await Promise.allSettled([fresh().start(request('code')), fresh().start(request('planning', 'scope:b'))]);
  assert.equal(outcomes.filter(o => o.status === 'fulfilled').length, 1);
  assert.equal(state.children.length, 1);
});
test('unknown children and uncertain creation or dispatch block even independent starts after recreation', async () => {
  for (const fail of ['create', 'dispatch', 'unknown', 'status']) {
    const { fresh, state } = await setup();
    if (fail === 'unknown') state.children.push({ id: 'old', parentID: 'parent' });
    else {
      state.fail = fail;
      if (fail === 'status') await assert.rejects(fresh().start(request('planning')));
      else assert.equal((await fresh().start(request('planning'))).state, 'indeterminate');
    }
    if (fail !== 'status') state.fail = '';
    await assert.rejects(fresh().start(request('planning', 'scope:b')));
  }
});
test('terminal evidence uses the actual last response rather than retained progress', async () => {
  const { fresh, state } = await setup();
  const { childID } = await fresh().start(request('code'));
  for (const last of [undefined, final('user'), final('assistant', 'tool-calls'), final('assistant', 'length')]) {
    state.messages[childID] = last ? [last] : [];
    assert.equal((await fresh().poll(childID)).terminal, false);
    await assert.rejects(fresh().start(request('planning', 'scope:b')));
  }
  state.messages[childID] = [final()];
  state.statuses[childID] = { type: 'retry' };
  assert.equal((await fresh().poll(childID)).terminal, false);
  state.statuses = {};
  assert.equal((await fresh().poll(childID)).terminal, true);
  await fresh().start(request('planning', 'scope:b'));
  state.messages[childID].push(final('user'));
  await assert.rejects(fresh().start(request('planning', 'scope:c')));
});
test('bounded multi-message progress survives an empty tool turn without exposing raw tool data', () => {
  const messages = [{ info: { id: 'm1', role: 'assistant', time: { created: 1 } }, parts: [
    { type: 'text', text: 'Validation running' }, { type: 'reasoning', text: 'private' },
    { type: 'tool', tool: 'bash', state: { status: 'running', input: 'credential', output: 'secret', title: 'secret title', time: { start: 1 } } },
  ] }, final('assistant', 'tool-calls')];
  const snapshot = progress(messages);
  assert.equal(snapshot.progress.text, 'Validation running');
  assert.equal(snapshot.progress.createdAt, 1);
  assert.equal(snapshot.tools.length, 1);
  assert.equal(snapshot.terminal, false);
  assert.doesNotMatch(JSON.stringify(snapshot), /private|credential|secret/);
  assert.equal(progress(Array.from({ length: 150 }, () => messages[0])).tools.length, 20);
  const error = final(); error.info.error = { name: 'MessageAbortedError', data: { message: 'secret' } };
  assert.equal(progress([error]).error, 'MessageAbortedError');
  assert.equal(progress([error]).terminal, true);
});
test('direct-child visibility, nested denial and cross-parent known ownership are preserved', async () => {
  const { fresh, state } = await setup();
  await fresh().start(request('code'));
  await assert.rejects(fresh().poll('child1', 'other'), /direct children/);
  await assert.rejects(fresh().start(request('planning'), 'other'), /ownership conflict/);
  await assert.rejects(fresh().start(request('planning'), 'parent', 'markdown-implementer'), /nested delegation/);
  assert.equal(state.children.length, 1);
  const other = await setup();
  other.state.children.push({ id: 'unknown', parentID: 'other-parent' });
  await assert.rejects(other.fresh().start(request('planning')), /unknown existing child/);
});
test('a lock held by another OS process blocks admission without stale stealing', async () => {
  const { fresh, path, state } = await setup();
  const script = "const fs=require('node:fs'); const fd=fs.openSync(process.argv[1],'wx',0o600); process.stdout.write('locked'); process.stdin.once('data',()=>{fs.closeSync(fd);fs.unlinkSync(process.argv[1]);});";
  const child = spawn(process.execPath, ['-e', script, `${path}/admission.lock`], { stdio: ['pipe', 'pipe', 'inherit'] });
  await new Promise((resolve, reject) => { child.stdout.once('data', resolve); child.once('error', reject); });
  try { await assert.rejects(fresh().start(request('planning')), { code: 'EEXIST' }); assert.equal(state.children.length, 0); }
  finally { child.stdin.end('release'); }
  await new Promise(resolve => child.once('exit', resolve));
  await fresh().start(request('planning'));
});
test('malformed claims fail before creation and corrupt durable state is not silently reset', async () => {
  const { fresh, state, path } = await setup();
  for (const args of [{ ...request('planning'), activity: 'unknown' }, request('planning', 'src/**'),
    { ...request('discovery'), role: 'fix' }, { role: 'implementation', claims: [] }]) {
    await assert.rejects(fresh().start(args));
  }
  const fd = await open(`${path}/ledger.json`, 'wx'); await fd.writeFile('{'); await fd.close();
  await assert.rejects(fresh().start(request('planning')));
  assert.equal(state.children.length, 0);
});
