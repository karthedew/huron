// @vitest-environment node
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HuronAccountStore } from './huron-accounts';

const folders: string[] = [];
const rootConnection = {
	url: 'http://localhost:8181',
	realm: 'POLARIS',
	clientId: 'bootstrap-root',
	clientSecret: 'root-secret'
};

async function fixture() {
	const folder = await mkdtemp(join(tmpdir(), 'huron-accounts-'));
	folders.push(folder);
	let principals = 0;
	const fetcher = vi.fn<typeof fetch>(async (input, init) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens'))
			return Response.json({ access_token: 'oauth-server-only', expires_in: 3600 });
		if (url.pathname.endsWith('/principals') && init?.method === 'POST')
			return Response.json({
				credentials: {
					clientId: `user-${++principals}`,
					clientSecret: `user-private-${principals}`
				}
			});
		return new Response(null, { status: 204 });
	});
	const options = {
		path: join(folder, 'accounts.json'),
		connection: { url: rootConnection.url, realm: rootConnection.realm },
		bootstrap: async () => rootConnection,
		fetcher,
		initialPassword: 'initial-admin-password'
	};
	return { folder, options, fetcher, store: new HuronAccountStore(options) };
}

afterEach(async () => {
	await Promise.all(
		folders.splice(0).map((folder) => rm(folder, { recursive: true, force: true }))
	);
});

