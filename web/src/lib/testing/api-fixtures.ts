import type {
	AuditEntry,
	Catalog,
	Collection,
	Commit,
	FileRecord,
	Namespace,
	Organization,
	Page,
	SchemaEntry,
	WhoAmI
} from '$api/types';

export function organizationFixture(overrides: Partial<Organization> = {}): Organization {
	return {
		id: '0192f2a4-0000-7000-8000-000000000001',
		name: 'helio',
		display_name: 'Heliophysics Division',
		description: 'Sun and solar wind.',
		version: 1,
		created_at: '2026-10-01T09:00:00+00:00',
		created_by: 'sub-alice',
		catalog_count: 2,
		...overrides
	};
}

export function catalogFixture(overrides: Partial<Catalog> = {}): Catalog {
	return {
		id: '0192f2a4-0000-7000-8000-000000000101',
		name: 'heliophysics',
		organization: 'helio',
		display_name: 'Heliophysics',
		description: '',
		schema: { id: '0192f2a4-0000-7000-8000-000000000201', name: 'huron-base', version: 1 },
		version: 1,
		created_at: '2026-10-01T09:00:00+00:00',
		created_by: 'sub-bob',
		namespace_count: 4,
		...overrides
	};
}

export function namespaceFixture(overrides: Partial<Namespace> = {}): Namespace {
	return {
		id: '0192f2a4-0000-7000-8000-000000000301',
		identifier: 'heliophysics.solar-wind',
		catalog: 'heliophysics',
		organization: 'helio',
		name: 'solar-wind',
		path: 'solar-wind',
		parent: '',
		collections_allowed: false,
		version: 1,
		created_at: '2026-10-01T09:00:00+00:00',
		created_by: 'sub-carol',
		namespace_count: 2,
		collection_count: 0,
		disk_path: 'helio/heliophysics/solar-wind',
		...overrides
	};
}

export function collectionFixture(overrides: Partial<Collection> = {}): Collection {
	return {
		id: '0192f2a4-0000-7000-8000-000000000401',
		identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
		organization: 'helio',
		catalog: 'heliophysics',
		namespace: 'solar-wind.ace',
		name: 'mag-l2-2024',
		state: 'active',
		version: 3,
		metadata: { title: 'ACE magnetometer level 2, 2024', labels: { mission: 'ace' } },
		schema_override: null,
		schema: { id: '0192f2a4-0000-7000-8000-000000000201', name: 'huron-base', version: 1 },
		file_count: 3,
		created_at: '2026-10-02T09:00:00+00:00',
		created_by: 'sub-dave',
		updated_at: '2026-10-03T09:00:00+00:00',
		activated_at: '2026-10-02T09:05:00+00:00',
		path: 'helio/heliophysics/solar-wind/ace/mag-l2-2024',
		problems: [],
		...overrides
	};
}

export function fileFixture(overrides: Partial<FileRecord> = {}): FileRecord {
	return {
		rel_path: 'data/2024-01.cdf',
		size: 1_234_567,
		sha256: 'a'.repeat(64),
		recorded_at: '2026-10-03T09:00:00+00:00',
		recorded_by: 'sub-dave',
		commit_id: '0192f2a4-0000-7000-8000-000000000501',
		...overrides
	};
}

export function commitFixture(overrides: Partial<Commit> = {}): Commit {
	return {
		id: '0192f2a4-0000-7000-8000-000000000501',
		base_version: 1,
		new_version: 2,
		adds: 3,
		removes: 0,
		host: 'ws-17',
		message: 'First upload',
		actor: 'sub-dave',
		created_at: '2026-10-03T09:00:00+00:00',
		...overrides
	};
}

export function auditFixture(overrides: Partial<AuditEntry> = {}): AuditEntry {
	return {
		id: 7,
		at: '2026-10-03T09:00:00+00:00',
		actor: 'sub-dave',
		action: 'collection.commit',
		object_type: 'collection',
		object_id: '0192f2a4-0000-7000-8000-000000000401',
		catalog_id: '0192f2a4-0000-7000-8000-000000000101',
		organization_id: '0192f2a4-0000-7000-8000-000000000001',
		detail: { adds: 3, removes: 0, host: 'ws-17', message: 'First upload', version: 2 },
		...overrides
	};
}

