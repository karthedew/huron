/**
 * The catalog explorer's model: one level per namespace (the catalog root is the level of `''`),
 * where the page is in the tree, and which folders open. The server loads the levels on the way
 * to the current page; the explorer fetches others from `/catalogs/<catalog>/tree?parent=`.
 */
import type { Collection, Namespace, Page } from '$api/types';
import { match as isDottedPath } from '../params/dotted';
import { isRecord } from './json';

/** A namespace in the explorer: a folder. */
export interface ExplorerNamespace {
	name: string;
	/** The dotted path inside the catalog. */
	path: string;
	/** Whether it holds neither namespaces nor collections the user can see. */
	empty: boolean;
}

/** A collection in the explorer: a leaf. */
export interface ExplorerCollection {
	name: string;
	/** The full identifier, `catalog.namespace.path.name`. */
	identifier: string;
}

/**
 * The first page of a namespace's contents, or of the catalog root (`parent: ''`). The `…Next`
 * cursors say that more follow; the explorer then links to the page that lists them.
 */
export interface ExplorerLevel {
	parent: string;
	namespaces: ExplorerNamespace[];
	namespacesNext: string | null;
	collections: ExplorerCollection[];
	collectionsNext: string | null;
}

/**
 * A level on the way to a page that the server could not load: its folder says so and offers
 * to load it again, while the page itself still shows.
 */
export interface FailedLevel {
	parent: string;
	failed: true;
}

/** A level of a page's trail: loaded, or not. */
export type TrailLevel = ExplorerLevel | FailedLevel;

/** Whether a trail's level could not be loaded. */
export function isFailedLevel(level: TrailLevel): level is FailedLevel {
	return 'failed' in level;
}

/**
 * Where the page is in the catalog's tree. `overview`: the catalog's or the collection's overview
 * itself rather than one of its other tabs, whose node then marks its section, not the page.
 */
export type ExplorerCurrent =
	| { kind: 'catalog'; overview: boolean }
	| { kind: 'namespace'; path: string }
	| { kind: 'collection'; namespace: string; name: string; overview: boolean };

/** The node of a level on the way to the page, which its loaded page does not hold. */
export type PinnedNode =
	{ kind: 'namespace'; node: ExplorerNamespace } | { kind: 'collection'; node: ExplorerCollection };

const OVERVIEW_ROUTE = '/(app)/catalogs/[catalog=segment]/(overview)';
const NAMESPACE_ROUTE = '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]';
const COLLECTION_ROUTE = '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]';

/** A level from the API's first pages of a parent's namespaces and (not at the root) collections. */
export function explorerLevel(
	parent: string,
	namespaces: Page<Namespace>,
	collections: Page<Collection> | null
): ExplorerLevel {
	return {
		parent,
		namespaces: namespaces.items.map((namespace) => ({
			name: namespace.name,
			path: namespace.path,
			empty: namespace.namespace_count === 0 && namespace.collection_count === 0
		})),
		namespacesNext: namespaces.next_cursor ?? null,
		collections: (collections?.items ?? []).map((collection) => ({
			name: collection.name,
			identifier: collection.identifier
		})),
		collectionsNext: collections?.next_cursor ?? null
	};
}

/** Whether a level holds nothing at all. */
export function isEmptyLevel(level: ExplorerLevel): boolean {
	return (
		level.namespaces.length === 0 &&
		level.collections.length === 0 &&
		level.namespacesNext === null &&
		level.collectionsNext === null
	);
}

/** Whether a `parent` query value names a level: empty for the root, else a dotted path. */
export function isLevelParent(value: string): boolean {
	return value === '' || isDottedPath(value);
}

/** Every path from the top down to `path`: `deep.a.b` gives `deep`, `deep.a`, `deep.a.b`. */
export function pathPrefixes(path: string): string[] {
	if (path === '') return [];
	const segments = path.split('.');
	return segments.map((_, index) => segments.slice(0, index + 1).join('.'));
}

/** The path of the namespace that holds `path`; `''` for a top-level namespace. */
export function parentPath(path: string): string {
	const end = path.lastIndexOf('.');
	return end === -1 ? '' : path.slice(0, end);
}

/** The last segment of a dotted path or identifier. */
export function lastSegment(path: string): string {
	return path.slice(path.lastIndexOf('.') + 1);
}

/** Where a page of the catalog layout sits in the tree, from its route and parameters. */
export function explorerCurrent(
	routeId: string | null,
	params: { path?: string; identifier?: string }
): ExplorerCurrent {
	if (routeId === NAMESPACE_ROUTE && params.path) return { kind: 'namespace', path: params.path };
	if (routeId?.startsWith(COLLECTION_ROUTE) && params.identifier) {
		return {
			kind: 'collection',
			namespace: parentPath(params.identifier),
			name: lastSegment(params.identifier),
			overview: routeId === COLLECTION_ROUTE
		};
	}
	return { kind: 'catalog', overview: routeId === OVERVIEW_ROUTE };
}

