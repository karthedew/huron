import { randomBytes } from 'node:crypto';
import { clearInterval, setInterval } from 'node:timers';

/** What a request knows about its signed-in user: plain data, no credentials. */
export interface SessionUser {
	subject: string;
	name: string;
	/** The LDAP groups as of sign-in. */
	groups: string[];
	/** ISO 8601 UTC. */
	expiresAt: string;
	/** ISO 8601 UTC. */
	signedInAt: string;
}

/** A verified token exchange; everything comes from `ExchangeOut`, never from the ID token. */
export interface NewSession {
	huronToken: string;
	/** `ExchangeOut.expires_at`. */
	tokenExpiresAt: string;
	subject: string;
	name: string;
	groups: readonly string[];
}

export interface CreatedSession {
	id: string;
	maxAgeSeconds: number;
}

export type SessionErrorReason = 'capacity' | 'expired';

/** A session could not be created: the store is full or the token is (nearly) expired. */
export class SessionError extends Error {
	readonly reason: SessionErrorReason;

	constructor(reason: SessionErrorReason) {
		super(reason === 'capacity' ? 'the session store is full' : 'the Huron token expires too soon');
		this.name = 'SessionError';
		this.reason = reason;
	}
}

export interface SessionStore {
	/** Store a new session under a fresh random id; throws `SessionError`. */
	create(session: NewSession): CreatedSession;
	/** The plain user view of a live session. */
	user(id: string): SessionUser | undefined;
	/** The Huron token of a live session. Only the API guard calls this. */
	token(id: string): string | undefined;
	delete(id: string): void;
	/** Drop expired sessions; returns how many were dropped. */
	sweep(): number;
	readonly size: number;
	/** Stop the sweep timer. */
	stop(): void;
}

export interface SessionStoreOptions {
	maxPerSubject?: number;
	maxTotal?: number;
	now?: () => number;
	/** 0 disables the background sweep. */
	sweepIntervalMs?: number;
}

/** Sessions end this long before the Huron token, so no request carries an expiring token. */
export const EXPIRY_MARGIN_MS = 30_000;

/** An in-memory store. Sessions are per process and die on restart. */
export function createSessionStore(options: SessionStoreOptions = {}): SessionStore {
	return new MemorySessionStore(options);
}

declare global {
	// Anchored on globalThis so that Vite's module reloads keep everyone signed in.
	var huronWebSessions: SessionStore | undefined;
}

/** The store of this process. */
export function sessionStore(): SessionStore {
	globalThis.huronWebSessions ??= createSessionStore({ sweepIntervalMs: 60_000 });
	return globalThis.huronWebSessions;
}

interface SessionRecord {
	id: string;
	huronToken: string;
	expiresAt: number;
	subject: string;
	name: string;
	groups: string[];
	createdAt: number;
}

class MemorySessionStore implements SessionStore {
	readonly #records = new Map<string, SessionRecord>();
	/** Session ids per subject, oldest first. */
	readonly #bySubject = new Map<string, string[]>();
	readonly #maxPerSubject: number;
	readonly #maxTotal: number;
	readonly #now: () => number;
	readonly #timer: ReturnType<typeof setInterval> | undefined;

	constructor({
		maxPerSubject = 10,
		maxTotal = 10_000,
		now = Date.now,
		sweepIntervalMs = 0
	}: SessionStoreOptions) {
		this.#maxPerSubject = Math.max(1, maxPerSubject);
		this.#maxTotal = maxTotal;
		this.#now = now;
		if (sweepIntervalMs > 0) {
			this.#timer = setInterval(() => this.sweep(), sweepIntervalMs);
			this.#timer.unref();
		}
	}

	get size(): number {
		return this.#records.size;
	}

	create(session: NewSession): CreatedSession {
		const now = this.#now();
		const expiresAt = Date.parse(session.tokenExpiresAt) - EXPIRY_MARGIN_MS;
		if (!Number.isFinite(expiresAt) || expiresAt <= now) throw new SessionError('expired');
		let owned = this.#owned(session.subject);
		while (owned.length >= this.#maxPerSubject) {
			this.delete(owned[0]);
			owned = this.#owned(session.subject);
		}
		if (this.#records.size >= this.#maxTotal) this.sweep();
		if (this.#records.size >= this.#maxTotal) throw new SessionError('capacity');

		let id = randomBytes(32).toString('base64url');
		while (this.#records.has(id)) id = randomBytes(32).toString('base64url');
		this.#records.set(id, {
			id,
			huronToken: session.huronToken,
			expiresAt,
			subject: session.subject,
			name: session.name,
			groups: [...session.groups],
			createdAt: now
		});
		this.#bySubject.set(session.subject, [...this.#owned(session.subject), id]);
		return { id, maxAgeSeconds: Math.max(1, Math.floor((expiresAt - now) / 1000)) };
	}

	user(id: string): SessionUser | undefined {
		const record = this.#live(id);
		if (record === undefined) return undefined;
		return {
			subject: record.subject,
			name: record.name,
			groups: [...record.groups],
			expiresAt: new Date(record.expiresAt).toISOString(),
			signedInAt: new Date(record.createdAt).toISOString()
		};
	}

	token(id: string): string | undefined {
		return this.#live(id)?.huronToken;
	}

	delete(id: string): void {
		const record = this.#records.get(id);
		if (record === undefined) return;
		this.#records.delete(id);
		const remaining = this.#owned(record.subject).filter((owned) => owned !== id);
		if (remaining.length === 0) this.#bySubject.delete(record.subject);
		else this.#bySubject.set(record.subject, remaining);
	}

	sweep(): number {
		const now = this.#now();
		let dropped = 0;
		for (const record of [...this.#records.values()]) {
			if (record.expiresAt <= now) {
				this.delete(record.id);
				dropped += 1;
			}
		}
		return dropped;
	}

	stop(): void {
		if (this.#timer !== undefined) clearInterval(this.#timer);
	}

	#owned(subject: string): string[] {
		return this.#bySubject.get(subject) ?? [];
	}

	#live(id: string): SessionRecord | undefined {
		const record = this.#records.get(id);
		if (record === undefined) return undefined;
		if (record.expiresAt <= this.#now()) {
			this.delete(id);
			return undefined;
		}
		return record;
	}
}