export function schemaFixture(overrides: Partial<SchemaEntry> = {}): SchemaEntry {
	return {
		id: '0192f2a4-0000-7000-8000-000000000201',
		organization_id: null,
		scope: 'platform',
		name: 'huron-base',
		version: 1,
		extends_id: null,
		document: { type: 'object', required: ['title'] },
		created_at: '2026-10-01T09:00:00+00:00',
		created_by: 'sub-alice',
		...overrides
	};
}

export function whoamiFixture(overrides: Partial<WhoAmI> = {}): WhoAmI {
	return {
		subject: 'sub-erin',
		name: 'Erin Example',
		groups: ['helio-readers'],
		roles: [{ scope: 'catalog', scope_id: '0192f2a4-0000-7000-8000-000000000101', role: 'reader' }],
		...overrides
	};
}

export function pageFixture<T>(items: T[], nextCursor: string | null = null): Page<T> {
	return { items, next_cursor: nextCursor };
}

/** A JSON answer. */
export function jsonResponse(body: unknown, status = 200): Response {
	return jsonTextResponse(JSON.stringify(body), status);
}

/** A JSON answer as the API wrote it, for what `JSON.stringify` cannot write: int64 digits. */
export function jsonTextResponse(text: string, status = 200): Response {
	return new Response(text, { status, headers: { 'content-type': 'application/json' } });
}

/** An RFC 9457 problem answer as the API sends it. */
export function problemResponse(
	status: number,
	code: string,
	context: Record<string, unknown> = {},
	detail = 'the API explains'
): Response {
	return new Response(
		JSON.stringify({
			type: `https://huron.dev/problems/${code.toLowerCase()}`,
			title: code,
			status,
			detail,
			code,
			context,
			instance: '/api/v1/somewhere'
		}),
		{ status, headers: { 'content-type': 'application/problem+json' } }
	);
}

export interface FetchCall {
	url: string;
	init: RequestInit | undefined;
}

export type FetchAnswer = Response | Error | ((call: FetchCall) => Response | Promise<Response>);

/** A fetch that records its calls and answers from a queue (the last answer repeats). */
export function fakeFetch(...answers: FetchAnswer[]): { fetch: typeof fetch; calls: FetchCall[] } {
	const calls: FetchCall[] = [];
	const queue = [...answers];
	const fetcher: typeof fetch = async (input, init) => {
		const url = input instanceof URL ? input.href : typeof input === 'string' ? input : input.url;
		const call = { url, init };
		calls.push(call);
		const answer = queue.length > 1 ? queue.shift() : queue[0];
		if (answer === undefined) throw new Error(`no answer queued for ${url}`);
		if (answer instanceof Error) throw answer;
		if (typeof answer === 'function') return answer(call);
		return answer.clone();
	};
	return { fetch: fetcher, calls };
}

/** The API base URL the test environment of the server tests configures. */
export const TEST_API = 'http://127.0.0.1:8197/api/v1';

/**
 * A fetch that answers each API request by its path and query below `/api/v1`
 * (`/organizations?limit=500`). A request no route names is refused, and the test then sees
 * the API as unreachable, so assert on `calls` as well.
 */
export function fakeApi(routes: Readonly<Record<string, FetchAnswer>>): {
	fetch: typeof fetch;
	calls: FetchCall[];
} {
	return fakeFetch((call) => {
		const path = call.url.startsWith(TEST_API) ? call.url.slice(TEST_API.length) : call.url;
		const answer: FetchAnswer | undefined = routes[path];
		if (answer === undefined) throw new Error(`no route for the API request ${path}`);
		if (answer instanceof Error) throw answer;
		return typeof answer === 'function' ? answer(call) : answer.clone();
	});
}

/** The error undici throws when a kept-alive connection was reset. */
export function connectionReset(code = 'ECONNRESET'): TypeError {
	return new TypeError('fetch failed', { cause: Object.assign(new Error('socket'), { code }) });
}

/** A fetch answer that never arrives; it fails when the request's signal aborts. */
export function hangingAnswer(call: FetchCall): Promise<Response> {
	return new Promise((_, reject) => {
		const signal = call.init?.signal;
		if (!signal) return;
		signal.addEventListener('abort', () => reject(signal.reason));
	});
}
