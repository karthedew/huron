import type { Cookies } from '@sveltejs/kit';
import type { CookieOptions } from '$lib/server/cookies';

export interface CookieWrite {
	name: string;
	/** `null` for a delete. */
	value: string | null;
	options: CookieOptions;
}

const SAME_SITE = { lax: 'Lax', strict: 'Strict', none: 'None' } as const;

/** An in-memory `Cookies` that records every write, for tests. */
export class FakeCookies implements Cookies {
	readonly values = new Map<string, string>();
	readonly writes: CookieWrite[] = [];
	#answered = false;

	constructor(initial: Record<string, string> = {}) {
		for (const [name, value] of Object.entries(initial)) this.values.set(name, value);
	}

	get(name: string): string | undefined {
		return this.values.get(name);
	}

	getAll(): Array<{ name: string; value: string }> {
		return [...this.values].map(([name, value]) => ({ name, value }));
	}

	set(name: string, value: string, options: CookieOptions): void {
		this.#refuseAfterAnswer();
		this.writes.push({ name, value, options });
		this.values.set(name, value);
	}

	delete(name: string, options: CookieOptions): void {
		this.#refuseAfterAnswer();
		this.writes.push({ name, value: null, options });
		this.values.delete(name);
	}

	/** The `set-cookie` value for the attributes the web uses, in the order SvelteKit writes them. */
	serialize(name: string, value: string, options: CookieOptions): string {
		const parts = [`${name}=${encodeURIComponent(value)}`];
		if (options.maxAge !== undefined) parts.push(`Max-Age=${options.maxAge}`);
		parts.push(`Path=${options.path}`);
		if (options.httpOnly) parts.push('HttpOnly');
		if (options.secure) parts.push('Secure');
		if (typeof options.sameSite === 'string') parts.push(`SameSite=${SAME_SITE[options.sameSite]}`);
		return parts.join('; ');
	}

	/** Behave like SvelteKit once the response exists: every later write throws. */
	answer(): void {
		this.#answered = true;
	}

	/** The last write to `name`, if any. */
	lastWrite(name: string): CookieWrite | undefined {
		return this.writes.findLast((write) => write.name === name);
	}

	#refuseAfterAnswer(): void {
		if (this.#answered) {
			throw new Error('Cannot use `cookies.set(...)` after the response has been generated');
		}
	}
}
