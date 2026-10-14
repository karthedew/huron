import {
	createCipheriv,
	createDecipheriv,
	randomBytes,
	randomUUID,
	scrypt,
	timingSafeEqual
} from 'node:crypto';
import { mkdir, open, readFile, rename, rm, type FileHandle } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { env } from '$env/dynamic/private';
import type { HuronUser } from '$api/types';
import { management, object, PolarisClient, type PolarisConnection } from './polaris-client';
import {
	polarisConfiguredConnection,
	polarisRealms,
	polarisRealmSettings,
	polarisSettings,
	type PolarisRealm
} from './polaris-settings';

interface PasswordHash {
	salt: string;
	hash: string;
}

interface EncryptedCredentials {
	iv: string;
	tag: string;
	value: string;
}

interface StoredIdentity extends PolarisRealm {
	credentials: EncryptedCredentials | null;
}

interface StoredAccount extends HuronUser {
	password: PasswordHash;
	identities: StoredIdentity[];
	authVersion: number;
}

interface AccountDocument {
	version: 2;
	upstream: { url: string; realm: string };
	accounts: StoredAccount[];
}

export interface AuthenticatedAccount {
	user: HuronUser;
	client: PolarisClient;
	clientId: string;
	authVersion: number;
}

interface AccountStoreOptions {
	path: string;
	connection: { url: string; realm: string };
	bootstrap: (realm?: string) => Promise<PolarisConnection>;
	realms?: () => PolarisRealm[];
	fetcher?: typeof fetch;
	initialPassword?: string;
}

export class HuronAccountError extends Error {}

function publicUser(account: StoredAccount): HuronUser {
	return {
		id: account.id,
		username: account.username,
		displayName: account.displayName,
		isAdmin: account.isAdmin,
		disabled: account.disabled,
		polarisPrincipal: account.polarisPrincipal,
		polarisPrincipalRole: account.polarisPrincipalRole,
		createdAt: account.createdAt
	};
}

function validateInput(input: { username: string; displayName: string; password: string }) {
	const username = input.username.trim().toLowerCase();
	if (!/^[a-z][a-z0-9_.-]{2,63}$/.test(username))
		throw new HuronAccountError(
			'Use a username of 3–64 characters beginning with a letter, followed by letters, numbers, dots, underscores or hyphens.'
		);
	if (!input.displayName.trim() || input.displayName.trim().length > 120)
		throw new HuronAccountError('Enter a display name of 1–120 characters.');
	validatePassword(input.password);
	return { ...input, username, displayName: input.displayName.trim() };
}

function validatePassword(password: string): void {
	if (password.length < 8 || password.length > 256)
		throw new HuronAccountError('Use a password of 8–256 characters.');
}

function derive(password: string, salt: string): Promise<Buffer> {
	return new Promise((accept, reject) => {
		scrypt(password, salt, 64, (error, result) => (error ? reject(error) : accept(result)));
	});
}

async function hashPassword(password: string): Promise<PasswordHash> {
	const salt = randomBytes(32).toString('base64url');
	return { salt, hash: (await derive(password, salt)).toString('base64url') };
}

