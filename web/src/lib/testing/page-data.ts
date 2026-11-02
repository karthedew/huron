import * as devalue from 'devalue';

/**
 * Page data as SvelteKit sends it: inlined in the server-rendered page (`uneval`) and as
 * `__data.json` (`stringify`). Both throw on what a load must never return, such as an object
 * with its own `__proto__` key, which `JSON.parse` keeps from an API answer.
 */
export function serializePageData(data: unknown): string[] {
	return [devalue.uneval(data), devalue.stringify(data)];
}
