import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { lstatSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const root = fileURLToPath(new URL('../../../../', import.meta.url));
const env = { ...process.env, GIT_OPTIONAL_LOCKS: '0' };
const git = (...args) => execFileSync('git', args, { cwd: root, env, encoding: 'utf8' });
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const file = new URL('../evidence/initial-state.json', import.meta.url);
const state = () => {
  const names = [...new Set([
    ...git('ls-files', '-z').split('\0'),
    ...git('ls-files', '--others', '--exclude-standard', '-z').split('\0'),
  ])].filter(Boolean).sort();
  const files = Object.fromEntries(names.map((name) => {
    const path = resolve(root, name);
    try {
      const stat = lstatSync(path);
      return [name, { kind: stat.isSymbolicLink() ? 'symlink' : 'file', mode: stat.mode, sha256: sha(stat.isSymbolicLink() ? readlinkSync(path) : readFileSync(path)) }];
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      return [name, { kind: 'absent' }];
    }
  }));
  return {
    head: git('rev-parse', 'HEAD').trim(),
    status: git('status', '--porcelain=v1', '--untracked-files=all'),
    indexSha256: sha(readFileSync(resolve(root, git('rev-parse', '--git-path', 'index').trim()))),
    stagedSha256: sha(git('ls-files', '--stage', '-z')), files,
  };
};
if (process.argv[2] === 'record') {
  const initial = state();
  writeFileSync(file, JSON.stringify(initial, null, 2) + '\n', { flag: 'wx' });
  console.log(`Recorded ${Object.keys(initial.files).length} source paths, index and status; no source contents copied.`);
} else if (process.argv[2] === 'verify') {
  const initial = JSON.parse(readFileSync(file, 'utf8'));
  assert.deepEqual(state(), initial, 'Canonical files, index, HEAD and dirty status must be unchanged');
  console.log(`PASS: all ${Object.keys(initial.files).length} source paths, HEAD, index bytes and dirty status unchanged.`);
} else throw new Error('Use record or verify');
