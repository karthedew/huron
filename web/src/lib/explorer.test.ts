import { describe, expect, it, vi } from 'vitest';
import {
	collectionFixture,
	jsonResponse,
	namespaceFixture,
	pageFixture
} from '$lib/testing/api-fixtures';
import {
	currentNamespace,
	explorerCurrent,
	explorerLevel,
	fetchLevel,
	identifierInCatalog,
	isCurrentCollection,
	isCurrentNamespace,
	isEmptyLevel,
	isLevelParent,
	lastSegment,
	opensByDefault,
	parentPath,
	parseLevel,
	pinnedNode,
	pathPrefixes,
	type ExplorerCurrent,
	type ExplorerLevel
} from './explorer';

const ACE: ExplorerLevel = {
	parent: 'solar-wind.ace',
	namespaces: [],
	namespacesNext: null,
	collections: [
		{ name: 'mag-l2-2024', identifier: 'heliophysics.solar-wind.ace.mag-l2-2024' },
		{ name: 'swepam-2024', identifier: 'heliophysics.solar-wind.ace.swepam-2024' }
	],
	collectionsNext: null
};

const SOLAR_WIND: ExplorerLevel = {
	parent: 'solar-wind',
	namespaces: [
		{ name: 'ace', path: 'solar-wind.ace', empty: false },
		{ name: 'wind', path: 'solar-wind.wind', empty: false }
	],
	namespacesNext: null,
	collections: [],
	collectionsNext: null
};

describe('explorerLevel', () => {
	it("keeps what the explorer shows of a parent's first pages", () => {
		const level = explorerLevel(
			'solar-wind',
			pageFixture(
				[
					namespaceFixture({
						name: 'ace',
						path: 'solar-wind.ace',
						namespace_count: 0,
						collection_count: 2
					}),
					namespaceFixture({
						name: 'empty',
						path: 'solar-wind.empty',
						namespace_count: 0,
						collection_count: 0
					})
				],
				'n2'
			),
			pageFixture([collectionFixture({ name: 'x', identifier: 'heliophysics.solar-wind.x' })])
		);
		expect(level).toEqual({
			parent: 'solar-wind',
			namespaces: [
				{ name: 'ace', path: 'solar-wind.ace', empty: false },
				{ name: 'empty', path: 'solar-wind.empty', empty: true }
			],
			namespacesNext: 'n2',
			collections: [{ name: 'x', identifier: 'heliophysics.solar-wind.x' }],
			collectionsNext: null
		});
	});

	it('has no collections at the catalog root', () => {
		const level = explorerLevel('', { items: [] }, null);
		expect(level).toEqual({
			parent: '',
			namespaces: [],
			namespacesNext: null,
			collections: [],
			collectionsNext: null
		});
		expect(isEmptyLevel(level)).toBe(true);
	});
});

describe('isEmptyLevel', () => {
	it('counts entries and further pages alike', () => {
		expect(isEmptyLevel(ACE)).toBe(false);
		expect(isEmptyLevel({ ...ACE, collections: [] })).toBe(true);
		expect(isEmptyLevel({ ...ACE, collections: [], collectionsNext: 'c' })).toBe(false);
		expect(isEmptyLevel({ ...ACE, collections: [], namespacesNext: 'n' })).toBe(false);
	});
});

describe('paths', () => {
	it('lists the prefixes from the top down', () => {
		expect(pathPrefixes('deep.a.b.c')).toEqual(['deep', 'deep.a', 'deep.a.b', 'deep.a.b.c']);
		expect(pathPrefixes('fields')).toEqual(['fields']);
		expect(pathPrefixes('')).toEqual([]);
	});

	it('names the parent and the last segment', () => {
		expect(parentPath('deep.a.b')).toBe('deep.a');
		expect(parentPath('deep')).toBe('');
		expect(lastSegment('deep.a.b')).toBe('b');
		expect(lastSegment('deep')).toBe('deep');
	});

	it('drops the catalog from an identifier', () => {
		expect(identifierInCatalog('heliophysics.solar-wind.ace.mag-l2-2024')).toBe(
			'solar-wind.ace.mag-l2-2024'
		);
		expect(identifierInCatalog('heliophysics.heliophysics.x')).toBe('heliophysics.x');
	});

	it('accepts the root and dotted paths as level parents', () => {
		expect(isLevelParent('')).toBe(true);
		expect(isLevelParent('solar-wind.ace')).toBe(true);
		for (const bad of ['.', 'a..b', 'A', 'a/b', '../x', 'a b', '%2e']) {
			expect(isLevelParent(bad), bad).toBe(false);
		}
	});
});

