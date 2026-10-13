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
import { polarisSettings } from './polaris-settings';

interface PasswordHash {
	salt: string;
	hash: string;
}

interface EncryptedCredentials {
	iv: string;
	tag: string;
	value: string;
}

interface StoredAccount extends HuronUser {
	password: PasswordHash;
	credentials: EncryptedCredentials | null;
	authVersion: number;
}

interface AccountDocument {
	version: 1;
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
	bootstrap: () => Promise<PolarisConnection>;
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

function decodeAccount(value: unknown): StoredAccount {
	const item = object(value);
	const password = object(item.password);
	const encrypted = item.credentials === null ? null : object(item.credentials);
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
		credentials: encrypted
			? { iv: text(encrypted.iv), tag: text(encrypted.tag), value: text(encrypted.value) }
			: null
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
			credentials: null,
			authVersion: 1
		};
		await this.key(true);
		await privateWrite(
			this.initialCredentialsPath,
			JSON.stringify({ username: account.username, password }, null, 2) + '\n'
		);
		await this.writeDocument({
			version: 1,
			upstream: this.options.connection,
			accounts: [account]
		});
	}

	private async readDocument(): Promise<AccountDocument> {
		const decoded: unknown = JSON.parse(await readFile(this.options.path, 'utf8'));
		const value = object(decoded);
		const upstream = object(value.upstream);
		if (value.version !== 1 || !Array.isArray(value.accounts))
			throw new Error('Invalid Huron account store.');
		if (
			upstream.url !== this.options.connection.url ||
			upstream.realm !== this.options.connection.realm
		)
			throw new Error(
				'HURON_ACCOUNT_STORE belongs to another Polaris endpoint or realm. Configure a separate account store for this connection.'
			);
		const accounts = value.accounts.map(decodeAccount);
		if (
			accounts.filter(
				(account) => account.isAdmin && account.username === 'admin' && !account.disabled
			).length !== 1 ||
			new Set(accounts.map((account) => account.username)).size !== accounts.length ||
			new Set(accounts.map((account) => account.id)).size !== accounts.length
		)
			throw new Error('Invalid Huron account store.');
		return { version: 1, upstream: this.options.connection, accounts };
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

	private async connection(account: StoredAccount): Promise<PolarisConnection> {
		if (account.isAdmin) return this.options.bootstrap();
		if (!account.credentials) throw new Error('Missing Polaris credentials for Huron account.');
		const encrypted = account.credentials;
		const decipher = createDecipheriv(
			'aes-256-gcm',
			await this.key(),
			Buffer.from(encrypted.iv, 'base64url')
		);
		decipher.setAAD(Buffer.from(account.id));
		decipher.setAuthTag(Buffer.from(encrypted.tag, 'base64url'));
		const decoded: unknown = JSON.parse(
			Buffer.concat([
				decipher.update(Buffer.from(encrypted.value, 'base64url')),
				decipher.final()
			]).toString('utf8')
		);
		const credentials = object(decoded);
		return {
			...this.options.connection,
			clientId: text(credentials.clientId),
			clientSecret: text(credentials.clientSecret)
		};
	}

	async listUsers(): Promise<HuronUser[]> {
		await this.initialize();
		return (await this.readDocument()).accounts.map(publicUser);
	}

	async sessionUser(id: string, authVersion: number): Promise<HuronUser | null> {
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
		await client.authenticate();
		return {
			user: publicUser(account),
			client,
			clientId: connection.clientId,
			authVersion: account.authVersion
		};
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
			const principal = `huron-user-${id}`;
			const principalRole = `huron-member-${id}`;
			const client = new PolarisClient(await this.options.bootstrap(), this.options.fetcher);
			let createdPrincipal = false;
			let createdRole = false;
			try {
				const value = object(
					await client.request(management('principals'), 'POST', {
						principal: { name: principal, properties: { 'huron.username': input.username } },
						credentialRotationRequired: false
					})
				);
				createdPrincipal = true;
				const credentials = object(value.credentials);
				await client.request(management('principal-roles'), 'POST', {
					principalRole: {
						name: principalRole,
						properties: { 'huron.username': input.username },
						federated: false
					}
				});
				createdRole = true;
				await client.request(management('principals', principal, 'principal-roles'), 'PUT', {
					principalRole: { name: principalRole }
				});
				const account: StoredAccount = {
					id,
					username: input.username,
					displayName: input.displayName,
					isAdmin: false,
					disabled: false,
					polarisPrincipal: principal,
					polarisPrincipalRole: principalRole,
					createdAt: new Date().toISOString(),
					authVersion: 1,
					password: await hashPassword(input.password),
					credentials: await this.encrypt(
						{ clientId: text(credentials.clientId), clientSecret: text(credentials.clientSecret) },
						id
					)
				};
				document.accounts.push(account);
				await this.writeDocument(document);
				return publicUser(account);
			} catch (error) {
				const recorded = await this.readDocument()
					.then((current) => current.accounts.some((account) => account.id === id))
					.catch(() => true);
				if (recorded)
					throw new HuronAccountError(
						'Account creation could not be confirmed. Refresh Users before retrying. Polaris identities were retained to preserve any account that was already saved.'
					);
				if (createdPrincipal)
					await client
						.request(management('principals', principal), 'DELETE')
						.catch(() => undefined);
				if (createdRole)
					await client
						.request(management('principal-roles', principalRole), 'DELETE')
						.catch(() => undefined);
				throw error;
			}
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

async function bootstrapConnection(): Promise<PolarisConnection> {
	const settings = polarisSettings();
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
		bootstrap: bootstrapConnection,
		initialPassword: env.HURON_ADMIN_PASSWORD
	}));
}

export function registrationAllowed(): boolean {
	return env.HURON_ALLOW_SIGNUP === 'true';
}

/** Trusted administration and discovery directory; never use this for user data operations. */
export async function getBootstrapPolarisClient(): Promise<PolarisClient> {
	return new PolarisClient(await bootstrapConnection());
}
