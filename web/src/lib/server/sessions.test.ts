// @vitest-environment node
import * as devalue from 'devalue';
import { afterEach, describe, expect, it } from 'vitest';
import {
	EXPIRY_MARGIN_MS,
	SessionError,
	createSessionStore,
	sessionStore,
	type NewSession,
	type SessionStore
} from './sessions';

const START = Date.parse('2026-10-29T10:00:00Z');
const TOKEN_EXPIRY = '2026-10-29T18:00:00Z';

function newSession(overrides: Partial<NewSession> = {}): NewSession {
	return {
		huronToken: 'eyJhbGciOiJFUzI1NiJ9.huron-token-payload.signature',
		tokenExpiresAt: TOKEN_EXPIRY,
		subject: 'sub-erin',
		name: 'Erin Example',
		groups: ['helio-readers'],
		...overrides
	};
}

function store(options: { maxPerSubject?: number; maxTotal?: number } = {}) {
	const clock = { now: START };
	const sessions: SessionStore = createSessionStore({ ...options, now: () => clock.now });
	return { sessions, clock };
}

describe('session store', () => {
	it('creates a session under a fresh 32-byte id and returns the plain user', () => {
		const { sessions } = store();
		const first = sessions.create(newSession());
		const second = sessions.create(newSession());
		expect(first.id).toMatch(/^[A-Za-z0-9_-]{43}$/);
		expect(second.id).not.toBe(first.id);
		expect(sessions.user(first.id)).toEqual({
			subject: 'sub-erin',
			name: 'Erin Example',
			groups: ['helio-readers'],
			expiresAt: new Date(Date.parse(TOKEN_EXPIRY) - EXPIRY_MARGIN_MS).toISOString(),
			signedInAt: new Date(START).toISOString()
		});
		expect(sessions.token(first.id)).toBe(newSession().huronToken);
	});

	it('ends the session 30 s before the Huron token and sizes the cookie to match', () => {
		const { sessions, clock } = store();
		const created = sessions.create(newSession());
		const end = Date.parse(TOKEN_EXPIRY) - EXPIRY_MARGIN_MS;
		expect(created.maxAgeSeconds).toBe((end - START) / 1000);
		clock.now = end - 1;
		expect(sessions.token(created.id)).toBeDefined();
		clock.now = end;
		expect(sessions.user(created.id)).toBeUndefined();
		expect(sessions.token(created.id)).toBeUndefined();
		expect(sessions.size).toBe(0);
	});

	it('refuses a token that expires within the margin or has no valid expiry', () => {
		const { sessions } = store();
		const soon = new Date(START + EXPIRY_MARGIN_MS).toISOString();
		for (const tokenExpiresAt of [soon, 'not a date']) {
			expect(() => sessions.create(newSession({ tokenExpiresAt }))).toThrow(
				new SessionError('expired')
			);
		}
	});

	it('copies the groups so callers cannot change a session', () => {
		const { sessions } = store();
		const groups = ['a'];
		const { id } = sessions.create(newSession({ groups }));
		groups.push('b');
		sessions.user(id)?.groups.push('c');
		expect(sessions.user(id)?.groups).toEqual(['a']);
	});

	it('answers nothing for unknown ids and deletes idempotently', () => {
		const { sessions } = store();
		const { id } = sessions.create(newSession());
		expect(sessions.user('unknown')).toBeUndefined();
		sessions.delete(id);
		sessions.delete(id);
		sessions.delete('unknown');
		expect(sessions.token(id)).toBeUndefined();
		expect(sessions.size).toBe(0);
	});

	it('keeps at most ten sessions per subject by evicting that subject only', () => {
		const { sessions, clock } = store();
		const other = sessions.create(newSession({ subject: 'sub-dave' }));
		const ids: string[] = [];
		for (let index = 0; index < 11; index += 1) {
			clock.now += 1000;
			ids.push(sessions.create(newSession()).id);
		}
		expect(sessions.user(ids[0])).toBeUndefined();
		expect(ids.slice(1).every((id) => sessions.user(id) !== undefined)).toBe(true);
		expect(sessions.user(other.id)?.subject).toBe('sub-dave');
		expect(sessions.size).toBe(11);
	});

	it('refuses a new sign-in when full instead of evicting other users', () => {
		const { sessions } = store({ maxTotal: 2 });
		const first = sessions.create(newSession({ subject: 'a' }));
		const second = sessions.create(newSession({ subject: 'b' }));
		expect(() => sessions.create(newSession({ subject: 'c' }))).toThrow(
			new SessionError('capacity')
		);
		expect(sessions.user(first.id)).toBeDefined();
		expect(sessions.user(second.id)).toBeDefined();
	});

	it('sweeps expired sessions to make room before refusing', () => {
		const { sessions, clock } = store({ maxTotal: 2 });
		sessions.create(newSession({ subject: 'a', tokenExpiresAt: '2026-10-29T11:00:00Z' }));
		const kept = sessions.create(newSession({ subject: 'b' }));
		clock.now = Date.parse('2026-10-29T12:00:00Z');
		const created = sessions.create(newSession({ subject: 'c' }));
		expect(sessions.size).toBe(2);
		expect(sessions.user(kept.id)).toBeDefined();
		expect(sessions.user(created.id)).toBeDefined();
	});

	it('reports how many expired sessions a sweep dropped', () => {
		const { sessions, clock } = store();
		sessions.create(newSession({ tokenExpiresAt: '2026-10-29T11:00:00Z' }));
		sessions.create(newSession({ subject: 'other' }));
		clock.now = Date.parse('2026-10-29T12:00:00Z');
		expect(sessions.sweep()).toBe(1);
		expect(sessions.sweep()).toBe(0);
		expect(sessions.size).toBe(1);
	});

	it('serializes the user view without any credential', () => {
		const { sessions } = store();
		const session = newSession();
		const { id } = sessions.create(session);
		const user = sessions.user(id);
		for (const serialized of [devalue.stringify({ user }), devalue.uneval({ user })]) {
			expect(serialized).toContain('Erin Example');
			expect(serialized).not.toContain(session.huronToken);
			expect(serialized).not.toContain('huron-token-payload');
			expect(serialized).not.toContain(id);
		}
	});
});

describe('sessionStore', () => {
	afterEach(() => {
		globalThis.huronWebSessions?.stop();
		globalThis.huronWebSessions = undefined;
	});

	it('is one store per process, anchored on globalThis', () => {
		const store = sessionStore();
		expect(sessionStore()).toBe(store);
		expect(globalThis.huronWebSessions).toBe(store);
	});
});
