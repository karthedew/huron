/**
 * The headers every answer of the web carries, the documentation's included
 * (docs/web-design.md §3.5). The content security policy is not among them: SvelteKit writes the
 * application's (`kit.csp` in `svelte.config.js`), `docs.ts` the documentation's.
 */
export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
	'x-content-type-options': 'nosniff',
	'x-frame-options': 'DENY',
	'referrer-policy': 'same-origin'
};

/** Set `SECURITY_HEADERS` on `headers`. */
export function setSecurityHeaders(headers: Headers): void {
	for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value);
}
