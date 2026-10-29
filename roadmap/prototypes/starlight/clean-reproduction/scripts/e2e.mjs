import { existsSync, readFileSync, readlinkSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const base = process.env.DOCS_BASE ?? '/';
const run = process.env.DOCS_RUN ?? 'full';
if (!['/', '/huron-docs/'].includes(base) || !/^[a-z0-9-]+$/.test(run)) throw new Error('Invalid test environment');
const output = `evidence/e2e-${base === '/' ? 'root' : 'subbase'}-${run}`;
if (existsSync(output) || existsSync(`${output}.json`)) throw new Error('Evidence exists; choose a new DOCS_RUN, never delete old/unknown results');
const service = JSON.parse(readFileSync('.work/preview.json', 'utf8'));
if (!service.ready || service.stopped || service.base !== base || readlinkSync(`/proc/${service.pid}/cwd`) !== process.cwd()) throw new Error('Expected owned built preview is not active');
const command = readFileSync(`/proc/${service.pid}/cmdline`, 'utf8').split('\0').filter(Boolean);
if (JSON.stringify(command) !== JSON.stringify(service.command)) throw new Error('Preview PID identity changed');
const result = spawnSync(process.execPath, [resolve('node_modules/@playwright/test/cli.js'), 'test', ...process.argv.slice(2)], { stdio: 'inherit', env: process.env });
process.exitCode = result.status ?? 1;
