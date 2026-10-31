import { expect } from '@playwright/test';
import {
	COLLECTIONS,
	NAMESPACES,
	RUN001_FILE_COUNT,
	USERNAMES,
	USERS,
	collection,
	collectionIdentifier,
	fileSha256,
	namespaceIdentifier,
	recordedFiles,
	searchMatches,
	visibleCatalogs,
	visibleOrganizations,
	type FixtureSearch
} from './support/fixture.mjs';
import { ApiSession, test } from './support/harness.ts';

// The other tests assert on fixture.mjs; these check that the API holds exactly that fixture.

test('each user sees the organizations and catalogs of the fixture', async () => {
	const exchangeable = USERNAMES.filter(
		(username) => USERS[username].special !== 'no-api-audience'
	);
	for (const username of exchangeable) {
		const api = await ApiSession.as(username);
		const organizations = await api.get('organizations?limit=500');
		expect(names(organizations.body), `${username}'s organizations`).toEqual(
			visibleOrganizations(username)
		);
		const catalogs = await api.get('catalogs?limit=500');
		expect(names(catalogs.body).sort(), `${username}'s catalogs`).toEqual(
			visibleCatalogs(username)
		);
	}
});

test('namespaces and collections are where the fixture puts them', async () => {
	const alice = await ApiSession.as('alice');
	for (const namespace of NAMESPACES) {
		const found = await alice.get(`catalogs/${namespace.catalog}/namespaces/${namespace.path}`);
		expect(found.status, namespaceIdentifier(namespace)).toBe(200);
		expect(found.body).toMatchObject({
			identifier: namespaceIdentifier(namespace),
			collections_allowed: namespace.collectionsAllowed,
			created_by: namespace.createdBy
		});
	}
	for (const expected of COLLECTIONS) {
		const identifier = collectionIdentifier(expected);
		const found = await alice.get(collectionPath(identifier));
		expect(found.status, identifier).toBe(200);
		expect(found.body, identifier).toMatchObject({
			identifier,
			state: expected.state,
			created_by: expected.createdBy,
			file_count: recordedFiles(expected).length
		});
	}
});

test('recorded files carry the fixture sizes and hashes', async () => {
	const erin = await ApiSession.as('erin');
	for (const identifier of [
		'heliophysics.solar-wind.ace.mag-l2-2024',
		'heliophysics.fields.run001'
	]) {
		const expected = collection(identifier);
		const found = await erin.get(collectionPath(identifier));
		const id = field(found.body, 'id');
		const files = await erin.get(`collections/${id}/files?limit=500`);
		const recorded = items(files.body).map((file) => ({
			relPath: field(file, 'rel_path'),
			size: field(file, 'size'),
			sha256: field(file, 'sha256')
		}));
		expect(recorded, identifier).toEqual(
			expect.arrayContaining(
				recordedFiles(expected).map(({ relPath, size }) => ({
					relPath,
					size,
					sha256: fileSha256(identifier, relPath)
				}))
			)
		);
		expect(recorded).toHaveLength(recordedFiles(expected).length);
	}
	expect(recordedFiles(collection('heliophysics.fields.run001'))).toHaveLength(RUN001_FILE_COUNT);
});

test('the catalog search finds what the fixture says it finds', async () => {
	const alice = await ApiSession.as('alice');
	const searches: Array<[string, FixtureSearch]> = [
		['heliophysics', { q: 'wind' }],
		['heliophysics', { q: 'WIND', states: ['active', 'incomplete', 'draft'] }],
		['heliophysics', { labels: { mission: 'wind' } }],
		['heliophysics', { labels: { level: 'l2' } }],
		['heliophysics', { q: 'ace', labels: { level: 'l2' } }],
		['heliophysics', { q: 'run' }],
		['heliophysics', { states: ['draft'] }],
		['space-weather', { states: ['incomplete'] }],
		['space-weather', {}],
		// What the organization searches of the tests find in each catalog.
		['space-weather', { q: 'run' }],
		['heliophysics', { q: '2024' }],
		['space-weather', { q: '2024' }],
		['space-weather', { q: 'wind' }],
		['geoscience', { q: 'ocean' }],
		['geoscience', { q: 'wind' }]
	];
	for (const [catalog, search] of searches) {
		const query = new URLSearchParams({ limit: '500' });
		if (search.q) query.append('q', search.q);
		for (const [key, value] of Object.entries(search.labels ?? {})) {
			query.append('label', `${key}=${value}`);
		}
		for (const state of search.states ?? []) query.append('state', state);
		const found = await alice.get(`catalogs/${catalog}/search?${query}`);
		expect(
			items(found.body).map((item) => field(item, 'identifier')),
			`${catalog} ${query}`
		).toEqual(searchMatches(catalog, search));
		expect(field(found.body, 'next_cursor')).toBeNull();
	}
	expect(searchMatches('heliophysics', { q: 'run' })).toHaveLength(60);
});

/** The API path of a collection by its full identifier (`catalog.namespace.name`). */
function collectionPath(identifier: string): string {
	const [catalog, ...rest] = identifier.split('.');
	return `catalogs/${catalog}/collections/${rest.join('.')}`;
}

/** The `items` of a page answer. */
function items(body: unknown): unknown[] {
	const value = field(body, 'items');
	if (!Array.isArray(value)) throw new Error('the answer has no items list');
	return value;
}

/** The `name` of every item of a page answer. */
function names(body: unknown): unknown[] {
	return items(body).map((item) => field(item, 'name'));
}

/** One field of a JSON object answer. */
function field(value: unknown, key: string): unknown {
	if (typeof value !== 'object' || value === null || !(key in value)) {
		throw new Error(`the answer has no ${key}`);
	}
	return Object.entries(value).find(([name]) => name === key)?.[1];
}
