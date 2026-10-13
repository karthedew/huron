import { randomUUID } from 'node:crypto';
import { mkdir, open, readFile, rename, rm, type FileHandle } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { env } from '$env/dynamic/private';
import type { HuronUser, PolarisCatalog, PolarisRole } from '$api/types';
import type {
	HuronOrganization,
	HuronOrganizationDirectory,
	HuronOrganizationMember,
	HuronOrganizationRole,
	HuronOrganizationSummary
} from '$api/organization-types';
import { accountStore, getBootstrapPolarisClient } from './huron-accounts';
import { visibleCatalogs } from './polaris-catalogs';
import { PolarisApiError, type PolarisClient } from './polaris-client';
import { PolarisInputError } from './polaris-forms';
import { polarisSettings } from './polaris-settings';

interface StoredOrganization extends HuronOrganization {
	members: { userId: string; role: HuronOrganizationRole }[];
	catalogNames: string[];
}
interface OrganizationDocument {
	version: 1;
	upstream: { url: string; realm: string };
	organizations: StoredOrganization[];
}
interface OrganizationStoreOptions {
	path: string;
	connection: { url: string; realm: string };
	users: () => Promise<HuronUser[]>;
	catalogs: () => Promise<PolarisCatalog[]>;
	assignments: (user: HuronUser, catalog: string) => Promise<PolarisRole[]>;
}
const nasaCatalogs = new Set(['heliophysics', 'geoscience', 'international_space_station']);
function hasCode(error: unknown, code: string): boolean {
	return error instanceof Error && 'code' in error && error.code === code;
}
function record(value: unknown): Record<string, unknown> {
	if (!value || typeof value !== 'object' || Array.isArray(value))
		throw new Error('Invalid Huron organization store.');
	return Object.fromEntries(Object.entries(value));
}
function text(value: unknown, allowEmpty = false): string {
	if (typeof value !== 'string' || (!allowEmpty && !value))
		throw new Error('Invalid Huron organization store.');
	return value;
}
function role(value: unknown): HuronOrganizationRole {
	if (value !== 'member' && value !== 'admin') throw new Error('Invalid Huron organization role.');
	return value;
}
function decodeOrganization(value: unknown): StoredOrganization {
	const item = record(value);
	if (!Array.isArray(item.members) || !Array.isArray(item.catalogNames))
		throw new Error('Invalid Huron organization store.');
	const members = item.members.map((entry: unknown) => {
		const member = record(entry);
		return { userId: text(member.userId), role: role(member.role) };
	});
	if (new Set(members.map((member) => member.userId)).size !== members.length)
		throw new Error('Invalid duplicate Huron organization membership.');
	return {
		id: text(item.id),
		slug: text(item.slug),
		name: text(item.name),
		description: text(item.description, true),
		createdAt: text(item.createdAt),
		members,
		catalogNames: item.catalogNames.map((entry: unknown) => text(entry))
	};
}
function publicOrganization(value: StoredOrganization): HuronOrganization {
	return {
		id: value.id,
		slug: value.slug,
		name: value.name,
		description: value.description,
		createdAt: value.createdAt
	};
}
function organizationInput(input: { name: string; description: string }) {
	const name = input.name.trim();
	const description = input.description.trim();
	if (!name || name.length > 120)
		throw new PolarisInputError('Enter an organization name of 1–120 characters.');
	if (description.length > 1000)
		throw new PolarisInputError('Use an organization description of at most 1,000 characters.');
	return { name, description };
}
function requireActive(actor: HuronUser): void {
	if (actor.disabled) throw new PolarisApiError(403, 'An active Huron account is required.');
}
function organizationRole(
	actor: HuronUser,
	organization: StoredOrganization
): HuronOrganizationRole | undefined {
	return actor.isAdmin
		? 'admin'
		: organization.members.find((member) => member.userId === actor.id)?.role;
}
function requireOrganization(
	actor: HuronUser,
	document: OrganizationDocument,
	slug: string,
	manage = false
): StoredOrganization {
	requireActive(actor);
	const organization = document.organizations.find((entry) => entry.slug === slug);
	if (!organization || !organizationRole(actor, organization)) throw new PolarisApiError(404);
	if (manage && organizationRole(actor, organization) !== 'admin')
		throw new PolarisApiError(403, 'Organization administrator access is required.');
	return organization;
}

/** Durable Huron ownership and membership; Polaris remains authoritative for catalog grants. */
export class HuronOrganizationStore {
	constructor(private readonly options: OrganizationStoreOptions) {}