async function matches(password: string, stored: PasswordHash): Promise<boolean> {
	const expected = Buffer.from(stored.hash, 'base64url');
	const actual = await derive(password, stored.salt);
	return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function text(value: unknown): string {
	if (typeof value !== 'string' || !value) throw new Error('Invalid Huron account store.');
	return value;
}

function flag(value: unknown): boolean {
	if (typeof value !== 'boolean') throw new Error('Invalid Huron account store.');
	return value;
}

function decodeCredentials(value: unknown): EncryptedCredentials | null {
	if (value === null) return null;
	const encrypted = object(value);
	return { iv: text(encrypted.iv), tag: text(encrypted.tag), value: text(encrypted.value) };
}

function decodeAccount(value: unknown, legacy?: PolarisRealm): StoredAccount {
	const item = object(value);
	const password = object(item.password);
	if (!legacy && !Array.isArray(item.identities)) throw new Error('Invalid Huron account store.');
	const identities = legacy
		? [{ ...legacy, credentials: decodeCredentials(item.credentials) }]
		: (Array.isArray(item.identities) ? item.identities : []).map((value: unknown) => {
				const identity = object(value);
				return {
					url: text(identity.url),
					realm: text(identity.realm),
					credentials: decodeCredentials(identity.credentials)
				};
			});
	if (new Set(identities.map((entry) => entry.realm)).size !== identities.length)
		throw new Error('Duplicate Polaris realm identity in Huron account store.');
	if (!Number.isSafeInteger(item.authVersion) || Number(item.authVersion) < 1)
		throw new Error('Invalid Huron account store.');
	return {
		id: text(item.id),
		username: text(item.username),
		displayName: text(item.displayName),
		isAdmin: flag(item.isAdmin),
		disabled: flag(item.disabled),
		polarisPrincipal: text(item.polarisPrincipal),
		polarisPrincipalRole: text(item.polarisPrincipalRole),
		createdAt: text(item.createdAt),
		authVersion: Number(item.authVersion),
		password: { salt: text(password.salt), hash: text(password.hash) },
		identities
	};
}

async function privateWrite(path: string, value: string | Buffer): Promise<void> {
	const temporary = `${path}.${randomUUID()}.tmp`;
	const file = await open(temporary, 'wx', 0o600);
	try {
		await file.writeFile(value);
		await file.sync();
		await file.close();
		await rename(temporary, path);
		const directory = await open(dirname(path), 'r');
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

function absent(error: unknown): boolean {
	return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

/** Local identities and private Polaris credentials survive server restarts. */
export class HuronAccountStore {
	constructor(private readonly options: AccountStoreOptions) {}

	get initialCredentialsPath(): string {
		return join(dirname(this.options.path), 'initial-admin.json');
	}

	async initialize(): Promise<void> {
		await this.locked(() => this.initializeUnlocked());
	}

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
				if (!(error instanceof Error && 'code' in error && error.code === 'EEXIST')) {
					if (lock) {
						await lock.close();
						await rm(lockPath, { force: true });
					}
					throw error;
				}
				await this.recoverDeadLock(lockPath);
				if (Date.now() >= deadline)
					throw new HuronAccountError('Account store is busy. Retry shortly.');
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
			if (error instanceof Error && 'code' in error && error.code === 'EEXIST') return;
			throw error;
		}
		try {
			let pid: number;
			try {
				pid = Number(await readFile(path, 'utf8'));
			} catch (error) {
				if (absent(error)) return;
				throw error;
			}
			if (!Number.isSafeInteger(pid) || pid <= 0) return;
			try {
				process.kill(pid, 0);
			} catch (error) {
				if (error instanceof Error && 'code' in error && error.code === 'ESRCH')
					await rm(path, { force: true });
			}
		} finally {
			await recovery.close();
			await rm(`${path}.recovery`, { force: true });
		}
	}

	private async initializeUnlocked(): Promise<void> {
		try {
			const decoded: unknown = JSON.parse(await readFile(this.options.path, 'utf8'));
			const value = object(decoded);
			if (value.version === 1) {
				const document = this.decodeDocument(value, true);
				for (const account of document.accounts) {
					for (const identity of account.identities) {
						if (identity.credentials)
							identity.credentials = await this.encrypt(
								await this.decrypt(identity.credentials, account.id),
								this.identityKey(account.id, identity)
							);
					}
				}
				await this.writeDocument(document);
			}
			await this.readDocument();
			return;
		} catch (error) {
			if (!absent(error)) throw error;
		}
		const bootstrap = await this.options.bootstrap();
		if (
			bootstrap.url !== this.options.connection.url ||
			bootstrap.realm !== this.options.connection.realm
		)
			throw new Error(
				'Bootstrap credentials do not match the configured Polaris endpoint and realm.'
			);
		const password = this.options.initialPassword || randomBytes(24).toString('base64url');
		validatePassword(password);
		const account: StoredAccount = {
			id: randomUUID(),
			username: 'admin',
			displayName: 'Huron administrator',
			isAdmin: true,
			disabled: false,
			polarisPrincipal: 'root',
			polarisPrincipalRole: 'service_admin',
			createdAt: new Date().toISOString(),
			password: await hashPassword(password),
			identities: [{ ...this.options.connection, credentials: null }],
			authVersion: 1
		};
		await this.key(true);
		await privateWrite(
			this.initialCredentialsPath,
			JSON.stringify({ username: account.username, password }, null, 2) + '\n'
		);
		await this.writeDocument({
			version: 2,
			upstream: this.options.connection,
			accounts: [account]
		});
	}

	private async readDocument(): Promise<AccountDocument> {
		const decoded: unknown = JSON.parse(await readFile(this.options.path, 'utf8'));
		return this.decodeDocument(object(decoded));
	}

	private decodeDocument(value: Record<string, unknown>, legacy = false): AccountDocument {
		const upstream = object(value.upstream);
		if (value.version !== (legacy ? 1 : 2) || !Array.isArray(value.accounts))
			throw new Error('Invalid Huron account store.');
		if (
			upstream.url !== this.options.connection.url ||
			upstream.realm !== this.options.connection.realm
		)
			throw new Error(
				'HURON_ACCOUNT_STORE belongs to another Polaris endpoint or realm. Configure a separate account store for this connection.'
			);
		const accounts = value.accounts.map((entry: unknown) =>
			decodeAccount(entry, legacy ? this.options.connection : undefined)
		);
		if (
			accounts.filter(
				(account) => account.isAdmin && account.username === 'admin' && !account.disabled
			).length !== 1 ||
			new Set(accounts.map((account) => account.username)).size !== accounts.length ||
			new Set(accounts.map((account) => account.id)).size !== accounts.length
		)
			throw new Error('Invalid Huron account store.');
		return { version: 2, upstream: this.options.connection, accounts };
	}

	private async writeDocument(document: AccountDocument): Promise<void> {
		await privateWrite(this.options.path, JSON.stringify(document, null, 2) + '\n');
	}

	private async key(create = false): Promise<Buffer> {
		const path = `${this.options.path}.key`;
		try {
			const key = await readFile(path);
			if (key.length !== 32) throw new Error('Invalid Huron account encryption key.');
			return key;
		} catch (error) {
			if (!absent(error)) throw error;
		}
		if (!create) throw new Error('Missing Huron account encryption key.');
		const key = randomBytes(32);
		await privateWrite(path, key);
		return key;
	}

	private async encrypt(credentials: { clientId: string; clientSecret: string }, id: string) {
		const iv = randomBytes(12);
		const cipher = createCipheriv('aes-256-gcm', await this.key(), iv);
		cipher.setAAD(Buffer.from(id));
		const value = Buffer.concat([
			cipher.update(JSON.stringify(credentials), 'utf8'),
			cipher.final()
		]);
		return {
			iv: iv.toString('base64url'),
			tag: cipher.getAuthTag().toString('base64url'),
			value: value.toString('base64url')
		};
	}

	private identityKey(id: string, connection: PolarisRealm): string {
		return JSON.stringify([id, connection.url, connection.realm]);
	}

	private realm(realm = this.options.connection.realm): PolarisRealm {
		const configured = (this.options.realms?.() ?? [this.options.connection]).find(
			(entry) => entry.realm === realm
		);
		if (!configured) throw new HuronAccountError('This Polaris realm is not configured.');
		return configured;
	}

	private async bootstrap(realm: string): Promise<PolarisConnection> {
		const settings = this.realm(realm);
		const connection = await this.options.bootstrap(realm);
		if (connection.url !== settings.url || connection.realm !== settings.realm)
			throw new Error('Bootstrap credentials do not match the selected Polaris realm.');
		return connection;
	}

	private async decrypt(encrypted: EncryptedCredentials, key: string) {
		const decipher = createDecipheriv(
			'aes-256-gcm',
			await this.key(),
			Buffer.from(encrypted.iv, 'base64url')
		);
		decipher.setAAD(Buffer.from(key));
		decipher.setAuthTag(Buffer.from(encrypted.tag, 'base64url'));
		const decoded: unknown = JSON.parse(
			Buffer.concat([
				decipher.update(Buffer.from(encrypted.value, 'base64url')),
				decipher.final()
			]).toString('utf8')
		);
		const credentials = object(decoded);
		return {
			clientId: text(credentials.clientId),
			clientSecret: text(credentials.clientSecret)
		};
	}

	private async connection(
		account: StoredAccount,
		realm = this.options.connection.realm
	): Promise<PolarisConnection> {
		const settings = this.realm(realm);
		if (account.isAdmin) return this.bootstrap(realm);
		const identity = account.identities.find(
			(entry) => entry.realm === settings.realm && entry.url === settings.url
		);
		if (!identity?.credentials)
			throw new HuronAccountError('This account has no identity in the selected Polaris realm.');
		return {
			...settings,
			...(await this.decrypt(identity.credentials, this.identityKey(account.id, identity)))
		};
	}

	/** Uses only this person's identity in the explicitly selected organization realm. */
	async polarisClient(id: string, realm: string): Promise<PolarisClient> {
		await this.initialize();
		const account = (await this.readDocument()).accounts.find((entry) => entry.id === id);
		if (!account || account.disabled)
			throw new HuronAccountError('An active Huron account is required.');
		return new PolarisClient(await this.connection(account, realm), this.options.fetcher);
	}

	async listUsers(): Promise<HuronUser[]> {
		await this.initialize();
		return (await this.readDocument()).accounts.map(publicUser);
	}

	async sessionUser(id: string, authVersion: number): Promise<HuronUser | null> {
		await this.initialize();
		const account = (await this.readDocument()).accounts.find((account) => account.id === id);
		return account && !account.disabled && account.authVersion === authVersion
			? publicUser(account)
			: null;
	}

	async authenticate(username: string, password: string): Promise<AuthenticatedAccount | null> {
		await this.initialize();
		const account = (await this.readDocument()).accounts.find(
			(account) => account.username === username.trim().toLowerCase()
		);
		const accepted = await matches(
			password.slice(0, 257),
			account?.password ?? { salt: 'unknown-user', hash: randomBytes(64).toString('base64url') }
		);
		if (!account || !accepted || account.disabled || password.length > 256) return null;
		const connection = await this.connection(account);
		const client = new PolarisClient(connection, this.options.fetcher);
		return {
			user: publicUser(account),
			client,
			clientId: connection.clientId,
			authVersion: account.authVersion
		};
	}

	private async provisionIdentity<T>(
		account: StoredAccount,
		realm: string,
		persist: (identity: StoredIdentity) => Promise<T>
	): Promise<T> {
		const settings = this.realm(realm);
		const client = new PolarisClient(await this.bootstrap(realm), this.options.fetcher);
		const principal = account.polarisPrincipal;
		const principalRole = account.polarisPrincipalRole;
		let createdPrincipal = false;
		let createdRole = false;
		try {
			const value = object(
				await client.request(management('principals'), 'POST', {
					principal: { name: principal, properties: { 'huron.username': account.username } },
					credentialRotationRequired: false
				})
			);
			createdPrincipal = true;
			const credentials = object(value.credentials);
			await client.request(management('principal-roles'), 'POST', {
				principalRole: {
					name: principalRole,
					properties: { 'huron.username': account.username },
					federated: false
				}
			});
			createdRole = true;
			await client.request(management('principals', principal, 'principal-roles'), 'PUT', {
				principalRole: { name: principalRole }
			});
			return await persist({
				...settings,
				credentials: await this.encrypt(
					{ clientId: text(credentials.clientId), clientSecret: text(credentials.clientSecret) },
					this.identityKey(account.id, settings)
				)
			});
		} catch (error) {
			const recorded = await this.readDocument()
				.then((current) =>
					current.accounts.some(
						(entry) =>
							entry.id === account.id &&
							entry.identities.some(
								(identity) => identity.realm === settings.realm && identity.url === settings.url
							)
					)
				)
				.catch(() => true);
			if (recorded)
				throw new HuronAccountError(
					'Account provisioning could not be confirmed. Refresh Users before retrying. Polaris identities were retained to preserve any account that was already saved.'
				);
			if (createdPrincipal)
				await client.request(management('principals', principal), 'DELETE').catch(() => undefined);
			if (createdRole)
				await client
					.request(management('principal-roles', principalRole), 'DELETE')
					.catch(() => undefined);
			throw error;
		}
	}

	/** Provision the person's own realm identity before organization/catalog onboarding. */
	async ensureRealmIdentity(id: string, realm: string): Promise<HuronUser> {
		return this.locked(async () => {
			await this.initializeUnlocked();
			const settings = this.realm(realm);
			const document = await this.readDocument();
			const account = document.accounts.find((entry) => entry.id === id);
			if (!account || account.disabled)
				throw new HuronAccountError('Choose an active Huron account.');
			if (account.isAdmin) {
				await this.bootstrap(realm);
				return publicUser(account);
			}
			const existing = account.identities.find((entry) => entry.realm === realm);
			if (existing) {
				if (existing.url !== settings.url || !existing.credentials)
					throw new HuronAccountError(
						'The stored Polaris realm identity does not match its connection.'
					);
				return publicUser(account);
			}
			return this.provisionIdentity(account, realm, async (identity) => {
				account.identities.push(identity);
				await this.writeDocument(document);
				return publicUser(account);
			});
		});
	}

	async createUser(raw: {
		username: string;
		displayName: string;
		password: string;
	}): Promise<HuronUser> {
		const input = validateInput(raw);
		return this.locked(async () => {
			await this.initializeUnlocked();
			const document = await this.readDocument();
			if (
				input.username === 'root' ||
				document.accounts.some((account) => account.username === input.username)
			)
				throw new HuronAccountError('That username is reserved or already in use.');
			const id = randomUUID();
			const account: StoredAccount = {
				id,
				username: input.username,
				displayName: input.displayName,
				isAdmin: false,
				disabled: false,
				polarisPrincipal: `huron-user-${id}`,
				polarisPrincipalRole: `huron-member-${id}`,
				createdAt: new Date().toISOString(),
				authVersion: 1,
				password: await hashPassword(input.password),
				identities: []
			};
			return this.provisionIdentity(account, this.options.connection.realm, async (identity) => {
				account.identities.push(identity);
				document.accounts.push(account);
				await this.writeDocument(document);
				return publicUser(account);
			});
		});
	}

	async resetPassword(id: string, password: string): Promise<void> {
		validatePassword(password);
		await this.locked(async () => {
			const document = await this.readDocument();
			const account = document.accounts.find((account) => account.id === id);
			if (!account) throw new HuronAccountError('Huron account not found.');
			account.password = await hashPassword(password);
			account.authVersion += 1;
			await this.writeDocument(document);
			if (account.isAdmin) await rm(this.initialCredentialsPath, { force: true });
		});
	}

	async setDisabled(id: string, disabled: boolean): Promise<void> {
		await this.locked(async () => {
			const document = await this.readDocument();
			const account = document.accounts.find((account) => account.id === id);
			if (!account) throw new HuronAccountError('Huron account not found.');
			if (account.isAdmin && disabled)
				throw new HuronAccountError('The default Huron administrator cannot be disabled.');
			account.disabled = disabled;
			account.authVersion += 1;
			await this.writeDocument(document);
		});
	}

	async changePassword(id: string, currentPassword: string, password: string): Promise<void> {
		validatePassword(password);
		if (currentPassword.length > 256)
			throw new HuronAccountError('Your current password is incorrect.');
		await this.locked(async () => {
			const document = await this.readDocument();
			const account = document.accounts.find((account) => account.id === id);
			if (!account || account.disabled || !(await matches(currentPassword, account.password)))
				throw new HuronAccountError('Your current password is incorrect.');
			account.password = await hashPassword(password);
			account.authVersion += 1;
			await this.writeDocument(document);
			if (account.isAdmin) await rm(this.initialCredentialsPath, { force: true });
		});
	}
}

function repositoryLocalFile(relative: string): string {
	return resolve(process.cwd(), basename(process.cwd()) === 'web' ? '..' : '.', relative);
}

async function bootstrapConnection(realm = polarisSettings().realm): Promise<PolarisConnection> {
	const settings = polarisRealmSettings(realm);
	const configured = polarisConfiguredConnection(realm);
	if (configured) return configured;
	const clientId = env.POLARIS_BOOTSTRAP_CLIENT_ID;
	const clientSecret = env.POLARIS_BOOTSTRAP_CLIENT_SECRET;
	if (clientId || clientSecret) {
		if (!clientId || !clientSecret)
			throw new Error('Configure both Polaris bootstrap client credentials.');
		return { ...settings, clientId, clientSecret };
	}
	const path =
		env.POLARIS_BOOTSTRAP_CREDENTIALS_FILE ||
		repositoryLocalFile('.local/polaris/credentials.json');
	const decoded: unknown = JSON.parse(await readFile(path, 'utf8'));
	const value = object(decoded);
	if (
		(value.url !== undefined && value.url !== settings.url) ||
		(value.realm !== undefined && value.realm !== settings.realm)
	)
		throw new Error('Bootstrap credentials file does not match POLARIS_URL and POLARIS_REALM.');
	const credentials = object(value.admin ?? value);
	return {
		...settings,
		clientId: text(credentials.clientId),
		clientSecret: text(credentials.clientSecret)
	};
}

let store: HuronAccountStore | undefined;

export function accountStore(): HuronAccountStore {
	return (store ??= new HuronAccountStore({
		path: resolve(env.HURON_ACCOUNT_STORE || repositoryLocalFile('.local/huron/accounts.json')),
		connection: polarisSettings(),
		realms: polarisRealms,
		bootstrap: bootstrapConnection,
		initialPassword: env.HURON_ADMIN_PASSWORD
	}));
}

export function registrationAllowed(): boolean {
	return env.HURON_ALLOW_SIGNUP === 'true';
}

/** Trusted administration and discovery directory; never use this for user data operations. */
export async function getBootstrapPolarisClient(realm?: string): Promise<PolarisClient> {
	return new PolarisClient(await bootstrapConnection(realm));
}
