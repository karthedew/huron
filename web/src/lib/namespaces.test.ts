import { describe, expect, it } from 'vitest';
import { namespaceFixture } from '$lib/testing/api-fixtures';
import { namespaceContents, namespaceKind } from './namespaces';

describe('namespaceKind', () => {
	it('tells a namespace for collections from one for structure only', () => {
		expect(namespaceKind(namespaceFixture({ collections_allowed: true }))).toEqual({
			label: 'Holds collections',
			tone: 'accent'
		});
		expect(namespaceKind(namespaceFixture({ collections_allowed: false }))).toEqual({
			label: 'Structure only',
			tone: 'neutral'
		});
	});
});

describe('namespaceContents', () => {
	it('counts only the namespaces of a structure-only namespace', () => {
		const structure = namespaceFixture({ collections_allowed: false, namespace_count: 2 });
		expect(namespaceContents(structure)).toBe('2 namespaces');
		expect(namespaceContents({ ...structure, namespace_count: 0 })).toBe('0 namespaces');
	});

	it('counts the collections of a namespace for collections and its namespaces if any', () => {
		const holding = namespaceFixture({
			collections_allowed: true,
			namespace_count: 0,
			collection_count: 60
		});
		expect(namespaceContents(holding)).toBe('60 collections');
		expect(namespaceContents({ ...holding, collection_count: 1 })).toBe('1 collection');
		expect(namespaceContents({ ...holding, namespace_count: 1, collection_count: 0 })).toBe(
			'1 namespace · 0 collections'
		);
	});

	it('still counts collections a namespace holds after they were forbidden', () => {
		const legacy = namespaceFixture({
			collections_allowed: false,
			namespace_count: 0,
			collection_count: 3
		});
		expect(namespaceContents(legacy)).toBe('0 namespaces · 3 collections');
	});
});
