import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Capture the actual exit independently from a terminal's output truncation.
const [name, command, ...args] = process.argv.slice(2);
if (!name || !command || !/^[a-z0-9-]+$/.test(name)) throw new Error('receipt NAME COMMAND [ARGS]');
const root = new URL('../', import.meta.url);
const dir = new URL('evidence/commands/', root);
mkdirSync(dir, { recursive: true });
const startedAt = new Date().toISOString();
const started = performance.now();
const result = spawnSync(command, args, { cwd: process.cwd(), env: process.env, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
const inBandFailure = command === 'npx' && args.includes('cli') && /^### Error\b/m.test(output);
writeFileSync(new URL(`${name}.log`, dir), output, { flag: 'wx' });
writeFileSync(new URL(`${name}.json`, dir), JSON.stringify({
  cwd: resolve(process.cwd()), command: [command, ...args], exit: result.status,
  signal: result.signal, error: result.error?.message ?? null, inBandFailure,
  node: process.version, cache: process.env.NPM_CONFIG_CACHE ?? null,
  environment: Object.fromEntries(['DOCS_BASE', 'DOCS_RUN', 'ASTRO_TELEMETRY_DISABLED', 'UV_CACHE_DIR', 'GIT_OPTIONAL_LOCKS'].map((key) => [key, process.env[key] ?? null])),
  startedAt, durationMs: Math.round(performance.now() - started),
}, null, 2) + '\n', { flag: 'wx' });
process.stdout.write(output);
process.exitCode = inBandFailure ? 1 : result.status ?? 1;
