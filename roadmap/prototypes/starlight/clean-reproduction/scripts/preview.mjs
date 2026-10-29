import { spawn, execFileSync } from 'node:child_process';
import { openSync, closeSync, writeFileSync, readFileSync, readlinkSync, existsSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { json } from './files.mjs';

const root = process.cwd();
const stateFile = '.work/preview.json';
const endpoint = 'http://127.0.0.1:4327';
const command = [process.execPath, resolve('node_modules/astro/bin/astro.mjs'), 'preview', '--host', '127.0.0.1', '--port', '4327', '--background', '--json'];
const listeners = () => execFileSync('ss', ['-ltnp', '( sport = :4327 )'], { encoding: 'utf8' });
const [action, label = 'root'] = process.argv.slice(2);
if (!/^[a-z0-9-]+$/.test(label)) throw new Error('Invalid evidence label');

function qualify() {
  const state = JSON.parse(readFileSync(stateFile, 'utf8'));
  if (state.stopped || state.ready) throw new Error('Only qualify the recorded unqualified launch');
  const astro = JSON.parse(readFileSync('.astro/preview.json', 'utf8'));
  const launchLog = readFileSync(`evidence/preview-${state.label}.log`, 'utf8');
  const actualCommand = readFileSync(`/proc/${astro.pid}/cmdline`, 'utf8').split('\0').filter(Boolean);
  const expectedCommand = [process.execPath, resolve('node_modules/astro/bin/astro.mjs'), 'preview', '--port', '4327', '--host', '127.0.0.1', '--json'];
  const after = listeners();
  if (astro.url !== endpoint || astro.port !== 4327 || !launchLog.includes(`(pid ${astro.pid})`) || !after.includes(`pid=${astro.pid},`) || readlinkSync(`/proc/${astro.pid}/cwd`) !== root || JSON.stringify(actualCommand) !== JSON.stringify(expectedCommand)) throw new Error('Background handshake, process or listener differs; reconcile ownership');
  const qualified = { ...state, launchPid: state.pid, launchCommand: state.command, pid: astro.pid, command: actualCommand, after, ready: true };
  writeFileSync(stateFile, json(qualified));
  writeFileSync(`evidence/service-${state.label}-qualified.json`, json(qualified), { flag: 'wx' });
  console.log(`Owned built preview qualified: PID ${astro.pid}, ${endpoint + state.base}`);
}
if (action === 'start') {
  if (existsSync(stateFile) && !JSON.parse(readFileSync(stateFile, 'utf8')).stopped) throw new Error('Owned preview state is active; reconcile rather than replay');
  const before = listeners();
  if (before.trim().split('\n').length !== 1) throw new Error('Port 4327 is occupied; no takeover');
  const fd = openSync(`evidence/preview-${label}.log`, 'wx');
  const child = spawn(command[0], command.slice(1), { cwd: root, env: process.env, detached: true, stdio: ['ignore', fd, fd] });
  child.unref();
  closeSync(fd);
  const state = { pid: child.pid, cwd: root, command, label, base: process.env.DOCS_BASE ?? '/', before, stopped: false };
  writeFileSync(stateFile, json(state));
  writeFileSync(`evidence/service-${label}.json`, json(state), { flag: 'wx' });
  let ready = false;
  for (let i = 0; i < 100; i++) {
    try {
      const response = await fetch(endpoint + state.base, { signal: AbortSignal.timeout(500) });
      if (response.ok && (await response.text()).includes('Huron · throwaway docs probe')) { ready = true; break; }
    } catch { /* Readiness has a bounded deadline; it is not a passing check. */ }
    await setTimeout(100);
  }
  if (!ready) throw new Error(`Owned preview PID ${child.pid} failed readiness; inspect its log, do not replay`);
  // The installed Astro CLI forks its background child; wait for its handshake.
  for (let i = 0; i < 100 && !readFileSync(`evidence/preview-${label}.log`, 'utf8').includes('(pid '); i++) await setTimeout(100);
  qualify();
} else if (action === 'qualify') {
  qualify();
} else if (action === 'stop') {
  const state = JSON.parse(readFileSync(stateFile, 'utf8'));
  if (state.stopped) throw new Error('Preview already stopped');
  const actualCommand = readFileSync(`/proc/${state.pid}/cmdline`, 'utf8').split('\0').filter(Boolean);
  if (readlinkSync(`/proc/${state.pid}/cwd`) !== state.cwd || JSON.stringify(actualCommand) !== JSON.stringify(state.command)) throw new Error('PID identity differs; refuse signal');
  process.kill(state.pid, 'SIGTERM');
  for (let i = 0; i < 100 && listeners().trim().split('\n').length > 1; i++) await setTimeout(100);
  const after = listeners();
  if (after.trim().split('\n').length !== 1) throw new Error('Listener survived owned stop; no broad shutdown');
  if (existsSync('.astro/preview.json')) {
    const astro = JSON.parse(readFileSync('.astro/preview.json', 'utf8'));
    if (astro.pid !== state.pid) throw new Error('Astro state changed ownership; do not move it');
    renameSync('.astro/preview.json', `evidence/service-${state.label}-stopped-astro.json`);
  }
  writeFileSync(stateFile, json({ ...state, stopped: true }));
  writeFileSync(`evidence/service-${state.label}-stopped.json`, json({ pid: state.pid, command: state.command, stopped: true, after }), { flag: 'wx' });
  console.log(`Stopped only owned PID ${state.pid}; port 4327 is free.`);
} else throw new Error('Use start LABEL, qualify or stop');