	private async locked<T>(operation: () => Promise<T>): Promise<T> {
		await mkdir(dirname(this.options.path), { recursive: true, mode: 0o700 });
		const lockPath = `${this.options.path}.lock`;
		const deadline = Date.now() + 60_000;
		let lock: FileHandle | undefined;
		while (!lock) {
			try {
				lock = await open(lockPath, 'wx', 0o600);
				await lock.writeFile(String(process.pid));
			} catch (error) {
				if (!hasCode(error, 'EEXIST')) {
					if (lock) {
						await lock.close();
						await rm(lockPath, { force: true });
					}
					throw error;
				}
				await this.recoverDeadLock(lockPath);
				if (Date.now() >= deadline)
					throw new PolarisApiError(503, 'Organization storage is busy. Retry shortly.');
				await setTimeout(50);
			}
		}
		try {
			return await operation();
		} finally {
			await lock.close();
			await rm(lockPath, { force: true });
		}
	}

	private async recoverDeadLock(path: string): Promise<void> {
		let recovery: FileHandle;
		try {
			recovery = await open(`${path}.recovery`, 'wx', 0o600);
		} catch (error) {
			if (hasCode(error, 'EEXIST')) return;
			throw error;
		}
		try {
			let pid: number;
			try {
				pid = Number(await readFile(path, 'utf8'));
			} catch (error) {
				if (hasCode(error, 'ENOENT')) return;
				throw error;
			}
			if (!Number.isSafeInteger(pid) || pid <= 0) return;
			try {
				process.kill(pid, 0);
			} catch (error) {
				if (hasCode(error, 'ESRCH')) await rm(path, { force: true });
			}
		} finally {
			await recovery.close();
			await rm(`${path}.recovery`, { force: true });
		}
	}

	private async readDocument(): Promise<OrganizationDocument> {
		const decoded: unknown = JSON.parse(await readFile(this.options.path, 'utf8'));
		const value = record(decoded);
		const upstream = record(value.upstream);
		if (value.version !== 1 || !Array.isArray(value.organizations))
			throw new Error('Invalid Huron organization store.');
		if (
			upstream.url !== this.options.connection.url ||
			upstream.realm !== this.options.connection.realm
		)
			throw new Error(
				'Huron organization storage belongs to another Polaris endpoint or realm. Configure a separate organization store for this connection.'
			);
		const organizations = value.organizations.map(decodeOrganization);
		const catalogs = organizations.flatMap((entry) => entry.catalogNames);
		if (
			new Set(organizations.map((entry) => entry.id)).size !== organizations.length ||
			new Set(organizations.map((entry) => entry.slug)).size !== organizations.length ||
			new Set(catalogs).size !== catalogs.length
		)
			throw new Error('Duplicate ownership in Huron organization storage.');
		return { version: 1, upstream: this.options.connection, organizations };
	}

	private async writeDocument(document: OrganizationDocument): Promise<void> {
		const temporary = `${this.options.path}.${randomUUID()}.tmp`;
		const file = await open(temporary, 'wx', 0o600);
		try {
			await file.writeFile(JSON.stringify(document, null, 2) + '\n');
			await file.sync();
			await file.close();
			await rename(temporary, this.options.path);
			const directory = await open(dirname(this.options.path), 'r');
			try {
				await directory.sync();
			} finally {
				await directory.close();
			}
		} finally {
			await file.close();
			await rm(temporary, { force: true });
		}
	}

	async initialize(): Promise<void> {
		await this.locked(async () => {
			try {
				await this.readDocument();
				return;
			} catch (error) {
				if (!hasCode(error, 'ENOENT')) throw error;
			}
			const [users, catalogs] = await Promise.all([this.options.users(), this.options.catalogs()]);
			const organizations: StoredOrganization[] = [];
			for (const seed of [
				{
					slug: 'nasa-science',
					name: 'NASA Science',
					include: (name: string) => nasaCatalogs.has(name)
				},
				{
					slug: 'workspace',
					name: 'Huron workspace',
					include: (name: string) => !nasaCatalogs.has(name)
				}
			]) {
				const catalogNames = catalogs.map((catalog) => catalog.name).filter(seed.include);
				if (!catalogNames.length) continue;
				const members: StoredOrganization['members'] = [];
				for (const user of users) {
					if (user.isAdmin) {
						members.push({ userId: user.id, role: 'admin' });
						continue;
					}
					const assigned = (
						await Promise.all(
							catalogNames.map((catalog) => this.options.assignments(user, catalog))
						)
					).flat();
					if (assigned.length)
						members.push({
							userId: user.id,
							role: 'member'
						});
				}
				organizations.push({
					id: randomUUID(),
					slug: seed.slug,
					name: seed.name,
					description: '',
					createdAt: new Date().toISOString(),
					catalogNames,
					members
				});
			}
			await this.writeDocument({ version: 1, upstream: this.options.connection, organizations });
		});
	}