/** The namespace the current node is in or is: `null` on the catalog's own pages. */
export function currentNamespace(current: ExplorerCurrent): string | null {
	if (current.kind === 'namespace') return current.path;
	if (current.kind === 'collection') return current.namespace;
	return null;
}

/** Whether a folder starts open: the catalog root, and every folder on the way to the page. */
export function opensByDefault(path: string, current: ExplorerCurrent): boolean {
	if (path === '') return true;
	const namespace = currentNamespace(current);
	return namespace !== null && (namespace === path || namespace.startsWith(`${path}.`));
}

/**
 * The node of this level on the way to the page, when the level's loaded page does not hold it:
 * the explorer still shows it, after the level's entries, so the way to the page and the page
 * itself always show in the tree. Below the current namespace's parent that is the next
 * namespace on the way; in a collection's namespace, the collection.
 */
export function pinnedNode(
	level: ExplorerLevel,
	catalog: string,
	current: ExplorerCurrent
): PinnedNode | null {
	const namespace = currentNamespace(current);
	if (namespace === null) return null;
	if (namespace === level.parent) {
		if (current.kind !== 'collection') return null;
		const identifier = `${catalog}.${current.namespace}.${current.name}`;
		if (level.collections.some((node) => node.identifier === identifier)) return null;
		return { kind: 'collection', node: { name: current.name, identifier } };
	}
	const prefix = level.parent === '' ? '' : `${level.parent}.`;
	if (!namespace.startsWith(prefix)) return null;
	const end = namespace.indexOf('.', prefix.length);
	const next = end === -1 ? namespace : namespace.slice(0, end);
	if (level.namespaces.some(({ path }) => path === next)) return null;
	return { kind: 'namespace', node: { name: lastSegment(next), path: next, empty: false } };
}

/** Whether the node is the page itself. */
export function isCurrentNamespace(path: string, current: ExplorerCurrent): boolean {
	return current.kind === 'namespace' && current.path === path;
}

/** Whether the leaf is the page itself. */
export function isCurrentCollection(
	identifier: string,
	catalog: string,
	current: ExplorerCurrent
): boolean {
	return (
		current.kind === 'collection' &&
		identifier === `${catalog}.${current.namespace}.${current.name}`
	);
}

/** A collection's identifier without its catalog, as the collection pages name it. */
export function identifierInCatalog(identifier: string): string {
	return identifier.slice(identifier.indexOf('.') + 1);
}

/** What fetching a level came to. */
export type LevelOutcome =
	| { kind: 'level'; level: ExplorerLevel }
	/** The session ended: the user must sign in again. */
	| { kind: 'signed-out' }
	| { kind: 'failed' };

/**
 * Fetch one level from the explorer's endpoint. Only a well-formed level of the requested parent
 * counts; any other answer, and a network failure, is a failure the user can retry.
 */
export async function fetchLevel(
	fetcher: typeof fetch,
	url: string,
	parent: string
): Promise<LevelOutcome> {
	let response: Response;
	try {
		response = await fetcher(url, {
			headers: { accept: 'application/json', 'x-huron-fetch': '1' }
		});
	} catch {
		return { kind: 'failed' };
	}
	if (response.status === 401) return { kind: 'signed-out' };
	if (!response.ok) return { kind: 'failed' };
	let body: unknown;
	try {
		body = await response.json();
	} catch {
		return { kind: 'failed' };
	}
	const level = parseLevel(body);
	return level !== null && level.parent === parent ? { kind: 'level', level } : { kind: 'failed' };
}

/** A level from the explorer endpoint's JSON, or `null` when it is not one. */
export function parseLevel(value: unknown): ExplorerLevel | null {
	if (!isRecord(value)) return null;
	const { parent, namespaces, namespacesNext, collections, collectionsNext } = value;
	if (typeof parent !== 'string' || !isLevelParent(parent)) return null;
	if (!isCursor(namespacesNext) || !isCursor(collectionsNext)) return null;
	const folders = listOf(namespaces, parseNamespace);
	const leaves = listOf(collections, parseCollection);
	if (folders === null || leaves === null) return null;
	return { parent, namespaces: folders, namespacesNext, collections: leaves, collectionsNext };
}

function parseNamespace(value: unknown): ExplorerNamespace | null {
	if (!isRecord(value)) return null;
	const { name, path, empty } = value;
	if (typeof name !== 'string' || typeof path !== 'string' || typeof empty !== 'boolean') {
		return null;
	}
	return isDottedPath(path) && lastSegment(path) === name ? { name, path, empty } : null;
}

function parseCollection(value: unknown): ExplorerCollection | null {
	if (!isRecord(value)) return null;
	const { name, identifier } = value;
	if (typeof name !== 'string' || typeof identifier !== 'string') return null;
	return isDottedPath(identifier) && lastSegment(identifier) === name ? { name, identifier } : null;
}

function listOf<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
	if (!Array.isArray(value)) return null;
	const items: T[] = [];
	for (const item of value) {
		const parsed = parse(item);
		if (parsed === null) return null;
		items.push(parsed);
	}
	return items;
}

function isCursor(value: unknown): value is string | null {
	return value === null || (typeof value === 'string' && value !== '');
}
