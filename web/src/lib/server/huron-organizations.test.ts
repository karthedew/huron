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
const admin = user('admin', true);
const alice = user('alice');
const bob = user('bob');
const carol = user('carol');
function catalog(name: string): PolarisCatalog {
	return { name, type: 'INTERNAL', properties: {}, storageConfigInfo: { storageType: 'FILE' } };
}
const nasa = ['geoscience', 'heliophysics', 'international_space_station'].map(catalog);
async function fixture(initialCatalogs: PolarisCatalog[] = nasa) {
	const directory = await mkdtemp(join(tmpdir(), 'huron-organizations-'));
	directories.push(directory);
	const path = join(directory, 'organizations.json');
	let catalogs = initialCatalogs;
	let users = [admin, alice, bob, carol];
	const assignments = new Map<string, PolarisRole[]>([
		['alice/geoscience', [{ name: 'huron_reader', properties: {} }]],
		['bob/heliophysics', [{ name: 'huron_catalog_admin', properties: {} }]]
	]);
	const assignmentReader = vi.fn(
		async (user: HuronUser, catalog: string) => assignments.get(`${user.id}/${catalog}`) ?? []
	);
	const options = {
		path,
		connection,
		users: async () => users,
		catalogs: async () => catalogs,
		assignments: assignmentReader
	};
	return {
		path,
		store: new HuronOrganizationStore(options),
		restart: () => new HuronOrganizationStore(options),
		assignments,
		assignmentReader,
		setCatalogs: (value: PolarisCatalog[]) => (catalogs = value),
		setUsers: (value: HuronUser[]) => (users = value)
	};
}

afterEach(async () => {
	vi.restoreAllMocks();
	vi.clearAllMocks();
	await Promise.all(
		directories.splice(0).map((path) => rm(path, { recursive: true, force: true }))
	);
});

