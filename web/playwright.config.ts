import { defineConfig, devices } from '@playwright/test';
import {
	FAULTS_PROJECT,
	LOOPBACK,
	apiCommand,
	apiEnvironment,
	e2eStack,
	idpEnvironment,
	webEnvironment
} from './e2e/support/stack.mjs';

const stack = e2eStack(process.env);
const browser = { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } };

/**
 * The fake IdP with its fault proxy, the API on the memory store and the built web server start
 * in that order, each with every setting explicit; the `setup` project seeds the fixture once
 * and every test project depends on it.
 */
export default defineConfig({
	testDir: 'e2e',
	forbidOnly: Boolean(process.env.CI),
	retries: 0,
	workers: 4,
	reporter: [['list']],
	use: {
		baseURL: stack.webOrigin,
		locale: 'en-US',
		timezoneId: 'UTC',
		trace: 'retain-on-failure'
	},
	projects: [
		{ name: 'setup', testMatch: /seed\.setup\.ts$/, retries: 0 },
		{
			name: 'chromium',
			testMatch: /\.test\.ts$/,
			testIgnore: /\/faults\//,
			dependencies: ['setup'],
			use: browser
		},
		{
			// Injected faults follow a user, not a test: these tests never overlap, not even
			// copies of one test under --repeat-each.
			name: FAULTS_PROJECT,
			testMatch: /\/faults\/.*\.test\.ts$/,
			dependencies: ['setup'],
			workers: 1,
			use: browser
		}
	],
	webServer: [
		{
			name: 'idp',
			command: 'node e2e/support/fake-idp.mjs',
			url: `${stack.issuer}/.well-known/openid-configuration`,
			env: idpEnvironment(stack),
			reuseExistingServer: false,
			timeout: 30_000
		},
		{
			name: 'api',
			command: apiCommand(stack).join(' '),
			cwd: '..',
			url: `${stack.apiUrl}/readyz`,
			env: apiEnvironment(stack),
			reuseExistingServer: false,
			timeout: 120_000
		},
		{
			name: 'web',
			// Not `npm run start`, which would read web/.env.
			command: 'node build/index.js',
			url: `http://${LOOPBACK}:${stack.ports.web}/healthz`,
			env: webEnvironment(stack),
			reuseExistingServer: false,
			timeout: 30_000
		}
	]
});