describe('explorerCurrent', () => {
	it('knows the overview from the other tabs of a catalog', () => {
		expect(explorerCurrent('/(app)/catalogs/[catalog=segment]/(overview)', {})).toEqual({
			kind: 'catalog',
			overview: true
		});
		expect(explorerCurrent('/(app)/catalogs/[catalog=segment]/(overview)/access', {})).toEqual({
			kind: 'catalog',
			overview: false
		});
		expect(explorerCurrent('/(app)/catalogs/[catalog=segment]/(overview)/search', {})).toEqual({
			kind: 'catalog',
			overview: false
		});
		expect(explorerCurrent(null, {})).toEqual({ kind: 'catalog', overview: false });
	});

	it('finds the namespace of a namespace page', () => {
		expect(
			explorerCurrent('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', {
				path: 'deep.a'
			})
		).toEqual({ kind: 'namespace', path: 'deep.a' });
	});

	it('finds the namespace and name of a collection page and its tabs', () => {
		for (const route of [
			'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]',
			'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/files'
		]) {
			expect(explorerCurrent(route, { identifier: 'solar-wind.ace.mag-l2-2024' })).toEqual({
				kind: 'collection',
				namespace: 'solar-wind.ace',
				name: 'mag-l2-2024',
				overview: !route.endsWith('/files')
			});
		}
	});
});

describe('opening folders', () => {
	const namespacePage: ExplorerCurrent = { kind: 'namespace', path: 'deep.a.b' };
	const collectionPage: ExplorerCurrent = {
		kind: 'collection',
		namespace: 'solar-wind.ace',
		name: 'x',
		overview: true
	};

	it('names the namespace the page is in', () => {
		expect(currentNamespace(namespacePage)).toBe('deep.a.b');
		expect(currentNamespace(collectionPage)).toBe('solar-wind.ace');
		expect(currentNamespace({ kind: 'catalog', overview: true })).toBeNull();
	});

	it('opens the root and every folder on the way to the page', () => {
		expect(opensByDefault('', { kind: 'catalog', overview: true })).toBe(true);
		for (const open of ['', 'deep', 'deep.a', 'deep.a.b']) {
			expect(opensByDefault(open, namespacePage), open).toBe(true);
		}
		for (const closed of ['deep.a.b.c', 'deep.ab', 'fields', 'de']) {
			expect(opensByDefault(closed, namespacePage), closed).toBe(false);
		}
		expect(opensByDefault('solar-wind', collectionPage)).toBe(true);
		expect(opensByDefault('solar-wind.ace', collectionPage)).toBe(true);
		expect(opensByDefault('solar-wind', { kind: 'catalog', overview: false })).toBe(false);
	});

	it('marks the current namespace and collection', () => {
		expect(isCurrentNamespace('deep.a.b', namespacePage)).toBe(true);
		expect(isCurrentNamespace('deep.a', namespacePage)).toBe(false);
		expect(
			isCurrentCollection('heliophysics.solar-wind.ace.x', 'heliophysics', collectionPage)
		).toBe(true);
		expect(
			isCurrentCollection('heliophysics.solar-wind.ace.y', 'heliophysics', collectionPage)
		).toBe(false);
		expect(isCurrentCollection('heliophysics.deep.a.b', 'heliophysics', namespacePage)).toBe(false);
	});
});

