/** Collections as lists show them. */
import type { Collection } from '$api/types';
import { clip, shortened } from './format';
import { stringField } from './json';
import { sharePath } from './share';

/**
 * The longest title a collection's row or the head of its pages shows, in code points: what the
 * base schema allows. A draft's metadata need not satisfy it, and a schema override may lift it.
 */
export const TITLE_LENGTH = 200;

/**
 * The longest description the head of a collection's pages shows, in code points. The head
 * stands on every tab, and a description may take up a mebibyte; `metadata.json` holds it all.
 */
export const HEAD_DESCRIPTION_LENGTH = 5_000;

/**
 * A collection in a list, as plain values. Loads return rows rather than the API's collections:
 * the keys of metadata and labels are whatever contributors chose, and SvelteKit's serializer
 * refuses an object with its own `__proto__` key (which `JSON.parse` keeps), so one collection
 * could break the page for every viewer. A row also keeps the rest of the metadata on the server.
 */
export interface CollectionRow {
	id: string;
	name: string;
	/** The full identifier, `catalog.namespace.path.name`. */
	identifier: string;
	catalog: string;
	state: string;
	/** The metadata's title, shortened to `TITLE_LENGTH`; the collection's name when it has none. */
	title: string;
	fileCount: number;
	createdBy: string;
	createdAt: string;
	/** When the record last changed, as the API's ISO time. */
	updatedAt: string;
}

/** The row of a collection. */
export function collectionRow(collection: Collection): CollectionRow {
	return {
		id: collection.id,
		name: collection.name,
		identifier: collection.identifier,
		catalog: collection.catalog,
		state: collection.state,
		title: shortened(metadataTitle(collection.metadata) ?? collection.name, TITLE_LENGTH),
		fileCount: collection.file_count,
		createdBy: collection.created_by,
		createdAt: collection.created_at,
		updatedAt: collection.updated_at
	};
}

/**
 * A collection as the head of its pages and its Overview's details show it, as plain values;
 * its metadata stays on the server (see `CollectionRow`).
 */
export interface CollectionSummary {
	id: string;
	/** The full identifier, `catalog.namespace.path.name`. */
	identifier: string;
	catalog: string;
	state: string;
	/**
	 * The metadata's title and description, when they are text worth showing, shortened to
	 * `TITLE_LENGTH` and `HEAD_DESCRIPTION_LENGTH`.
	 */
	title: string | null;
	description: string | null;
	/** Whether the title or the description goes on beyond what the head shows. */
	shortened: boolean;
	fileCount: number;
	/** The record's revision (`version`): it counts changes to the record, not to the data. */
	revision: number;
	createdAt: string;
	createdBy: string;
	updatedAt: string;
	activatedAt: string | null;
	/**
	 * Where its directory is on the share (`<share root>/<path>`, else `<mount prefix>/<path>`);
	 * `null` for a draft.
	 */
	sharePath: string | null;
	/** The catalog's schema it validates against. */
	schema: { name: string; version: number };
	/** Whether its own schema override adds to the catalog's schema. */
	hasOverride: boolean;
	/**
	 * Whether that override no longer fits the catalog's schema (a later schema assignment can
	 * bring this about): then no schema can be resolved, and that is its only problem.
	 */
	overrideIncompatible: boolean;
}

/** The rule of the problem the API reports for a schema override that no longer fits. */
const INCOMPATIBLE_OVERRIDE = 'schema_incompatible';

/**
 * The summary of a collection. Its `path` is relative to its organization's `share_root` when the
 * API names one, else to `mountPrefix`, where the share is mounted as the CLI mounts it
 * (`HURON_WEB_MOUNT_PREFIX`); see `sharePath`.
 */
export function collectionSummary(collection: Collection, mountPrefix: string): CollectionSummary {
	const title = clipped(metadataTitle(collection.metadata), TITLE_LENGTH);
	const description = clipped(metadataDescription(collection.metadata), HEAD_DESCRIPTION_LENGTH);
	return {
		id: collection.id,
		identifier: collection.identifier,
		catalog: collection.catalog,
		state: collection.state,
		title: title?.text ?? null,
		description: description?.text ?? null,
		shortened: (title?.cut ?? false) || (description?.cut ?? false),
		fileCount: collection.file_count,
		revision: collection.version,
		createdAt: collection.created_at,
		createdBy: collection.created_by,
		updatedAt: collection.updated_at,
		activatedAt: collection.activated_at,
		sharePath:
			collection.path === null
				? null
				: sharePath(collection.share_root, mountPrefix, collection.path),
		schema: { name: collection.schema.name, version: collection.schema.version },
		hasOverride: collection.schema_override !== null,
		overrideIncompatible: collection.problems.some(({ rule }) => rule === INCOMPATIBLE_OVERRIDE)
	};
}

/** The title a collection's metadata gives it, unless it is missing, blank or not text. */
export function metadataTitle(metadata: Collection['metadata']): string | null {
	return shownText(stringField(metadata, 'title'));
}

/** The description a collection's metadata gives it, unless it is missing, blank or not text. */
export function metadataDescription(metadata: Collection['metadata']): string | null {
	return shownText(stringField(metadata, 'description'));
}

function shownText(text: string | null): string | null {
	return text !== null && text.trim() !== '' ? text : null;
}

function clipped(text: string | null, limit: number) {
	return text === null ? null : clip(text, limit);
}
