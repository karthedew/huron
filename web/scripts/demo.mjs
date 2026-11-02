/**
 * `npm run demo`: the web against a complete local stack without Keycloak or PostgreSQL. It
 * starts the fake company IdP with its fault proxy, the Huron API on the memory store, seeds
 * the e2e fixture and runs `vite dev`, all with matching settings, then prints the URL and the
 * users. Ctrl+C stops everything.
 *
 * The ports are those of the e2e harness (`HURON_E2E_IDP_PORT`, `HURON_E2E_PROXY_PORT`,
 * `HURON_E2E_API_PORT`) plus `HURON_DEMO_WEB_PORT` (5173), so the demo and `npm run test:e2e`
 * cannot run at the same time unless those are moved.
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { startFakeIdp } from '../e2e/support/fake-idp.mjs';
import { USERNAMES, USERS } from '../e2e/support/fixture.mjs';
import { seed } from '../e2e/support/seed.mjs';
import {
	LOOPBACK,
	apiCommand,
	apiEnvironment,
	demoStack,
	webEnvironment
} from '../e2e/support/stack.mjs';

/** @typedef {import('node:child_process').ChildProcess} ChildProcess */

const webRoot = fileURLToPath(new URL('..', import.meta.url));
const repositoryRoot = fileURLToPath(new URL('../..', import.meta.url));
const viteCli = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url));
const STARTUP_TIMEOUT_MS = 120_000;
const STOP_TIMEOUT_MS = 5_000;

/** @type {ReadonlyArray<[keyof import('../e2e/support/stack.mjs').Ports, string]>} */
const PORT_VARIABLES = [
	['idp', 'HURON_E2E_IDP_PORT'],
	['proxy', 'HURON_E2E_PROXY_PORT'],
	['api', 'HURON_E2E_API_PORT'],
	['web', 'HURON_DEMO_WEB_PORT']
];

const stack = demoStack(process.env);
/** @type {ChildProcess[]} */
const children = [];
/** @type {import('../e2e/support/fake-idp.mjs').FakeIdp | undefined} */
let idp;
let stopping = false;

for (const signal of /** @type {const} */ (['SIGINT', 'SIGTERM'])) {
	process.on(signal, () => {
		void stop(0);
	});
}

try {
	await ensurePortsFree();
	idp = await startFakeIdp({
		idpPort: stack.ports.idp,
		proxyPort: stack.ports.proxy,
		apiUrl: stack.apiUrl,
		webOrigins: stack.webOrigins
	});
	const [command, ...args] = apiCommand(stack);
	const api = start('API', command, args, repositoryRoot, apiEnvironment(stack));
	await waitUntilReady(`${stack.apiUrl}/readyz`, api);
	await seed({ apiUrl: stack.apiUrl, issuer: stack.issuer });
	const web = start(
		'vite dev',
		process.execPath,
		[viteCli, 'dev', '--host', LOOPBACK, '--port', String(stack.ports.web), '--strictPort'],
		webRoot,
		webEnvironment(stack)
	);
	await waitUntilReady(`http://${LOOPBACK}:${stack.ports.web}/healthz`, web);
	console.log(summary());
} catch (failure) {
	console.error(`demo: ${failure instanceof Error ? failure.message : String(failure)}`);
	await stop(1);
}

/**
 * Stop before starting anything when another process holds a port: a server left over from a
 * crashed run would answer the readiness checks, and the demo would seed into it. Browsers
 * reach the web as `localhost`, which resolves to `::1` first on some hosts.
 */
async function ensurePortsFree() {
	for (const [name, variable] of PORT_VARIABLES) {
		const port = stack.ports[name];
		for (const host of name === 'web' ? [LOOPBACK, '::1'] : [LOOPBACK]) {
			if (!(await isFree(port, host))) {
				throw new Error(
					`port ${port} (${variable}) is in use; stop what holds it or move the demo`
				);
			}
		}
	}
}

/**
 * Whether nothing listens on the port at that address; an address the host lacks (no IPv6)
 * counts as free.
 * @param {number} port
 * @param {string} host
 * @returns {Promise<boolean>}
 */