	/** Membership alone never discloses catalog names not granted by Polaris. */
	async list(
		actor: HuronUser,
		authorizedCatalogs: PolarisCatalog[]
	): Promise<HuronOrganizationSummary[]> {
		requireActive(actor);
		await this.initialize();
		const available = new Set(authorizedCatalogs.map((catalog) => catalog.name));
		return (await this.readDocument()).organizations.flatMap((organization) => {
			const role = organizationRole(actor, organization);
			return role
				? [
						{
							...publicOrganization(organization),
							role,
							catalogNames: organization.catalogNames.filter((name) => available.has(name))
						}
					]
				: [];
		});
	}

	async members(actor: HuronUser, slug: string): Promise<HuronOrganizationMember[]> {
		await this.initialize();
		const organization = requireOrganization(actor, await this.readDocument(), slug, true);
		const users = await this.options.users();
		return organization.members.flatMap((member) => {
			const user = users.find((candidate) => candidate.id === member.userId);
			return user ? [{ user, role: member.role }] : [];
		});
	}

	/** Candidate people for catalog administration stay within the owning organization. */
	async catalogUsers(actor: HuronUser, catalog: string): Promise<HuronUser[]> {
		await this.initialize();
		const document = await this.readDocument();
		const target = document.organizations.find((entry) => entry.catalogNames.includes(catalog));
		if (!target) throw new PolarisApiError(404);
		const organization = requireOrganization(actor, document, target.slug);
		const users = await this.options.users();
		return actor.isAdmin
			? users
			: users.filter((user) => organization.members.some((member) => member.userId === user.id));
	}

	async create(
		actor: HuronUser,
		input: { slug: string; name: string; description: string }
	): Promise<HuronOrganization> {
		requireActive(actor);
		if (!actor.isAdmin)
			throw new PolarisApiError(
				403,
				'Huron administrator access is required to create organizations.'
			);
		const slug = input.slug.trim().toLowerCase();
		if (!/^[a-z][a-z0-9-]{1,62}[a-z0-9]$/.test(slug))
			throw new PolarisInputError(
				'Use an organization identifier of 3–64 lowercase letters, numbers or hyphens, beginning with a letter and ending with a letter or number.'
			);
		const values = organizationInput(input);
		await this.initialize();
		return this.locked(async () => {
			const document = await this.readDocument();
			if (document.organizations.some((entry) => entry.slug === slug))
				throw new PolarisApiError(409, 'That organization identifier is already in use.');
			const organization: StoredOrganization = {
				id: randomUUID(),
				slug,
				...values,
				createdAt: new Date().toISOString(),
				members: [{ userId: actor.id, role: 'admin' }],
				catalogNames: []
			};
			document.organizations.push(organization);
			await this.writeDocument(document);
			return publicOrganization(organization);
		});
	}

	async update(
		actor: HuronUser,
		slug: string,
		input: { name: string; description: string }
	): Promise<void> {
		const values = organizationInput(input);
		await this.initialize();
		await this.locked(async () => {
			const document = await this.readDocument();
			Object.assign(requireOrganization(actor, document, slug, true), values);
			await this.writeDocument(document);
		});
	}

	/** Changes Huron membership only; catalog roles and data access remain unchanged in Polaris. */
	async setMembership(
		actor: HuronUser,
		slug: string,
		username: string,
		selectedRole: HuronOrganizationRole | 'none'
	): Promise<void> {
		if (!['member', 'admin', 'none'].includes(selectedRole))
			throw new PolarisInputError('Choose Member, Organization admin or Remove membership.');
		await this.initialize();
		await this.locked(async () => {
			const document = await this.readDocument();
			const organization = requireOrganization(actor, document, slug, true);
			const users = await this.options.users();
			const user = users.find((candidate) => candidate.username === username.trim().toLowerCase());
			if (!user) throw new PolarisInputError('Enter the username of an existing Huron account.');
			if (user.disabled && selectedRole !== 'none')
				throw new PolarisInputError('Enable this account before adding organization membership.');
			if (user.isAdmin && selectedRole !== 'admin')
				throw new PolarisInputError(
					'The default Huron administrator retains organization administration.'
				);
			const previous = organization.members.find((member) => member.userId === user.id);
			if (
				previous?.role === 'admin' &&
				selectedRole !== 'admin' &&
				!organization.members.some(
					(member) =>
						member.userId !== user.id &&
						member.role === 'admin' &&
						users.some((candidate) => candidate.id === member.userId && !candidate.disabled)
				)
			)
				throw new PolarisInputError('Keep at least one active organization administrator.');
			if (selectedRole === 'none' && previous) {
				const assignments = await Promise.all(
					organization.catalogNames.map((catalog) => this.options.assignments(user, catalog))
				);
				if (assignments.some((entries) => entries.length))
					throw new PolarisInputError(
						'Remove this person’s Polaris catalog roles in every catalog owned by this organization before removing organization membership.'
					);
			}
			organization.members = organization.members.filter((member) => member.userId !== user.id);
			if (selectedRole !== 'none')
				organization.members.push({ userId: user.id, role: selectedRole });
			await this.writeDocument(document);
		});
	}

