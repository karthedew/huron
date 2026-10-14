import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HuronUser, PolarisCatalog, PolarisRole } from '$api/types';
import {
	HuronOrganizationStore,
	organizationDirectory,
	requireOrganizationCatalog
} from './huron-organizations';
import { visibleCatalogs } from './polaris-catalogs';
import { PolarisClient } from './polaris-client';

vi.mock('./polaris-catalogs', () => ({ visibleCatalogs: vi.fn() }));
const directories: string[] = [];
const connection = { url: 'http://localhost:8181', realm: 'POLARIS' };
const connections = [
	connection,
	{ ...connection, realm: 'SECOND' },
	{ ...connection, realm: 'THIRD' }
];
function user(username: string, admin = false): HuronUser {
	return {
		id: username,
		username,
		displayName: username,
		isAdmin: admin,
		disabled: false,
		polarisPrincipal: `principal-${username}`,
		polarisPrincipalRole: `role-${username}`,
		createdAt: '2026-10-13T00:00:00Z'
	};
}
const admin = user('admin', true),
	alice = user('alice'),
	bob = user('bob'),
	carol = user('carol');
function catalog(name: string): PolarisCatalog {
	return { name, type: 'INTERNAL', properties: {}, storageConfigInfo: { storageType: 'FILE' } };
}
const nasa = ['geoscience', 'heliophysics', 'international_space_station'].map(catalog);
const readerRole = [{ name: 'huron_reader', properties: {} }];
const otherOrganization = { slug: 'other-org', name: 'Other', description: '', realm: 'SECOND' };
async function fixture(initialCatalogs: PolarisCatalog[] = nasa) {
	const directory = await mkdtemp(join(tmpdir(), 'huron-organizations-'));
	directories.push(directory);
	const path = join(directory, 'organizations.json');
	const catalogs = new Map<string, PolarisCatalog[]>([
		['POLARIS', initialCatalogs],
		['SECOND', []],
		['THIRD', []]
	]);
	let users = [admin, alice, bob, carol];
	const assignments = new Map<string, PolarisRole[]>([
		['POLARIS/alice/geoscience', readerRole],
		['POLARIS/bob/heliophysics', [{ name: 'huron_catalog_admin', properties: {} }]]
	]);
	const assignmentReader = vi.fn(
		async (user: HuronUser, catalog: string, realm: string) =>
			assignments.get(`${realm}/${user.id}/${catalog}`) ?? []
	);
	const catalogReader = vi.fn(async (realm: string) => catalogs.get(realm) ?? []);
	const ensureIdentity = vi.fn(async (userId: string, _realm: string) => {
		const found = users.find((entry) => entry.id === userId);
		if (!found) throw new Error('Missing account');
		return found;
	});
	const options = {
		path,
		connection,
		connections: () => connections,
		users: async () => users,
		catalogs: catalogReader,
		assignments: assignmentReader,
		ensureIdentity
	};
	return {
		path,
		options,
		store: new HuronOrganizationStore(options),
		restart: () => new HuronOrganizationStore(options),
		assignments,
		assignmentReader,
		catalogReader,
		ensureIdentity,
		setCatalogs: (value: PolarisCatalog[], realm = 'POLARIS') => catalogs.set(realm, value),
		setUsers: (value: HuronUser[]) => (users = value)
	};
}
async function writeLegacy(path: string, organizations?: object[]) {
	await writeFile(
		path,
		JSON.stringify({
			version: 1,
			upstream: connection,
			organizations: organizations ?? [
				{
					id: 'existing-nasa-id',
					slug: 'nasa-science',
					name: 'NASA Science',
					description: 'Preserved',
					createdAt: '2026-10-13T00:00:00Z',
					catalogNames: nasa.map((entry) => entry.name),
					members: [
						{ userId: 'admin', role: 'admin' },
						{ userId: 'alice', role: 'member' }
					]
				}
			]
		})
	);
}
afterEach(async () => {
	vi.restoreAllMocks();
	vi.clearAllMocks();
	await Promise.all(
		directories.splice(0).map((path) => rm(path, { recursive: true, force: true }))
	);
});

