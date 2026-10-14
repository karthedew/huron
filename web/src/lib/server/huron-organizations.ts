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
import { polarisRealms, polarisSettings } from './polaris-settings';

interface StoredOrganization extends HuronOrganization {
	members: { userId: string; role: HuronOrganizationRole }[];
	polarisUrl: string;
}
interface OrganizationDocument {
	version: 2;
	upstream: { url: string; realm: string };
	organizations: StoredOrganization[];
}
interface OrganizationStoreOptions {
	path: string;
	connection: { url: string; realm: string };
	connections: () => { url: string; realm: string }[];
	users: () => Promise<HuronUser[]>;
	catalogs: (realm: string) => Promise<PolarisCatalog[]>;
	assignments: (user: HuronUser, catalog: string, realm: string) => Promise<PolarisRole[]>;
	ensureIdentity: (userId: string, realm: string) => Promise<HuronUser>;
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
function decodeOrganization(
	value: unknown,
	legacy?: { url: string; realm: string }
): StoredOrganization {
	const item = record(value);
	if (!Array.isArray(item.members) || (legacy && !Array.isArray(item.catalogNames)))
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
		realm: legacy?.realm ?? text(item.realm),
		polarisUrl: legacy?.url ?? text(item.polarisUrl)
	};
}
function publicOrganization(value: StoredOrganization): HuronOrganization {
	return {
		id: value.id,
		slug: value.slug,
		name: value.name,
		description: value.description,
		createdAt: value.createdAt,
		realm: value.realm
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

/** Durable membership roots; each organization's catalogs belong to its native Polaris realm. */
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

	private configuredRealm(realm: string): { url: string; realm: string } {
		const connection = this.options.connections().find((entry) => entry.realm === realm);
		if (!connection)
			throw new PolarisInputError('Choose a configured Polaris realm for this deployment.');
		return connection;
	}

	private async readDocument(migrate = false): Promise<OrganizationDocument> {
		const decoded: unknown = JSON.parse(await readFile(this.options.path, 'utf8'));
		const value = record(decoded);
		const upstream = record(value.upstream);
		if ((value.version !== 1 && value.version !== 2) || !Array.isArray(value.organizations))
			throw new Error('Invalid Huron organization store.');
		if (
			upstream.url !== this.options.connection.url ||
			upstream.realm !== this.options.connection.realm
		)
			throw new Error(
				'Huron organization storage belongs to another Polaris endpoint or realm. Configure a separate organization store for this connection.'
			);
		if (value.version === 1 && value.organizations.length > 1)
			throw new Error(
				'Legacy organizations share one Polaris realm. Migrate each organization and its catalogs to a separate configured realm before upgrading; the organization store has not been changed.'
			);
		const organizations = value.organizations.map((entry: unknown) =>
			decodeOrganization(entry, value.version === 1 ? this.options.connection : undefined)
		);
		if (
			new Set(organizations.map((entry) => entry.id)).size !== organizations.length ||
			new Set(organizations.map((entry) => entry.slug)).size !== organizations.length ||
			new Set(organizations.map((entry) => entry.realm)).size !== organizations.length
		)
			throw new Error('Duplicate organization or Polaris realm in Huron organization storage.');
		for (const organization of organizations)
			if (this.configuredRealm(organization.realm).url !== organization.polarisUrl)
				throw new Error(
					'A Huron organization belongs to another Polaris endpoint. Restore its configured realm connection before continuing.'
				);
		const document: OrganizationDocument = {
			version: 2,
			upstream: this.options.connection,
			organizations
		};
		if (migrate && value.version === 1) await this.writeDocument(document);
		return document;
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
				const document = await this.readDocument(true);
				if (document.organizations.length) return;
			} catch (error) {
				if (!hasCode(error, 'ENOENT')) throw error;
			}
			const { realm } = this.options.connection;
			this.configuredRealm(realm);
			const [users, catalogs] = await Promise.all([
				this.options.users(),
				this.options.catalogs(realm)
			]);
			const members: StoredOrganization['members'] = [];
			for (const user of users) {
				if (user.isAdmin) {
					members.push({ userId: user.id, role: 'admin' });
					continue;
				}
				const assigned = await Promise.all(
					catalogs.map((catalog) => this.options.assignments(user, catalog.name, realm))
				);
				if (assigned.some((entries) => entries.length))
					members.push({ userId: user.id, role: 'member' });
			}
			const isNasa =
				catalogs.length > 0 && catalogs.every((catalog) => nasaCatalogs.has(catalog.name));
			await this.writeDocument({
				version: 2,
				upstream: this.options.connection,
				organizations: [
					{
						id: randomUUID(),
						slug: isNasa ? 'nasa-science' : 'workspace',
						name: isNasa ? 'NASA Science' : 'Huron workspace',
						description: '',
						createdAt: new Date().toISOString(),
						realm,
						polarisUrl: this.options.connection.url,
						members
					}
				]
			});
		});
	}

	/** Membership alone never discloses catalog names not granted by Polaris. */
	async list(
		actor: HuronUser,
		authorizedCatalogs: PolarisCatalog[] = [],
		realm?: string
	): Promise<HuronOrganizationSummary[]> {
		requireActive(actor);
		await this.initialize();
		if (authorizedCatalogs.length && !realm)
			throw new PolarisInputError('Catalog discovery requires an explicit Polaris realm.');
		return (await this.readDocument()).organizations.flatMap((organization) => {
			const role = organizationRole(actor, organization);
			return role
				? [
						{
							...publicOrganization(organization),
							role,
							catalogNames:
								organization.realm === realm
									? authorizedCatalogs.map((catalog) => catalog.name)
									: []
						}
					]
				: [];
		});
	}

	async get(actor: HuronUser, slug: string): Promise<HuronOrganizationSummary> {
		const organization = (await this.list(actor)).find((entry) => entry.slug === slug);
		if (!organization) throw new PolarisApiError(404);
		return organization;
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
	async catalogUsers(actor: HuronUser, catalog: string, realm: string): Promise<HuronUser[]> {
		await this.initialize();
		const document = await this.readDocument();
		const target = document.organizations.find((entry) => entry.realm === realm);
		if (!target) throw new PolarisApiError(404);
		const organization = requireOrganization(actor, document, target.slug);
		if (!(await this.options.catalogs(realm)).some((entry) => entry.name === catalog))
			throw new PolarisApiError(404);
		const users = await this.options.users();
		return actor.isAdmin
			? users
			: users.filter((user) => organization.members.some((member) => member.userId === user.id));
	}

	async create(
		actor: HuronUser,
		input: { slug: string; name: string; description: string; realm: string }
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
		const realm = input.realm.trim();
		const connection = this.configuredRealm(realm);
		await this.initialize();
		return this.locked(async () => {
			const document = await this.readDocument();
			if (document.organizations.some((entry) => entry.slug === slug))
				throw new PolarisApiError(409, 'That organization identifier is already in use.');
			if (document.organizations.some((entry) => entry.realm === realm))
				throw new PolarisApiError(409, 'That Polaris realm already belongs to an organization.');
			await this.options.catalogs(realm);
			await this.options.ensureIdentity(actor.id, realm);
			const organization: StoredOrganization = {
				id: randomUUID(),
				slug,
				...values,
				createdAt: new Date().toISOString(),
				members: [{ userId: actor.id, role: 'admin' }],
				realm,
				polarisUrl: connection.url
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
				const catalogs = await this.options.catalogs(organization.realm);
				const assignments = await Promise.all(
					catalogs.map((catalog) =>
						this.options.assignments(user, catalog.name, organization.realm)
					)
				);
				if (assignments.some((entries) => entries.length))
					throw new PolarisInputError(
						'Remove this person’s Polaris catalog roles in every catalog owned by this organization before removing organization membership.'
					);
			}
			organization.members = organization.members.filter((member) => member.userId !== user.id);
			if (selectedRole !== 'none') {
				await this.options.ensureIdentity(user.id, organization.realm);
				organization.members.push({ userId: user.id, role: selectedRole });
			}
			await this.writeDocument(document);
		});
	}

	/** Enrolls a target before a separately authorized Polaris catalog-role assignment. */
	async ensureMembershipForCatalog(
		actor: HuronUser,
		userId: string,
		catalog: string,
		realm: string
	): Promise<void> {
		await this.initialize();
		await this.locked(async () => {
			const document = await this.readDocument();
			const target = document.organizations.find((entry) => entry.realm === realm);
			if (!target)
				throw new PolarisInputError(
					'Connect this Polaris realm to an organization before adding catalog members.'
				);
			const organization = requireOrganization(actor, document, target.slug);
			if (!(await this.options.catalogs(realm)).some((entry) => entry.name === catalog))
				throw new PolarisApiError(404);
			const user = (await this.options.users()).find((entry) => entry.id === userId);
			if (!user || user.disabled) throw new PolarisInputError('Choose an active Huron account.');
			if (!organization.members.some((entry) => entry.userId === userId)) {
				requireOrganization(actor, document, target.slug, true);
				await this.options.ensureIdentity(userId, realm);
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
		connections: () => polarisRealms(),
		users: () => accountStore().listUsers(),
		catalogs: async (realm) => (await getBootstrapPolarisClient(realm)).catalogs(),
		ensureIdentity: (userId, realm) => accountStore().ensureRealmIdentity(userId, realm),
		assignments: async (user, catalog, realm) => {
			try {
				return await (
					await getBootstrapPolarisClient(realm)
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
	const organizations = await organizationStore().list(user);
	const realm = client.connection.realm;
	const member = organizations.find((entry) => entry.realm === realm);
	if (!member) return { organizations, catalogs: [] };
	const catalogs = await visibleCatalogs(user, client);
	return {
		organizations: organizations.map((entry) =>
			entry.realm === realm
				? { ...entry, catalogNames: catalogs.map((catalog) => catalog.name) }
				: entry
		),
		catalogs
	};
}

/** Huron membership is checked on every request, alongside the user's own Polaris authority. */
export async function requireOrganizationCatalog(
	user: HuronUser,
	client: PolarisClient,
	catalog: string
): Promise<HuronOrganizationSummary> {
	const directory = await organizationDirectory(user, client);
	const organization = directory.organizations.find(
		(entry) => entry.realm === client.connection.realm && entry.catalogNames.includes(catalog)
	);
	if (!organization) throw new PolarisApiError(404);
	return organization;
}