describe('pinnedNode', () => {
	it('pins nothing when the loaded page holds the current node', () => {
		expect(
			pinnedNode(SOLAR_WIND, 'heliophysics', { kind: 'namespace', path: 'solar-wind.ace' })
		).toBeNull();
		expect(
			pinnedNode(ACE, 'heliophysics', {
				kind: 'collection',
				namespace: 'solar-wind.ace',
				name: 'swepam-2024',
				overview: true
			})
		).toBeNull();
	});

	it('pins the current namespace when the loaded page does not hold it', () => {
		const firstPage = { ...SOLAR_WIND, namespacesNext: 'more' };
		expect(
			pinnedNode(firstPage, 'heliophysics', { kind: 'namespace', path: 'solar-wind.zeta' })
		).toEqual({
			kind: 'namespace',
			node: { name: 'zeta', path: 'solar-wind.zeta', empty: false }
		});
	});

	it('pins the current collection when the loaded page does not hold it', () => {
		expect(
			pinnedNode({ ...ACE, collectionsNext: 'more' }, 'heliophysics', {
				kind: 'collection',
				namespace: 'solar-wind.ace',
				name: 'zz-2030',
				overview: false
			})
		).toEqual({
			kind: 'collection',
			node: { name: 'zz-2030', identifier: 'heliophysics.solar-wind.ace.zz-2030' }
		});
	});

	it('pins the next namespace on the way when the loaded page does not hold it', () => {
		const current: ExplorerCurrent = { kind: 'namespace', path: 'zeta.b.c' };
		const root = { ...SOLAR_WIND, parent: '', namespacesNext: 'more' };
		expect(pinnedNode(root, 'heliophysics', current)).toEqual({
			kind: 'namespace',
			node: { name: 'zeta', path: 'zeta', empty: false }
		});
		const zeta = { ...SOLAR_WIND, parent: 'zeta', namespaces: [] };
		expect(pinnedNode(zeta, 'heliophysics', current)?.node).toEqual({
			name: 'b',
			path: 'zeta.b',
			empty: false
		});
		expect(
			pinnedNode(SOLAR_WIND, 'heliophysics', {
				kind: 'collection',
				namespace: 'solar-wind.zz',
				name: 'x',
				overview: true
			})?.node
		).toEqual({ name: 'zz', path: 'solar-wind.zz', empty: false });
	});

	it('pins nothing below the current namespace', () => {
		expect(
			pinnedNode(ACE, 'heliophysics', { kind: 'namespace', path: 'solar-wind.ace' })
		).toBeNull();
	});

	it('pins nothing into a level the current node is not in', () => {
		const elsewhere: ExplorerCurrent[] = [
			{ kind: 'namespace', path: 'solar-wind.wind.deeper' },
			{ kind: 'collection', namespace: 'solar-wind', name: 'x', overview: true },
			{ kind: 'catalog', overview: true }
		];
		for (const current of elsewhere) {
			expect(pinnedNode(ACE, 'heliophysics', current)).toBeNull();
		}
	});
});

describe('parseLevel', () => {
	it('accepts what the endpoint sends', () => {
		expect(parseLevel(JSON.parse(JSON.stringify(SOLAR_WIND)))).toEqual(SOLAR_WIND);
		expect(parseLevel({ ...ACE, collectionsNext: 'c2' })).toEqual({
			...ACE,
			collectionsNext: 'c2'
		});
	});

	it.each([
		['not an object', 'level'],
		['an array', []],
		['without a parent', { ...ACE, parent: undefined }],
		['with a malformed parent', { ...ACE, parent: 'a/b' }],
		['with an empty cursor', { ...ACE, collectionsNext: '' }],
		['with a numeric cursor', { ...ACE, namespacesNext: 3 }],
		['without lists', { ...ACE, collections: null }],
		['with a malformed folder', { ...SOLAR_WIND, namespaces: [{ name: 'ace', path: 'x.ace' }] }],
		[
			'with a folder named apart from its path',
			{ ...SOLAR_WIND, namespaces: [{ name: 'b', path: 'solar-wind.a', empty: true }] }
		],
		['with a malformed leaf', { ...ACE, collections: [{ name: 'x', identifier: '../x' }] }]
	])('refuses a body %s', (_, body) => {
		expect(parseLevel(body)).toBeNull();
	});
});

describe('fetchLevel', () => {
	it('asks the endpoint as a script and returns the level', async () => {
		const fetcher = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(SOLAR_WIND)));
		const outcome = await fetchLevel(fetcher, '/catalogs/h/tree?parent=solar-wind', 'solar-wind');
		expect(outcome).toEqual({ kind: 'level', level: SOLAR_WIND });
		expect(fetcher).toHaveBeenCalledWith('/catalogs/h/tree?parent=solar-wind', {
			headers: { accept: 'application/json', 'x-huron-fetch': '1' }
		});
	});

	it('reports an ended session', async () => {
		const fetcher = () => Promise.resolve(jsonResponse({ code: 'UNAUTHENTICATED' }, 401));
		expect(await fetchLevel(fetcher, '/t', 'solar-wind')).toEqual({ kind: 'signed-out' });
	});

	it.each([
		['an error status', () => Promise.resolve(jsonResponse({ code: 'UNAVAILABLE' }, 503))],
		['a network failure', () => Promise.reject(new TypeError('offline'))],
		['a body that is not JSON', () => Promise.resolve(new Response('<html>'))],
		['another level', () => Promise.resolve(jsonResponse(ACE))],
		['a body that is no level', () => Promise.resolve(jsonResponse({ items: [] }))]
	])('fails on %s', async (_, fetcher: typeof fetch) => {
		expect(await fetchLevel(fetcher, '/t', 'solar-wind')).toEqual({ kind: 'failed' });
	});
});