describe('Huron organizations bound to native Polaris realms', () => {
	it('seeds one NASA realm root with scoped memberships without promoting catalog administrators', async () => {
		const { store, path, assignments } = await fixture();
		const originalAssignments = structuredClone([...assignments]);
		expect(await store.list(alice, [nasa[0]], 'POLARIS')).toEqual([
			expect.objectContaining({
				slug: 'nasa-science',
				realm: 'POLARIS',
				role: 'member',
				catalogNames: ['geoscience']
			})
		]);
		expect(await store.list(bob, [nasa[1]], 'POLARIS')).toEqual([
			expect.objectContaining({ role: 'member', catalogNames: ['heliophysics'] })
		]);
		expect(await store.list(carol, nasa, 'POLARIS')).toEqual([]);
		expect(await store.list(admin, nasa, 'POLARIS')).toEqual([
			expect.objectContaining({ role: 'admin', catalogNames: nasa.map((entry) => entry.name) })
		]);
		expect([...assignments]).toEqual(originalAssignments);
		expect((await stat(path)).mode & 0o777).toBe(0o600);
		expect(await readFile(path, 'utf8')).not.toMatch(
			/password|clientSecret|polarisPrincipal|catalogNames/
		);
	});
	it('creates a default root for an empty realm and keeps mixed programs in one root', async () => {
		const empty = await fixture([]);
		expect(await empty.store.list(admin)).toEqual([
			expect.objectContaining({ slug: 'workspace', realm: 'POLARIS', catalogNames: [] })
		]);
		const mixed = await fixture([...nasa, catalog('research')]);
		expect(await mixed.store.list(admin, [...nasa, catalog('research')], 'POLARIS')).toEqual([
			expect.objectContaining({
				slug: 'workspace',
				catalogNames: [...nasa.map((entry) => entry.name), 'research']
			})
		]);
	});
	it('migrates one legacy organization preserving identity, members and realm without upstream writes', async () => {
		const { store, path, catalogReader, ensureIdentity, restart } = await fixture();
		await writeLegacy(path);
		expect(await store.get(alice, 'nasa-science')).toMatchObject({
			id: 'existing-nasa-id',
			realm: 'POLARIS',
			description: 'Preserved',
			role: 'member'
		});
		expect(await readFile(path, 'utf8')).toContain('"version": 2');
		expect(await readFile(path, 'utf8')).not.toContain('catalogNames');
		expect(catalogReader).not.toHaveBeenCalled();
		expect(ensureIdentity).not.toHaveBeenCalled();
		await store.update(admin, 'nasa-science', { name: 'NASA Programs', description: 'Updated' });
		expect(await restart().get(alice, 'nasa-science')).toMatchObject({
			id: 'existing-nasa-id',
			name: 'NASA Programs',
			realm: 'POLARIS'
		});
	});
	it('refuses legacy organizations sharing one realm without modifying the store', async () => {
		const { store, path } = await fixture();
		await writeLegacy(path, [{ id: 'first' }, { id: 'second' }]);
		const original = await readFile(path, 'utf8');
		await expect(store.list(admin)).rejects.toThrow('Legacy organizations share one Polaris realm');
		expect(await readFile(path, 'utf8')).toBe(original);
	});
	it('lists roots without fetching other realms or enrolling later accounts while showing new native catalogs', async () => {
		const { store, assignments, setCatalogs, assignmentReader, catalogReader } = await fixture();
		await store.initialize();
		await store.create(admin, otherOrganization);
		assignmentReader.mockClear();
		catalogReader.mockClear();
		assignments.set('POLARIS/carol/geoscience', readerRole);
		setCatalogs([...nasa, catalog('new_program')]);
		expect(await store.list(carol)).toEqual([]);
		expect(await store.list(admin)).toEqual([
			expect.objectContaining({ slug: 'nasa-science', catalogNames: [] }),
			expect.objectContaining({ slug: 'other-org', catalogNames: [] })
		]);
		expect(
			(await store.list(admin, [...nasa, catalog('new_program')], 'POLARIS'))[0].catalogNames
		).toContain('new_program');
		expect(catalogReader).not.toHaveBeenCalled();
		expect(assignmentReader).not.toHaveBeenCalled();
		await expect(store.list(admin, nasa)).rejects.toThrow('explicit Polaris realm');
	});
	it('isolates identical catalog names across realms and validates membership candidates in the selected realm', async () => {
		const { store, setCatalogs } = await fixture();
		await store.create(admin, otherOrganization);
		setCatalogs([catalog('geoscience')], 'SECOND');
		expect(await store.list(alice, [catalog('geoscience')], 'SECOND')).toEqual([
			expect.objectContaining({ realm: 'POLARIS', catalogNames: [] })
		]);
		await expect(store.catalogUsers(alice, 'geoscience', 'SECOND')).rejects.toMatchObject({
			status: 404
		});
		expect(
			(await store.catalogUsers(bob, 'heliophysics', 'POLARIS')).map((entry) => entry.username)
		).toEqual(['admin', 'alice', 'bob']);
		expect(
			(await store.catalogUsers(admin, 'heliophysics', 'POLARIS')).map((entry) => entry.username)
		).toContain('carol');
		await expect(store.catalogUsers(carol, 'heliophysics', 'POLARIS')).rejects.toMatchObject({
			status: 404
		});
		await expect(store.catalogUsers(bob, 'missing', 'POLARIS')).rejects.toMatchObject({
			status: 404
		});
		await store.setMembership(admin, 'other-org', 'alice', 'member');
		expect(await store.list(alice, [catalog('geoscience')], 'SECOND')).toEqual([
			expect.objectContaining({ realm: 'POLARIS', catalogNames: [] }),
			expect.objectContaining({ realm: 'SECOND', catalogNames: ['geoscience'] })
		]);
	});
	it('creates organizations only in configured unused reachable realms and provisions the creator', async () => {
		const { store, ensureIdentity, catalogReader } = await fixture();
		await store.initialize();
		catalogReader.mockClear();
		expect(
			await store.create(admin, {
				...otherOrganization,
				name: ' Other ',
				description: ' description '
			})
		).toMatchObject({ realm: 'SECOND', name: 'Other', description: 'description' });
		expect(catalogReader).toHaveBeenCalledExactlyOnceWith('SECOND');
		expect(ensureIdentity).toHaveBeenCalledExactlyOnceWith(admin.id, 'SECOND');
		await expect(
			store.create(admin, { ...otherOrganization, slug: 'third-org' })
		).rejects.toMatchObject({ status: 409 });
		await expect(
			store.create(admin, { ...otherOrganization, realm: 'THIRD' })
		).rejects.toMatchObject({ status: 409 });
		await expect(
			store.create(admin, { ...otherOrganization, slug: 'unsafe', realm: 'UNKNOWN' })
		).rejects.toThrow('configured Polaris realm');
		await expect(store.create(admin, { ...otherOrganization, slug: '../unsafe' })).rejects.toThrow(
			'identifier'
		);
		await expect(store.update(admin, 'other-org', { name: '', description: '' })).rejects.toThrow(
			'name'
		);
	});
	it('does not persist an organization when its realm or creator identity is unavailable', async () => {
		const { store, path, catalogReader, ensureIdentity } = await fixture();
		await store.initialize();
		const original = await readFile(path, 'utf8');
		catalogReader.mockRejectedValueOnce(new Error('Realm unavailable'));
		await expect(store.create(admin, otherOrganization)).rejects.toThrow('Realm unavailable');
		expect(ensureIdentity).not.toHaveBeenCalled();
		expect(await readFile(path, 'utf8')).toBe(original);
		ensureIdentity.mockRejectedValueOnce(new Error('Principal unavailable'));
		await expect(store.create(admin, otherOrganization)).rejects.toThrow('Principal unavailable');
		expect(await readFile(path, 'utf8')).toBe(original);
	});
	it('conceals roots from nonmembers and rejects member or disabled administration', async () => {
		const { store } = await fixture();
		await expect(store.get(carol, 'nasa-science')).rejects.toMatchObject({ status: 404 });
		await expect(store.members(carol, 'nasa-science')).rejects.toMatchObject({ status: 404 });
		await expect(
			store.update(carol, 'nasa-science', { name: 'Hidden', description: '' })
		).rejects.toMatchObject({ status: 404 });
		await expect(store.members(alice, 'nasa-science')).rejects.toMatchObject({ status: 403 });
		await expect(
			store.setMembership(alice, 'nasa-science', 'carol', 'member')
		).rejects.toMatchObject({ status: 403 });
		await expect(store.create(alice, otherOrganization)).rejects.toMatchObject({ status: 403 });

		await expect(store.list({ ...admin, disabled: true })).rejects.toMatchObject({ status: 403 });
	});
	it('provisions membership in its realm without catalog grants and keeps admin operations scoped', async () => {
		const { store, assignments, ensureIdentity } = await fixture();
		await store.setMembership(admin, 'nasa-science', 'alice', 'admin');
		await store.update(alice, 'nasa-science', { name: 'NASA Research', description: '' });
		await store.setMembership(alice, 'nasa-science', 'carol', 'member');
		expect(ensureIdentity).toHaveBeenCalledWith(carol.id, 'POLARIS');
		expect(await store.members(alice, 'nasa-science')).toEqual(
			expect.arrayContaining([{ user: carol, role: 'member' }])
		);
		expect(await store.list(carol)).toEqual([
			expect.objectContaining({ name: 'NASA Research', catalogNames: [] })
		]);
		expect(assignments.has('POLARIS/carol/geoscience')).toBe(false);
		await store.create(admin, otherOrganization);
		await expect(store.setMembership(alice, 'other-org', 'bob', 'admin')).rejects.toMatchObject({
			status: 404
		});
	});
	it('does not add membership when realm identity provisioning fails', async () => {
		const { store, path, ensureIdentity } = await fixture();
		await store.initialize();
		const original = await readFile(path, 'utf8');
		ensureIdentity.mockRejectedValueOnce(new Error('Provisioning failed'));
		await expect(store.setMembership(admin, 'nasa-science', 'carol', 'member')).rejects.toThrow(
			'Provisioning failed'
		);
		expect(await readFile(path, 'utf8')).toBe(original);
	});
	it('requires revocation only in the removed realm, including grants on newly created catalogs', async () => {
		const { store, restart, assignments, setCatalogs, assignmentReader } = await fixture();
		await store.create(admin, otherOrganization);
		setCatalogs([catalog('geoscience')], 'SECOND');
		await store.setMembership(admin, 'other-org', 'alice', 'member');
		assignments.set('SECOND/alice/geoscience', readerRole);
		await expect(store.setMembership(admin, 'nasa-science', 'alice', 'none')).rejects.toThrow(
			'Polaris catalog roles'
		);
		assignments.delete('POLARIS/alice/geoscience');
		setCatalogs([...nasa, catalog('new_program')]);
		assignments.set('POLARIS/alice/new_program', readerRole);
		await expect(store.setMembership(admin, 'nasa-science', 'alice', 'none')).rejects.toThrow(
			'Polaris catalog roles'
		);
		assignments.delete('POLARIS/alice/new_program');
		assignmentReader.mockClear();
		await store.setMembership(admin, 'nasa-science', 'alice', 'none');
		expect(assignmentReader.mock.calls.every(([, , realm]) => realm === 'POLARIS')).toBe(true);
		expect(await restart().list(alice)).toEqual([expect.objectContaining({ realm: 'SECOND' })]);
		assignments.set('POLARIS/alice/geoscience', readerRole);
		expect(await restart().list(alice)).toEqual([expect.objectContaining({ realm: 'SECOND' })]);
	});
	it('preserves default administration and rejects disabled accounts for new membership', async () => {
		const { store, setUsers } = await fixture();
		await expect(store.setMembership(admin, 'nasa-science', 'admin', 'none')).rejects.toThrow(
			'default Huron administrator'
		);
		await expect(store.setMembership(admin, 'nasa-science', 'admin', 'member')).rejects.toThrow(
			'default Huron administrator'
		);
		setUsers([admin, alice, bob, { ...carol, disabled: true }]);
		await expect(store.setMembership(admin, 'nasa-science', 'carol', 'member')).rejects.toThrow(
			'Enable'
		);
	});
	it('permits catalog-role changes for members but requires an organization admin for enrollment', async () => {
		const { store, ensureIdentity } = await fixture();
		await expect(
			store.ensureMembershipForCatalog(bob, alice.id, 'heliophysics', 'POLARIS')
		).resolves.toBeUndefined();
		await expect(
			store.ensureMembershipForCatalog(bob, carol.id, 'heliophysics', 'POLARIS')
		).rejects.toMatchObject({ status: 403 });
		await store.ensureMembershipForCatalog(admin, carol.id, 'heliophysics', 'POLARIS');
		expect(ensureIdentity).toHaveBeenCalledWith(carol.id, 'POLARIS');
		expect(await store.list(carol)).toEqual([
			expect.objectContaining({ role: 'member', catalogNames: [] })
		]);
		await store.setMembership(admin, 'nasa-science', 'alice', 'admin');
		await store.ensureMembershipForCatalog(admin, alice.id, 'heliophysics', 'POLARIS');
		expect((await store.list(alice))[0].role).toBe('admin');
	});
	it('serializes independent realm creation and concurrent membership writes without lost updates', async () => {
		const { store, restart } = await fixture();
		await Promise.all([
			store.create(admin, { ...otherOrganization, slug: 'first-org' }),
			restart().create(admin, { ...otherOrganization, slug: 'second-org', realm: 'THIRD' })
		]);
		await Promise.all([
			store.setMembership(admin, 'first-org', 'alice', 'member'),
			restart().setMembership(admin, 'first-org', 'carol', 'member')
		]);
		expect((await store.list(admin)).map((entry) => entry.slug).sort()).toEqual([
			'first-org',
			'nasa-science',
			'second-org'
		]);
		expect((await store.members(admin, 'first-org')).map((entry) => entry.user.id).sort()).toEqual([
			'admin',
			'alice',
			'carol'
		]);
	});
	it('allows only one organization when concurrent creators choose the same realm', async () => {
		const { store, restart } = await fixture();
		const outcomes = await Promise.allSettled([
			store.create(admin, otherOrganization),
			restart().create(admin, { ...otherOrganization, slug: 'another-org' })
		]);
		expect(outcomes.filter((entry) => entry.status === 'fulfilled')).toHaveLength(1);
		expect(outcomes.filter((entry) => entry.status === 'rejected')).toEqual([
			expect.objectContaining({ reason: expect.objectContaining({ status: 409 }) })
		]);
		expect((await store.list(admin)).filter((entry) => entry.realm === 'SECOND')).toHaveLength(1);
	});
	it('rejects endpoint changes or duplicated stored realms without modifying organization metadata', async () => {
		const { store, path, options } = await fixture();
		await store.create(admin, otherOrganization);
		const original = await readFile(path, 'utf8');
		const different = new HuronOrganizationStore({
			...options,
			connection: { ...connection, realm: 'OTHER' }
		});
		await expect(different.list(admin)).rejects.toThrow('another Polaris endpoint or realm');
		const rebound = new HuronOrganizationStore({
			...options,
			connections: () =>
				connections.map((entry) =>
					entry.realm === 'SECOND' ? { ...entry, url: 'http://other:8181' } : entry
				)
		});
		await expect(rebound.list(admin)).rejects.toThrow('another Polaris endpoint');
		expect(await readFile(path, 'utf8')).toBe(original);
		const organization = {
			id: 'second',
			slug: 'second-org',
			name: 'Second',
			description: '',
			createdAt: '2026-10-13',
			members: [],
			realm: 'POLARIS',
			polarisUrl: connection.url
		};
		await writeFile(
			path,
			JSON.stringify({
				version: 2,
				upstream: connection,
				organizations: [{ ...organization, id: 'first', slug: 'first-org' }, organization]
			})
		);
		await expect(store.list(admin)).rejects.toThrow('Duplicate organization or Polaris realm');
	});
});