function isFree(port, host) {
	return new Promise((resolve, reject) => {
		const probe = createServer();
		probe.once('error', (failure) => {
			const code = 'code' in failure ? failure.code : undefined;
			if (code === 'EADDRINUSE') resolve(false);
			else if (code === 'EADDRNOTAVAIL') resolve(true);
			else reject(failure);
		});
		probe.listen(port, host, () => {
			probe.close(() => resolve(true));
		});
	});
}

/**
 * Start a child in its own process group, so stopping it also stops what it started (uv starts
 * Python).
 * @param {string} name
 * @param {string} command
 * @param {string[]} args
 * @param {string} cwd
 * @param {Record<string, string>} env
 * @returns {ChildProcess}
 */
function start(name, command, args, cwd, env) {
	const child = spawn(command, args, {
		cwd,
		env: { ...process.env, ...env },
		stdio: ['ignore', 'inherit', 'inherit'],
		detached: true
	});
	children.push(child);
	child.on('error', (failure) => {
		console.error(`demo: ${name} did not start: ${failure.message}`);
		void stop(1);
	});
	child.on('exit', (code, signal) => {
		if (stopping) return;
		console.error(`demo: ${name} exited (${signal ?? `code ${code}`}); stopping the demo`);
		void stop(1);
	});
	return child;
}

/**
 * Poll until the URL answers 200, the child exits or the startup timeout passes.
 * @param {string} url
 * @param {ChildProcess} child
 */
async function waitUntilReady(url, child) {
	const deadline = Date.now() + STARTUP_TIMEOUT_MS;
	while (Date.now() < deadline) {
		if (child.exitCode !== null || child.signalCode !== null || stopping) {
			throw new Error(`${url} never became ready: its process ended`);
		}
		try {
			const response = await fetch(url);
			if (response.ok) return;
		} catch {
			// Not listening yet.
		}
		await delay(250);
	}
	throw new Error(`${url} was not ready within ${STARTUP_TIMEOUT_MS / 1000} s`);
}

/**
 * Stop every child (SIGTERM to its process group, SIGKILL after a grace period) and the IdP.
 * @param {number} code
 */
async function stop(code) {
	if (stopping) return;
	stopping = true;
	await Promise.all(children.map((child) => terminate(child)));
	await idp?.close();
	process.exit(code);
}

/** @param {ChildProcess} child */
async function terminate(child) {
	if (child.pid === undefined || child.exitCode !== null || child.signalCode !== null) return;
	const exited = new Promise((resolve) => child.once('exit', resolve));
	signalGroup(child.pid, 'SIGTERM');
	const timeout = delay(STOP_TIMEOUT_MS).then(() => 'timeout');
	if ((await Promise.race([exited, timeout])) === 'timeout') {
		signalGroup(child.pid, 'SIGKILL');
		await exited;
	}
}

/**
 * @param {number} pid
 * @param {NodeJS.Signals} signal
 */
function signalGroup(pid, signal) {
	try {
		process.kill(-pid, signal);
	} catch {
		// The group is already gone.
	}
}

function summary() {
	const width = Math.max(...USERNAMES.map((username) => username.length));
	const users = USERNAMES.map((username) => {
		const { about, groups } = USERS[username];
		const listed = groups.length > 0 ? groups.join(', ') : 'no groups';
		return `  ${username.padEnd(width)}  ${about} [${listed}]`;
	});
	return [
		'',
		'Huron demo is running.',
		`  Web:  ${stack.webOrigins.join('  or  ')}`,
		`  API:  ${stack.apiUrl} (the web calls it through the fault proxy ${stack.proxyUrl})`,
		`  IdP:  ${stack.issuer} (fake company sign-in and group directory)`,
		'',
		'Sign in as one of these users on the fake IdP page:',
		...users,
		'',
		'Make API calls fail for one user (mode: unavailable, unauthorized, error500, reset, hang or',
		'null; an optional "path" such as "/api/v1/catalogs/heliophysics/search" limits it):',
		`  curl -X POST ${stack.proxyUrl}/__test/faults -H 'content-type: application/json' \\`,
		`    -d '{"subject":"oscar","mode":"unavailable"}'`,
		'',
		'Press Ctrl+C to stop everything.',
		''
	].join('\n');
}
