// @vitest-environment node
import { createCipheriv, randomBytes } from 'node:crypto';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HuronAccountStore } from './huron-accounts';
import { object } from './polaris-client';

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
		await authenticated?.client.authenticate();
		const lastOAuth = fetcher.mock.calls
			.filter(([url]) => String(url).includes('/oauth/tokens'))
			.at(-1);
		expect(String(lastOAuth?.[1]?.body)).toContain('client_id=user-1');
		expect(String(lastOAuth?.[1]?.body)).not.toContain('bootstrap-root');
	});

	it('authenticates the global Huron password without contacting Polaris', async () => {
		const { store, fetcher } = await fixture();
		await store.createUser({ username: 'alice', displayName: 'Alice', password: 'alice-password' });
		fetcher.mockClear();
		fetcher.mockRejectedValue(new Error('Polaris unavailable'));
		expect((await store.authenticate('alice', 'alice-password'))?.user.username).toBe('alice');
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('migrates legacy credentials without changing identities, passwords or upstream grants', async () => {
		const { store, options, fetcher } = await fixture();
		const alice = await store.createUser({
			username: 'alice',
			displayName: 'Alice',
			password: 'alice-password'
		});
		const document = object(JSON.parse(await readFile(options.path, 'utf8')));
		if (!Array.isArray(document.accounts)) throw new Error('Missing fixture accounts');
		const key = await readFile(`${options.path}.key`);
		const accounts = document.accounts.map((entry: unknown) => {
			const account = object(entry);
			const { identities: _identities, ...values } = account;
			if (account.isAdmin) return { ...values, credentials: null };
			const iv = randomBytes(12);
			const cipher = createCipheriv('aes-256-gcm', key, iv);
			cipher.setAAD(Buffer.from(alice.id));
			const encrypted = Buffer.concat([
				cipher.update(JSON.stringify({ clientId: 'user-1', clientSecret: 'user-private-1' })),
				cipher.final()
			]);
			return {
				...values,
				credentials: {
					iv: iv.toString('base64url'),
					tag: cipher.getAuthTag().toString('base64url'),
					value: encrypted.toString('base64url')
				}
			};
		});
		await writeFile(
			options.path,
			JSON.stringify({ version: 1, upstream: options.connection, accounts })
		);
		fetcher.mockClear();
		const restarted = new HuronAccountStore(options);
		const authenticated = await restarted.authenticate('alice', 'alice-password');
		expect(authenticated?.user).toEqual(alice);
		expect(authenticated?.clientId).toBe('user-1');
		expect(authenticated?.authVersion).toBe(1);
		expect(fetcher).not.toHaveBeenCalled();
		expect(object(JSON.parse(await readFile(options.path, 'utf8'))).version).toBe(2);
		await authenticated?.client.authenticate();
		expect(String(fetcher.mock.calls.at(-1)?.[1]?.body)).toContain('client_secret=user-private-1');
	});

	it('provisions isolated realm credentials explicitly and never falls back across roots', async () => {
		const { options, fetcher } = await fixture();
		const lab = {
			url: 'https://lab.example',
			realm: 'LAB',
			clientId: 'lab-root',
			clientSecret: 'lab-private'
		};
		const realmOptions = {
			...options,
			realms: () => [options.connection, { url: lab.url, realm: lab.realm }],
			bootstrap: async (realm = rootConnection.realm) =>
				realm === lab.realm ? lab : rootConnection
		};
		const store = new HuronAccountStore(realmOptions);
		const alice = await store.createUser({
			username: 'alice',
			displayName: 'Alice',
			password: 'alice-password'
		});
		await expect(store.polarisClient(alice.id, 'LAB')).rejects.toThrow('no identity');
		await expect(store.polarisClient(alice.id, 'UNKNOWN')).rejects.toThrow('not configured');
		fetcher.mockClear();
		const restarted = new HuronAccountStore(realmOptions);
		await Promise.all([
			store.ensureRealmIdentity(alice.id, 'LAB'),
			restarted.ensureRealmIdentity(alice.id, 'LAB')
		]);
		const created = fetcher.mock.calls.filter(
			([url, init]) => String(url).endsWith('/principals') && init?.method === 'POST'
		);
		expect(created).toHaveLength(1);
		expect(new Headers(created[0][1]?.headers).get('Polaris-Realm')).toBe('LAB');
		expect(fetcher.mock.calls.every(([url]) => !String(url).includes('/catalogs'))).toBe(true);
		fetcher.mockClear();
		const primary = await restarted.polarisClient(alice.id, 'POLARIS');
		const secondary = await restarted.polarisClient(alice.id, 'LAB');
		expect(secondary.connection).toEqual({ url: lab.url, realm: lab.realm });
		await primary.authenticate();
		await secondary.authenticate();
		expect(fetcher.mock.calls.map(([, init]) => String(init?.body))).toEqual([
			expect.stringContaining('client_id=user-1'),
			expect.stringContaining('client_id=user-2')
		]);
		expect(
			fetcher.mock.calls.map(([, init]) => new Headers(init?.headers).get('Polaris-Realm'))
		).toEqual(['POLARIS', 'LAB']);
		const admin = (await store.listUsers()).find((user) => user.isAdmin);
		if (!admin) throw new Error('Missing fixture admin');
		await store.ensureRealmIdentity(admin.id, 'LAB');
		fetcher.mockClear();
		await (await store.polarisClient(admin.id, 'LAB')).authenticate();
		expect(String(fetcher.mock.calls[0][1]?.body)).toContain('client_id=lab-root');

		const document = object(JSON.parse(await readFile(options.path, 'utf8')));
		if (!Array.isArray(document.accounts)) throw new Error('Missing fixture accounts');
		const savedAccounts = document.accounts.map((entry: unknown) => object(entry));
		const saved = savedAccounts.find((entry) => entry.id === alice.id);
		if (!saved || !Array.isArray(saved.identities)) throw new Error('Missing fixture identities');
		const identities = saved.identities.map((entry: unknown) => object(entry));
		const [first, second] = identities;
		[first.credentials, second.credentials] = [second.credentials, first.credentials];
		saved.identities = identities;
		document.accounts = savedAccounts;
		await writeFile(options.path, JSON.stringify(document));
		fetcher.mockClear();
		await expect(restarted.polarisClient(alice.id, 'LAB')).rejects.toThrow();
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('rejects bootstrap credentials for a different realm before provisioning', async () => {
		const { options, fetcher } = await fixture();
		const store = new HuronAccountStore({
			...options,
			realms: () => [options.connection, { url: 'https://lab.example', realm: 'LAB' }]
		});
		const alice = await store.createUser({
			username: 'alice',
			displayName: 'Alice',
			password: 'alice-password'
		});
		fetcher.mockClear();
		await expect(store.ensureRealmIdentity(alice.id, 'LAB')).rejects.toThrow('do not match');
		expect(fetcher).not.toHaveBeenCalled();
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
		await expect(store.polarisClient(user.id, 'POLARIS')).rejects.toThrow('active Huron account');
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
