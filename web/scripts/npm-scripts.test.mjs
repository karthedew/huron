import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const web = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const docs = JSON.parse(
	readFileSync(new URL('../docs-site/package.json', import.meta.url), 'utf8')
);
const cases = [
	[
		web.scripts['test:e2e'],
		[
			['run', 'build'],
			['run', 'docs:build']
		]
	],
	[web.scripts['docs:install'], [['--prefix', 'docs-site', 'ci', '--no-audit', '--no-fund']]],
	[web.scripts['docs:sync'], [['--prefix', 'docs-site', 'run', 'sync']]],
	[web.scripts['docs:build'], [['--prefix', 'docs-site', 'run', 'build']]],
	[web.scripts['docs:dev'], [['--prefix', 'docs-site', 'run', 'dev']]],
	[docs.scripts.dev, [['run', 'sync']]],
	[docs.scripts.build, [['run', 'sync']]]
];

for (const [command, expected] of cases) {
	test(`nested commands use the selected npm: ${command}`, () => {
		const root = mkdtempSync(join(tmpdir(), 'huron-npm-'));
		try {
			const bin = join(root, 'bin');
			mkdirSync(bin);
			mkdirSync(join(root, 'scripts'));
			writeFileSync(join(root, 'scripts/postbuild.mjs'), '');
			writeFileSync(join(bin, 'npm'), '#!/bin/sh\nexit 91\n', { mode: 0o755 });
			for (const tool of ['astro', 'playwright']) {
				writeFileSync(join(bin, tool), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
			}
			const selected = join(root, 'selected npm.cjs');
			writeFileSync(selected, 'console.log(JSON.stringify(process.argv.slice(2)));');
			const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, npm_execpath: selected };
			const shadow = spawnSync('npm', ['--version'], { cwd: root, env });
			assert.equal(shadow.status, 91, 'the control must select the PATH shadow');
			const result = spawnSync(command, { cwd: root, env, shell: true, encoding: 'utf8' });
			assert.equal(result.status, 0, result.stderr);
			assert.deepEqual(
				result.stdout
					.trim()
					.split('\n')
					.map((line) => JSON.parse(line)),
				expected
			);
		} finally {
			rmSync(root, { recursive: true, force: true });
		}
	});
}