describe('organization and native realm discovery intersection', () => {
	const client = new PolarisClient({ ...connection, clientId: 'alice', clientSecret: 'private' });
	const secondClient = new PolarisClient({
		...connection,
		realm: 'SECOND',
		clientId: 'alice',
		clientSecret: 'private-second'
	});
	const nasaOrganization = {
		id: 'org',
		slug: 'nasa-science',
		name: 'NASA Science',
		description: '',
		createdAt: '2026-10-13',
		realm: 'POLARIS',
		role: 'member' as const,
		catalogNames: []
	};
	it('never queries a realm without organization membership even when catalog names match', async () => {
		vi.mocked(visibleCatalogs).mockResolvedValue(nasa);
		vi.spyOn(HuronOrganizationStore.prototype, 'list').mockResolvedValue([nasaOrganization]);
		expect((await organizationDirectory(alice, secondClient)).catalogs).toEqual([]);
		await expect(
			requireOrganizationCatalog(alice, secondClient, 'geoscience')
		).rejects.toMatchObject({ status: 404 });
		expect(visibleCatalogs).not.toHaveBeenCalled();
	});
	it('publishes only the selected realm projection and retains other membership roots', async () => {
		vi.mocked(visibleCatalogs).mockResolvedValue([nasa[0]]);
		vi.spyOn(HuronOrganizationStore.prototype, 'list').mockResolvedValue([
			nasaOrganization,
			{ ...nasaOrganization, id: 'second', slug: 'other-org', realm: 'SECOND' }
		]);
		const directory = await organizationDirectory(alice, client);
		expect(directory.catalogs).toEqual([nasa[0]]);
		expect(directory.organizations).toEqual([
			{ ...nasaOrganization, catalogNames: ['geoscience'] },
			expect.objectContaining({ realm: 'SECOND', catalogNames: [] })
		]);
		await expect(requireOrganizationCatalog(alice, client, 'heliophysics')).rejects.toMatchObject({
			status: 404
		});
		expect(await requireOrganizationCatalog(alice, client, 'geoscience')).toMatchObject({
			slug: 'nasa-science',
			realm: 'POLARIS'
		});
	});
	it('does not expose unconnected realm catalogs to global administrators', async () => {
		vi.mocked(visibleCatalogs).mockResolvedValue(nasa);
		vi.spyOn(HuronOrganizationStore.prototype, 'list').mockResolvedValue([]);
		expect((await organizationDirectory(admin, client)).catalogs).toEqual([]);
		expect(visibleCatalogs).not.toHaveBeenCalled();
	});
});