describe('Huron organization persistence and authority', () => {
	it('migrates NASA catalogs and existing memberships without promoting catalog administrators or exposing sibling catalogs', async () => {
		const { store, path, assignments } = await fixture();
		const originalAssignments = structuredClone([...assignments]);
		expect(await store.list(alice, [nasa[0]])).toEqual([
			expect.objectContaining({
				slug: 'nasa-science',
				name: 'NASA Science',
				role: 'member',
				catalogNames: ['geoscience']
			})
		]);
		expect(await store.list(bob, [nasa[1]])).toEqual([
			expect.objectContaining({ role: 'member', catalogNames: ['heliophysics'] })
		]);
		expect(await store.list(carol, nasa)).toEqual([]);
		expect(await store.list(admin, nasa)).toEqual([
			expect.objectContaining({ role: 'admin', catalogNames: nasa.map((entry) => entry.name) })
		]);
		expect([...assignments]).toEqual(originalAssignments);
		expect((await stat(path)).mode & 0o777).toBe(0o600);
		expect(await readFile(path, 'utf8')).not.toMatch(/password|clientSecret|polarisPrincipal/);
	});

	it('preserves organizations across restart and migrates non-NASA catalogs into a separate workspace', async () => {
		const { store, restart } = await fixture([...nasa, catalog('research')]);
		await store.update(admin, 'nasa-science', {
			name: 'NASA Programs',
			description: 'A persistent organization'
		});
		const reloaded = await restart().list(admin, [...nasa, catalog('research')]);
		expect(reloaded).toEqual([
			expect.objectContaining({
				slug: 'nasa-science',
				name: 'NASA Programs',
				description: 'A persistent organization'
			}),
			expect.objectContaining({ slug: 'workspace', catalogNames: ['research'] })
		]);
	});

	it('does not enroll later accounts or attach later upstream catalogs automatically', async () => {
		const { store, assignments, setCatalogs, assignmentReader } = await fixture();
		await store.initialize();
		const migrationReads = assignmentReader.mock.calls.length;
		assignments.set('carol/geoscience', [{ name: 'huron_reader', properties: {} }]);
		setCatalogs([...nasa, catalog('new_program')]);
		expect(await store.list(carol, nasa)).toEqual([]);
		expect(
			(await store.list(admin, [...nasa, catalog('new_program')]))[0].catalogNames
		).not.toContain('new_program');
		expect(assignmentReader).toHaveBeenCalledTimes(migrationReads);
	});

	it('keeps membership when catalog grants disappear but discloses no unavailable catalog names', async () => {
		const { store } = await fixture();
		expect(await store.list(alice, [])).toEqual([
			expect.objectContaining({ slug: 'nasa-science', role: 'member', catalogNames: [] })
		]);
	});

	it('scopes catalog membership candidates to the owning organization for ordinary catalog administrators', async () => {
		const { store } = await fixture();
		expect((await store.catalogUsers(bob, 'heliophysics')).map((entry) => entry.username)).toEqual([
			'admin',
			'alice',
			'bob'
		]);
		expect(
			(await store.catalogUsers(admin, 'heliophysics')).map((entry) => entry.username)
		).toContain('carol');
		await expect(store.catalogUsers(carol, 'heliophysics')).rejects.toMatchObject({ status: 404 });
		await expect(store.catalogUsers(bob, 'missing')).rejects.toMatchObject({ status: 404 });
	});

	it('allows explicit empty organizations and rejects duplicate identifiers or invalid fields', async () => {
		const { store } = await fixture([]);
		expect(await store.list(admin, [])).toEqual([]);
		const created = await store.create(admin, {
			slug: 'new-program',
			name: ' New program ',
			description: ' description '
		});
		expect(created).toMatchObject({
			slug: 'new-program',
			name: 'New program',
			description: 'description'
		});
		expect(await store.list(admin, [])).toEqual([
			expect.objectContaining({ ...created, role: 'admin', catalogNames: [] })
		]);
		await expect(
			store.create(admin, { slug: 'new-program', name: 'Duplicate', description: '' })
		).rejects.toMatchObject({ status: 409 });
		await expect(
			store.create(admin, { slug: '../unsafe', name: 'Unsafe', description: '' })
		).rejects.toThrow('identifier');
		await expect(store.update(admin, 'new-program', { name: '', description: '' })).rejects.toThrow(
			'name'
		);
	});

	it('conceals organizations from nonmembers and rejects member or disabled administration', async () => {
		const { store } = await fixture();
		await expect(store.members(carol, 'nasa-science')).rejects.toMatchObject({ status: 404 });
		await expect(
			store.update(carol, 'nasa-science', { name: 'Hidden', description: '' })
		).rejects.toMatchObject({ status: 404 });
		await expect(store.members(alice, 'nasa-science')).rejects.toMatchObject({ status: 403 });
		await expect(
			store.setMembership(alice, 'nasa-science', 'carol', 'member')
		).rejects.toMatchObject({ status: 403 });
		await expect(
			store.create(alice, { slug: 'new-program', name: 'New', description: '' })
		).rejects.toMatchObject({ status: 403 });
		await expect(store.assignCatalog(alice, 'nasa-science', 'geoscience')).rejects.toMatchObject({
			status: 403
		});
		await expect(store.list({ ...admin, disabled: true }, nasa)).rejects.toMatchObject({
			status: 403
		});
	});

	it('allows organization admins to manage their own members and name without granting Polaris access', async () => {
		const { store, assignments } = await fixture();
		await store.setMembership(admin, 'nasa-science', 'alice', 'admin');
		await store.update(alice, 'nasa-science', { name: 'NASA Research', description: '' });
		await store.setMembership(alice, 'nasa-science', 'carol', 'member');
		expect(await store.members(alice, 'nasa-science')).toEqual(
			expect.arrayContaining([{ user: carol, role: 'member' }])
		);
		expect(await store.list(carol, [])).toEqual([
			expect.objectContaining({ name: 'NASA Research', catalogNames: [] })
		]);
		expect(assignments.has('carol/geoscience')).toBe(false);
		await store.create(admin, { slug: 'other-org', name: 'Other', description: '' });
		await expect(store.setMembership(alice, 'other-org', 'bob', 'admin')).rejects.toMatchObject({
			status: 404
		});
	});

	it('requires explicit Polaris-role revocation before membership removal and never reseeds removed members', async () => {
		const { store, restart, assignments } = await fixture();
		await expect(store.setMembership(admin, 'nasa-science', 'alice', 'none')).rejects.toThrow(
			'Polaris catalog roles'
		);
		expect(await store.list(alice, [nasa[0]])).toHaveLength(1);
		assignments.delete('alice/geoscience');
		await store.setMembership(admin, 'nasa-science', 'alice', 'none');
		expect(await restart().list(alice, nasa)).toEqual([]);
		assignments.set('alice/geoscience', [{ name: 'huron_reader', properties: {} }]);
		expect(await restart().list(alice, nasa)).toEqual([]);
	});

	it('preserves default admin and rejects disabled users when assigning membership', async () => {
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

	it('moves catalog ownership once while retaining independent Polaris grants and target memberships', async () => {
		const { store, assignments } = await fixture();
		await store.create(admin, { slug: 'other-org', name: 'Other', description: '' });
		await store.assignCatalog(admin, 'other-org', 'geoscience');
		expect((await store.list(alice, [nasa[0]]))[0].catalogNames).toEqual([]);
		await store.setMembership(admin, 'other-org', 'alice', 'member');
		expect(await store.list(alice, [nasa[0]])).toEqual([
			expect.objectContaining({ slug: 'nasa-science', catalogNames: [] }),
			expect.objectContaining({ slug: 'other-org', catalogNames: ['geoscience'] })
		]);
		expect(assignments.get('alice/geoscience')).toEqual([{ name: 'huron_reader', properties: {} }]);
		await expect(store.assignCatalog(admin, 'other-org', 'missing')).rejects.toMatchObject({
			status: 404
		});
	});

	it('permits existing members during catalog-role changes but requires an org admin to enroll a new member', async () => {
		const { store } = await fixture();
		await expect(
			store.ensureMembershipForCatalog(bob, alice.id, 'heliophysics')
		).resolves.toBeUndefined();
		await expect(
			store.ensureMembershipForCatalog(bob, carol.id, 'heliophysics')
		).rejects.toMatchObject({ status: 403 });
		await store.ensureMembershipForCatalog(admin, carol.id, 'heliophysics');
		expect(await store.list(carol, [])).toEqual([
			expect.objectContaining({ role: 'member', catalogNames: [] })
		]);
		await store.setMembership(admin, 'nasa-science', 'alice', 'admin');
		await store.ensureMembershipForCatalog(admin, alice.id, 'heliophysics');
		expect((await store.list(alice, []))[0].role).toBe('admin');
	});

	it('serializes concurrent persisted changes without losing unrelated organizations or memberships', async () => {
		const { store, restart } = await fixture();
		await Promise.all([
			store.create(admin, { slug: 'first-org', name: 'First', description: '' }),
			restart().create(admin, { slug: 'second-org', name: 'Second', description: '' })
		]);
		await Promise.all([
			store.setMembership(admin, 'first-org', 'alice', 'member'),
			restart().setMembership(admin, 'first-org', 'carol', 'member')
		]);
		expect((await store.list(admin, [])).map((entry) => entry.slug).sort()).toEqual([
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

	it('atomically claims new catalogs for one organization while keeping retries and explicit transfers distinct', async () => {
		const { store, restart, setCatalogs } = await fixture([]);
		await store.create(admin, { slug: 'first-org', name: 'First', description: '' });
		await store.create(admin, { slug: 'second-org', name: 'Second', description: '' });
		const catalogs = [catalog('new-program')];
		setCatalogs(catalogs);
		const outcomes = await Promise.allSettled([
			store.claimCatalog(admin, 'first-org', 'new-program'),
			restart().claimCatalog(admin, 'second-org', 'new-program')
		]);
		expect(outcomes.filter((outcome) => outcome.status === 'fulfilled')).toHaveLength(1);
		expect(outcomes.filter((outcome) => outcome.status === 'rejected')).toEqual([
			expect.objectContaining({ reason: expect.objectContaining({ status: 409 }) })
		]);
		const owner = (await store.list(admin, catalogs)).find((entry) =>
			entry.catalogNames.includes('new-program')
		);
		expect(owner).toBeDefined();
		if (!owner) throw new Error('A successful catalog claim must have an owner.');
		await expect(restart().claimCatalog(admin, owner.slug, 'new-program')).resolves.toBeUndefined();
		const otherSlug = owner.slug === 'first-org' ? 'second-org' : 'first-org';
		await store.assignCatalog(admin, otherSlug, 'new-program');
		await expect(store.claimCatalog(admin, owner.slug, 'new-program')).rejects.toMatchObject({
			status: 409
		});
		expect(
			(await restart().list(admin, catalogs)).filter((entry) =>
				entry.catalogNames.includes('new-program')
			)
		).toEqual([expect.objectContaining({ slug: otherSlug })]);
	});

	it('fails closed on an endpoint mismatch without overwriting organization metadata', async () => {
		const { store, path } = await fixture();
		await store.initialize();
		const original = await readFile(path, 'utf8');
		const different = new HuronOrganizationStore({
			path,
			connection: { ...connection, realm: 'OTHER' },
			users: async () => [],
			catalogs: async () => [],
			assignments: async () => []
		});
		await expect(different.list(admin, nasa)).rejects.toThrow('another Polaris endpoint or realm');
		expect(await readFile(path, 'utf8')).toBe(original);
	});

	it('fails closed on duplicate catalog ownership instead of choosing an arbitrary organization', async () => {
		const { store, path } = await fixture();
		await store.initialize();
		const organization = {
			id: 'second',
			slug: 'second-org',
			name: 'Second',
			description: '',
			createdAt: '2026-10-13',
			members: [],
			catalogNames: ['geoscience']
		};
		await writeFile(
			path,
			JSON.stringify({
				version: 1,
				upstream: connection,
				organizations: [{ ...organization, id: 'first', slug: 'first-org' }, organization]
			})
		);
		await expect(store.list(admin, nasa)).rejects.toThrow('Duplicate ownership');
	});
});

describe('organization and Polaris discovery intersection', () => {
	const client = new PolarisClient({ ...connection, clientId: 'alice', clientSecret: 'private' });
	it('filters nonmember catalogs even when Polaris grants remain and rejects direct catalog access', async () => {
		vi.mocked(visibleCatalogs).mockResolvedValue(nasa);
		vi.spyOn(HuronOrganizationStore.prototype, 'list').mockResolvedValue([
			{
				id: 'org',
				slug: 'nasa-science',
				name: 'NASA Science',
				description: '',
				createdAt: '2026-10-13',
				role: 'member',
				catalogNames: ['geoscience']
			}
		]);
		expect((await organizationDirectory(alice, client)).catalogs).toEqual([nasa[0]]);
		await expect(requireOrganizationCatalog(alice, client, 'heliophysics')).rejects.toMatchObject({
			status: 404
		});
		expect(await requireOrganizationCatalog(alice, client, 'geoscience')).toMatchObject({
			slug: 'nasa-science'
		});
	});
	it('keeps unassigned upstream catalogs visible only in the global administrator directory', async () => {
		vi.mocked(visibleCatalogs).mockResolvedValue(nasa);
		vi.spyOn(HuronOrganizationStore.prototype, 'list').mockResolvedValue([]);
		expect((await organizationDirectory(admin, client)).catalogs).toEqual(nasa);
		expect((await organizationDirectory(alice, client)).catalogs).toEqual([]);
	});
});