	/** Transfers catalog ownership without changing any Polaris role or grant. */
	async assignCatalog(actor: HuronUser, slug: string, catalog: string): Promise<void> {
		await this.setCatalogOwner(actor, slug, catalog, 'transfer');
	}

	/** Completes creation without adopting a catalog that another organization already owns. */
	async claimCatalog(actor: HuronUser, slug: string, catalog: string): Promise<void> {
		await this.setCatalogOwner(actor, slug, catalog, 'claim');
	}

	private async setCatalogOwner(
		actor: HuronUser,
		slug: string,
		catalog: string,
		operation: 'claim' | 'transfer'
	): Promise<void> {
		requireActive(actor);
		if (!actor.isAdmin)
			throw new PolarisApiError(
				403,
				'Huron administrator access is required to assign catalogs to organizations.'
			);
		await this.initialize();
		await this.locked(async () => {
			const document = await this.readDocument();
			const organization = requireOrganization(actor, document, slug, true);
			const owner = document.organizations.find((entry) => entry.catalogNames.includes(catalog));
			if (operation === 'claim' && owner && owner.id !== organization.id)
				throw new PolarisApiError(
					409,
					'This catalog already belongs to another organization. Use Assign catalog to move an existing catalog.'
				);
			if (!(await this.options.catalogs()).some((entry) => entry.name === catalog))
				throw new PolarisApiError(404);
			for (const entry of document.organizations)
				entry.catalogNames = entry.catalogNames.filter((name) => name !== catalog);
			organization.catalogNames.push(catalog);
			await this.writeDocument(document);
		});
	}

	/** Enrolls a target before a separately authorized Polaris catalog-role assignment. */
	async ensureMembershipForCatalog(
		actor: HuronUser,
		userId: string,
		catalog: string
	): Promise<void> {
		await this.initialize();
		await this.locked(async () => {
			const document = await this.readDocument();
			const target = document.organizations.find((entry) => entry.catalogNames.includes(catalog));
			if (!target)
				throw new PolarisInputError(
					'Assign this catalog to an organization before adding catalog members.'
				);
			const organization = requireOrganization(actor, document, target.slug);
			const user = (await this.options.users()).find((entry) => entry.id === userId);
			if (!user || user.disabled) throw new PolarisInputError('Choose an active Huron account.');
			if (!organization.members.some((entry) => entry.userId === userId)) {
				requireOrganization(actor, document, target.slug, true);
				organization.members.push({ userId, role: user.isAdmin ? 'admin' : 'member' });
				await this.writeDocument(document);
			}
		});
	}
}

let store: HuronOrganizationStore | undefined;
export function organizationStore(): HuronOrganizationStore {
	const repository = resolve(process.cwd(), basename(process.cwd()) === 'web' ? '..' : '.');
	const accounts = resolve(
		env.HURON_ACCOUNT_STORE || resolve(repository, '.local/huron/accounts.json')
	);
	return (store ??= new HuronOrganizationStore({
		path: resolve(env.HURON_ORGANIZATION_STORE || `${accounts}.organizations.json`),
		connection: polarisSettings(),
		users: () => accountStore().listUsers(),
		catalogs: async () => (await getBootstrapPolarisClient()).catalogs(),
		assignments: async (user, catalog) => {
			try {
				return await (
					await getBootstrapPolarisClient()
				).assignments(user.polarisPrincipalRole, catalog);
			} catch (error) {
				if (error instanceof PolarisApiError && error.status === 404) return [];
				throw error;
			}
		}
	}));
}

export async function organizationDirectory(
	user: HuronUser,
	client: PolarisClient
): Promise<HuronOrganizationDirectory> {
	const catalogs = await visibleCatalogs(user, client);
	const organizations = await organizationStore().list(user, catalogs);
	const allowed = new Set(organizations.flatMap((entry) => entry.catalogNames));
	return {
		organizations,
		catalogs: user.isAdmin ? catalogs : catalogs.filter((entry) => allowed.has(entry.name))
	};
}

/** Huron membership is checked on every request, alongside the user's own Polaris authority. */
export async function requireOrganizationCatalog(
	user: HuronUser,
	client: PolarisClient,
	catalog: string
): Promise<HuronOrganizationSummary> {
	const directory = await organizationDirectory(user, client);
	const organization = directory.organizations.find((entry) =>
		entry.catalogNames.includes(catalog)
	);
	if (!organization) throw new PolarisApiError(404);
	return organization;
}
