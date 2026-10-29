import { mkdtempSync, cpSync, writeFileSync, existsSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { json, sha256 } from './files.mjs';

const root = mkdtempSync(resolve('.test-work', 'wrong-engine-'));
for (const name of ['package.json', 'package-lock.json', '.npmrc']) cpSync(name, resolve(root, name));
const lockHash = sha256(readFileSync(resolve(root, 'package-lock.json')));
const bin = '/home/karl/.nvm/versions/node/v20.17.0/bin';
const command = [resolve(bin, 'node'), resolve(bin, '../lib/node_modules/npm/bin/npm-cli.js'), 'ci'];
const result = spawnSync(command[0], command.slice(1), { cwd: root, env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, encoding: 'utf8' });
writeFileSync('evidence/wrong-engine.json', json({ cwd: root, command, exit: result.status, output: result.stdout + result.stderr }));
assert.equal(result.status, 1);
assert.match(result.stderr, /EBADENGINE/);
assert.equal(existsSync(resolve(root, 'node_modules')), false);
assert.equal(sha256(readFileSync(resolve(root, 'package-lock.json'))), lockHash);
console.log('PASS: ordinary npm ci under Node 20.17.0 rejected with EBADENGINE before node_modules or lock modification.');