describe('Huron local accounts', () => {
	it('persists a protected default administrator with a salted hash and no browser-visible credentials', async () => {
		const { store, options } = await fixture();
		await store.initialize();
		const persisted = await readFile(options.path, 'utf8');
		expect(persisted).not.toContain('initial-admin-password');
		expect(persisted).not.toContain('root-secret');
		expect((await stat(options.path)).mode & 0o777).toBe(0o600);
		expect((await stat(`${options.path}.key`)).mode & 0o777).toBe(0o600);
		expect(JSON.parse(await readFile(store.initialCredentialsPath, 'utf8'))).toEqual({
			username: 'admin',
			password: 'initial-admin-password'
		});
		const restarted = new HuronAccountStore({
			...options,
			initialPassword: 'changed-in-environment'
		});
		const account = await restarted.authenticate('admin', 'initial-admin-password');
		expect(account?.user.isAdmin).toBe(true);
		expect(account?.user.polarisPrincipal).toBe('root');
		expect(JSON.stringify(await restarted.listUsers())).not.toMatch(
			/secret|password|hash|salt|credentials/
		);
	});

	it('rejects wrong passwords, unknown users and a reserved administrator username', async () => {
		const { store, fetcher } = await fixture();
		expect(await store.authenticate('admin', 'wrong-password')).toBeNull();
		expect(await store.authenticate('nobody', 'initial-admin-password')).toBeNull();
		for (const username of ['admin', 'ADMIN', 'root'])
			await expect(
				store.createUser({
					username,
					displayName: 'Spoofed administrator',
					password: 'valid-password'
				})
			).rejects.toThrow('reserved or already');
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('provisions each scientist with a distinct Polaris principal and no catalog access', async () => {
		const { store, options, fetcher } = await fixture();
		const alice = await store.createUser({
			username: 'Alice',
			displayName: 'Alice Scientist',
			password: 'alice-password'
		});
		const bob = await store.createUser({
			username: 'bob',
			displayName: 'Bob Scientist',
			password: 'bob-password'
		});
		expect(alice.username).toBe('alice');
		expect(alice.isAdmin).toBe(false);
		expect(alice.polarisPrincipal).not.toBe(bob.polarisPrincipal);
		expect(alice.polarisPrincipalRole).not.toBe(bob.polarisPrincipalRole);
		expect(fetcher.mock.calls.every(([url]) => !String(url).includes('/catalogs'))).toBe(true);
		const persisted = await readFile(options.path, 'utf8');
		for (const secret of ['alice-password', 'bob-password', 'user-private-1', 'user-private-2'])
			expect(persisted).not.toContain(secret);
		const restarted = new HuronAccountStore(options);
		const authenticated = await restarted.authenticate('alice', 'alice-password');
		expect(authenticated?.user).toEqual(alice);
		expect(authenticated?.clientId).toBe('user-1');
		const lastOAuth = fetcher.mock.calls
			.filter(([url]) => String(url).includes('/oauth/tokens'))
			.at(-1);
		expect(String(lastOAuth?.[1]?.body)).toContain('client_id=user-1');
		expect(String(lastOAuth?.[1]?.body)).not.toContain('bootstrap-root');
	});

	it('serializes concurrent provisioning and preserves both users across independent stores', async () => {
		const { store, options } = await fixture();
		const other = new HuronAccountStore(options);
		await Promise.all([
			store.createUser({ username: 'alice', displayName: 'Alice', password: 'alice-password' }),
			other.createUser({ username: 'bobby', displayName: 'Bob', password: 'bobby-password' })
		]);
		expect((await other.listUsers()).map((user) => user.username).sort()).toEqual([
			'admin',
			'alice',
			'bobby'
		]);
	});

	it('invalidates sessions on password changes and disabling, and preserves the default administrator', async () => {
		const { store } = await fixture();
		const user = await store.createUser({
			username: 'alice',
			displayName: 'Alice',
			password: 'alice-password'
		});
		const account = await store.authenticate('alice', 'alice-password');
		expect(await store.sessionUser(user.id, account?.authVersion ?? 0)).toEqual(user);
		await expect(store.changePassword(user.id, 'wrong-password', 'new-password')).rejects.toThrow(
			'current password'
		);
		await store.changePassword(user.id, 'alice-password', 'new-password');
		expect(await store.sessionUser(user.id, account?.authVersion ?? 0)).toBeNull();
		expect(await store.authenticate('alice', 'alice-password')).toBeNull();
		expect(await store.authenticate('alice', 'new-password')).not.toBeNull();
		await store.setDisabled(user.id, true);
		expect(await store.authenticate('alice', 'new-password')).toBeNull();
		const admin = (await store.listUsers()).find((user) => user.isAdmin);
		await expect(store.setDisabled(admin?.id ?? '', true)).rejects.toThrow('cannot be disabled');
		await store.resetPassword(user.id, 'reset-password');
		await store.setDisabled(user.id, false);
		expect(await store.authenticate('alice', 'reset-password')).not.toBeNull();
	});

	it('fails closed for changed upstream configuration, malformed records or a lost encryption key', async () => {
		const { store, options } = await fixture();
		await store.createUser({ username: 'alice', displayName: 'Alice', password: 'alice-password' });
		const anotherEndpoint = new HuronAccountStore({
			...options,
			connection: { ...options.connection, url: 'https://other.example' }
		});
		await expect(anotherEndpoint.authenticate('admin', 'initial-admin-password')).rejects.toThrow(
			'another Polaris endpoint'
		);
		await rm(`${options.path}.key`);
		await expect(store.authenticate('alice', 'alice-password')).rejects.toThrow();
		await writeFile(options.path, '{"version":1,"accounts":[]}');
		await expect(store.listUsers()).rejects.toThrow();
	});

	it('does not save an account when Polaris provisioning fails', async () => {
		const { options } = await fixture();
		const store = new HuronAccountStore({
			...options,
			fetcher: async (input) =>
				String(input).includes('/oauth/tokens')
					? Response.json({ access_token: 'token' })
					: Response.json({}, { status: 403 })
		});
		await expect(
			store.createUser({ username: 'alice', displayName: 'Alice', password: 'alice-password' })
		).rejects.toMatchObject({ status: 403 });
		expect((await store.listUsers()).map((user) => user.username)).toEqual(['admin']);
	});

	it('removes a newly provisioned principal when its role creation fails', async () => {
		const { options } = await fixture();
		let principalRemoved = false;
		const store = new HuronAccountStore({
			...options,
			fetcher: async (input, init) => {
				const path = new URL(String(input)).pathname;
				if (path.endsWith('/oauth/tokens')) return Response.json({ access_token: 'token' });
				if (path.endsWith('/principals') && init?.method === 'POST')
					return Response.json({
						credentials: { clientId: 'new-user', clientSecret: 'private-user-secret' }
					});
				if (path.endsWith('/principal-roles')) return Response.json({}, { status: 503 });
				if (path.includes('/principals/') && init?.method === 'DELETE') {
					principalRemoved = true;
					return new Response(null, { status: 204 });
				}
				return Response.json({}, { status: 404 });
			}
		});
		await expect(
			store.createUser({ username: 'alice', displayName: 'Alice', password: 'alice-password' })
		).rejects.toMatchObject({ status: 503 });
		expect(principalRemoved).toBe(true);
		expect((await store.listUsers()).map((user) => user.username)).toEqual(['admin']);
	});
});
