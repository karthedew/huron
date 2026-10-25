import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const accountDirectory = mkdtempSync(join(tmpdir(), 'huron-e2e-'));
const storageRoot = join(accountDirectory, 'storage');
const realmConnections = [
	'E2E_EMPTY',
	'E2E_ALPHA',
	'E2E_BETA',
	'E2E_ORGADMIN',
	'E2E_TOOLBAR',
	'E2E_RETRY'
].map((realm) => ({
	realm,
	url: 'http://127.0.0.1:8189',
	clientId: `${realm}-admin`,
	clientSecret: `${realm}-secret`
}));
const webDirectory = dirname(fileURLToPath(import.meta.url));
const inspectorPython = resolve(
	webDirectory,
	process.env.HURON_ICECHUNK_PYTHON || '../.local/polaris/icechunk-venv/bin/python'
);
try {
	execFileSync(
		inspectorPython,
		[
			'-I',
			resolve(webDirectory, '../scripts/seed_icechunk_ui_fixture.py'),
			join(storageRoot, 'huron-local/science/temperature')
		],
		{
			timeout: 15_000,
			maxBuffer: 1_000_000,
			env: { PATH: process.env.PATH || '/usr/bin:/bin', RUST_LOG: 'off' },
			stdio: ['ignore', 'pipe', 'pipe']
		}
	);
} catch {
	throw new Error(
		'Icechunk browser tests require the SDK runtime. Run scripts/polaris-dev.sh start from the repository root or configure HURON_ICECHUNK_PYTHON.'
	);
}

export default defineConfig({
	webServer: [
		{
			command: 'node e2e/polaris-mock.mjs',
			url: 'http://127.0.0.1:8189/health',
			env: { HURON_E2E_STORAGE_ROOT: storageRoot },
			reuseExistingServer: false
		},
		{
			command: 'npm run start',
			port: 4173,
			env: {
				HOST: '127.0.0.1',
				PORT: '4173',
				ORIGIN: 'http://localhost:4173',
				HURON_ACCOUNT_STORE: join(accountDirectory, 'accounts.json'),
				HURON_ADMIN_PASSWORD: 'browser-admin-password',
				HURON_ALLOW_SIGNUP: 'false',
				HURON_ICECHUNK_PYTHON: inspectorPython,
				HURON_ICECHUNK_READ_ROOTS: storageRoot,
				POLARIS_BOOTSTRAP_CLIENT_ID: 'browser-admin',
				POLARIS_BOOTSTRAP_CLIENT_SECRET: 'browser-secret',
				POLARIS_URL: 'http://127.0.0.1:8189',
				POLARIS_REALM: 'POLARIS',
				POLARIS_CONNECTIONS_JSON: JSON.stringify(realmConnections)
			},
			reuseExistingServer: false
		}
	],
	testDir: 'e2e',
	use: { baseURL: 'http://localhost:4173' }
});
