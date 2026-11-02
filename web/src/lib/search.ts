/**
 * The search model the catalog search, the organization search and the header box share: a
 * search as its address holds it, read and checked the way the API checks it, written back in
 * one canonical form, the changes links make to it, the API request it makes and its results as
 * plain rows. It runs on both sides: the server reads the address, the browser tidies what a form
 * submits. It knows no routes: `search-links.ts` gives the addresses of the pages that search.
 *
 * The API (`GET /catalogs/{catalog}/search`) matches `q` as one piece of text, case-insensitively,
 * in the identifier, the title and the description; each label filter must equal a label exactly;
 * the states default to active and incomplete, and drafts count only for those who may create
 * collections in the catalog. Results come sorted by identifier, a keyset page at a time.
 */
import type { Collection } from '$api/types';
import { match as isDottedPath } from '../params/dotted';
import { TITLE_LENGTH, metadataDescription, metadataTitle } from './collections';
import { formatCount, shortened } from './format';
import { isRecord, ownValue } from './json';
import { labelChips, MAX_LABEL_LENGTH, type LabelChip } from './metadata';
import { SEARCH_PAGE_SIZE } from './paging';

/** The states a search can include, in the order the address and the form list them. */
export const SEARCH_STATES = ['active', 'incomplete', 'draft'] as const;
export type SearchState = (typeof SEARCH_STATES)[number];

/** The states a search includes when its address names none: what the API searches by default. */
export const DEFAULT_STATES: readonly SearchState[] = ['active', 'incomplete'];

/** How the form and the results name each state. */
export const STATE_NAMES: Readonly<Record<SearchState, string>> = {
	active: 'Active',
	incomplete: 'Incomplete',
	draft: 'Draft'
};

/**
 * The longest search text the API accepts, in code points: Python counts a string's length so.
 * An `<input maxlength>` counts UTF-16 code units instead, so it never lets more through, but a
 * hand-made address can.
 */
export const MAX_TEXT_LENGTH = 200;

/** One label filter: collections whose `labels` hold `key` with exactly this `value`. */
export interface LabelFilter {
	key: string;
	value: string;
}

/** A search, read and checked. */
export interface Search {
	/** The text, trimmed; `''` searches no text. */
	q: string;
	/** Label filters, each once, in the order the address gave them; at most `MAX_LABEL_FILTERS`. */
	labels: LabelFilter[];
	/** The states to include, in `SEARCH_STATES` order; `null` for the default ones. */
	states: SearchState[] | null;
	/** The keyset cursor of the results page; `null` for the first page. */
	cursor: string | null;
}

/** Why a search cannot run as written, by the field to fix; `null` where nothing is wrong. */
export interface SearchErrors {
	q: string | null;
	label: string | null;
	/** A refusal that names no field. */
	form: string | null;
}

/** A search as an address holds it. */
export interface ReadSearch {
	search: Search;
	errors: SearchErrors;
	/**
	 * The first label text that is no filter, for the field that adds a label, so the user can fix
	 * it there; `''` when every label reads.
	 */
	pendingLabel: string;
}

/** The request `HuronApi.search` makes for a search. */
export interface SearchRequest {
	q: string;
	/** `key=value` texts; each becomes one `label` parameter. */
	labels: string[];
	/** The states to include; none means the API's default ones. */
	states: SearchState[];
	cursor: string | null;
	limit: number;
}

/** A search result as plain values: loads never return a collection or its metadata. */
export interface SearchResult {
	id: string;
	/** The full identifier, `catalog.namespace.path.name`. */
	identifier: string;
	catalog: string;
	state: string;
	/** The metadata's title, shortened to `TITLE_LENGTH`; `null` when it has none. */
	title: string | null;
	/** The metadata's description, shortened to `DESCRIPTION_LENGTH`; `null` when it has none. */
	description: string | null;
	fileCount: number;
	/** When the record last changed, as the API's ISO time. */
	updatedAt: string;
	/**
	 * Its first labels, by key, as many as `LABELS_LENGTH` holds, each key and value shortened to
	 * `MAX_LABEL_LENGTH`; a chip's `filter` is `null` where the search cannot find it, or the label
	 * is longer than that.
	 */
	labels: LabelChip[];
	/** How many more labels it has. */
	moreLabels: number;
}

/** A part of a text, matched by the search text or not. */
export interface TextPart {
	text: string;
	match: boolean;
}

/** The longest title a result shows, in code points: what the base schema allows. */
export { TITLE_LENGTH };

/**
 * The longest description a result shows, in code points. A row shows two lines of it; a
 * description may take up a mebibyte, which 25 results would make a page of.
 */
export const DESCRIPTION_LENGTH = 300;

/**
 * The most label text a result shows, keys and values together, in code points: as much as its
 * description. Its first labels show while they fit, each key and value shortened to
 * `MAX_LABEL_LENGTH`; the collection's page shows them all. A row's chips repeat their text in
 * their names, links and page data, and labels may take up a mebibyte.
 */
export const LABELS_LENGTH = 300;

/**
 * The most label chips a result shows; the collection's page shows them all. Each chip that adds
 * its label links to the whole search again, so 25 results of 50 chips made a page of a
 * megabyte, and the organization's search shows many more results.
 */
export const MAX_RESULT_LABELS = 12;

/**
 * The most label filters a search has. Each link that changes the search repeats all of them,
 * and the form and an empty result list link once per filter: a hand-made address of 120
 * filters made a page of 4 MB.
 */
export const MAX_LABEL_FILTERS = 10;

/** The most words of a text that a search finding nothing offers to search for one by one. */
export const MAX_WORDS = 10;

/**
 * The most catalogs an organization's search covers: its first ones, by name. The API has no
 * search over an organization, so the web asks each catalog in turn.
 */
export const ORGANIZATION_CATALOGS = 50;

/** How many results an organization's search shows of each catalog; the catalog's own shows all. */
export const CATALOG_RESULTS = 5;

/**
 * The parameter that keeps a label filter whose text holds a line break in a search form, the
 * text written as a JSON string (see `formLabel`).
 */
export const JSON_LABEL = 'label_json';

const LABEL_ERROR = 'Write a label filter as key=value, for example mission=ace.';
const LABEL_LENGTH_ERROR = `Use at most ${MAX_LABEL_LENGTH} characters in a label filter's key and in its value.`;
const LINE_BREAK = /[\r\n]/u;

/** The search with no text, no label filters and the default states: everything, first page. */
export function emptySearch(): Search {
	return { q: '', labels: [], states: null, cursor: null };
}

/**
 * Read a search from an address's query: `q`, every `label` (and `label_json`, see
 * `formLabel`), every `state` and `cursor`.
 *
 * - The text is trimmed; longer than `MAX_TEXT_LENGTH` code points is an error.
 * - A label is split at its first `=`; without one, at its first `:`, as the API also accepts
 *   (`mission:ace` reads as `mission=ace`). A label without either, or with an empty key, is an
 *   error, and so is one whose key or value is longer than `MAX_LABEL_LENGTH` code points, the
 *   most a label chip searches for. A blank label (the field for adding one, left empty) is no
 *   filter, and a label given twice counts once. Labels are kept as written, spaces included:
 *   the API compares them so. More than `MAX_LABEL_FILTERS` filters is an error, and the search
 *   keeps the first ones.
 * - States outside `SEARCH_STATES` are ignored, and so is `draft` unless `drafts` (the user may
 *   create collections in the catalog, so the API would include them): it is never sent. With
 *   no state left, or exactly the default ones, the search has the default states.
 */
export function readSearch(params: URLSearchParams, { drafts }: { drafts: boolean }): ReadSearch {
	const q = (params.get('q') ?? '').trim();
	const labels: LabelFilter[] = [];
	const unread: Array<{ text: string; error: string }> = [];
	for (const [name, value] of params) {
		if (name !== 'label' && name !== JSON_LABEL) continue;
		const text = name === 'label' ? value : jsonText(value);
		if (text === null) {
			unread.push({ text: value, error: LABEL_ERROR });
			continue;
		}
		if (text.trim() === '') continue;
		const label = parseLabel(text);
		if (label === null) unread.push({ text, error: LABEL_ERROR });
		else if (longerThan(label.key) || longerThan(label.value)) {
			unread.push({ text, error: LABEL_LENGTH_ERROR });
		} else if (!hasLabel(labels, label)) labels.push(label);
	}
	return {
		search: {
			q,
			labels: labels.slice(0, MAX_LABEL_FILTERS),
			states: chosenStates(params.getAll('state'), drafts),
			cursor: params.get('cursor') || null
		},
		errors: {
			q: textError(q),
			label: unread[0]?.error ?? countError(labels.length),
			form: null
		},
		pendingLabel: unread[0]?.text ?? ''
	};
}

/**
 * Whether an address asks for drafts; only then does reading it need to know whether the user
 * may see them.
 */
export function asksForDrafts(params: URLSearchParams): boolean {
	return params.getAll('state').includes('draft');
}

/** Whether any field of a search has an error. */
export function hasErrors(errors: SearchErrors): boolean {
	return errors.q !== null || errors.label !== null || errors.form !== null;
}

/** Whether a search asks for nothing in particular: no text, no label filters, the default states. */
export function isEmptySearch(search: Search): boolean {
	return search.q === '' && search.labels.length === 0 && search.states === null;
}

/**
 * A label filter from its `key=value` text, as the API reads it: split at the first `=`, else at
 * the first `:`; `null` without either or with an empty key.
 */
export function parseLabel(text: string): LabelFilter | null {
	let at = text.indexOf('=');
	if (at < 0) at = text.indexOf(':');
	if (at <= 0) return null;
	return { key: text.slice(0, at), value: text.slice(at + 1) };
}

/**
 * A label filter as `key=value`. A filter's key never holds `=` (it is split at the first), so
 * the text reads back as the same filter.
 */
export function labelText({ key, value }: LabelFilter): string {
	return `${key}=${value}`;
}

/**
 * The field of a search form that keeps a label filter: `label` with its text, or `label_json`
 * with the text as a JSON string where it holds a line break. A browser submitting a form itself
 * writes every line break of a field as CR LF, which would make the filter another one; JSON
 * writes them as escapes. Reading the address takes either (see `readSearch`), and links write
 * `label` alone (see `searchParams`), as the form does when scripts tidy it.
 */
export function formLabel(label: LabelFilter): { name: string; value: string } {
	const text = labelText(label);
	return LINE_BREAK.test(text)
		? { name: JSON_LABEL, value: JSON.stringify(text) }
		: { name: 'label', value: text };
}

/** The filter a label chip searches for, or `null` for a chip the search cannot find. */
export function chipFilter(chip: LabelChip): LabelFilter | null {
	return chip.filter === null ? null : parseLabel(chip.filter);
}

/** Whether two label filters are the same. */
export function sameLabel(a: LabelFilter, b: LabelFilter): boolean {
	return a.key === b.key && a.value === b.value;
}

/** Whether a search filters by this label. */
export function filtersBy(search: Search, label: LabelFilter): boolean {
	return hasLabel(search.labels, label);
}

/**
 * Whether no collection can pass a search's label filters: two of them give one key different
 * values, and a collection's labels hold one value for each key.
 */
export function labelsContradict(search: Search): boolean {
	const values = new Map<string, string>();
	for (const { key, value } of search.labels) {
		if ((values.get(key) ?? value) !== value) return true;
		values.set(key, value);
	}
	return false;
}

/** The states a search includes. */
export function searchedStates(search: Search): readonly SearchState[] {
	return search.states ?? DEFAULT_STATES;
}

/**
 * A search's canonical query parameters: `q`, each `label`, each `state` (none for the default
 * states), then `cursor`, each only when it holds something. Reading them back gives the same
 * search.
 */
export function searchParams(search: Search): URLSearchParams {
	const params = new URLSearchParams();
	if (search.q !== '') params.append('q', search.q);
	for (const label of search.labels) params.append('label', labelText(label));
	for (const state of chosenStates(search.states ?? [], true) ?? []) params.append('state', state);
	if (search.cursor !== null) params.append('cursor', search.cursor);
	return params;
}

/**
 * Rewrite what a search form submits as the search's canonical query (see `searchParams`): no
 * empty text or label, no states when they are the default ones, the text trimmed. What cannot be
 * read stays as it was typed, for the page to explain. `drafts`: whether the form offers them.
 */
export function tidySearchForm(data: FormData, { drafts }: { drafts: boolean }): void {
	const params = new URLSearchParams();
	for (const [key, value] of data) {
		if (typeof value === 'string') params.append(key, value);
	}
	const { search, errors } = readSearch(params, { drafts });
	if (hasErrors(errors)) return;
	for (const key of new Set(data.keys())) data.delete(key);
	for (const [key, value] of searchParams(search)) data.append(key, value);
}

/** A search's canonical query string with its `?`, or `''` for the empty search. */
export function searchQuery(search: Search): string {
	const query = searchParams(search).toString();
	return query === '' ? '' : `?${query}`;
}

/** The same search without its text. Every change of a search starts again at its first page. */
export function withoutText(search: Search): Search {
	return { ...search, q: '', cursor: null };
}

/** The same search with another text: one word of it, say. */
export function withText(search: Search, q: string): Search {
	return { ...search, q, cursor: null };
}

/** The same search without one label filter. */
export function withoutLabel(search: Search, label: LabelFilter): Search {
	return {
		...search,
		labels: search.labels.filter((known) => !sameLabel(known, label)),
		cursor: null
	};
}

/** The same search with one more label filter; a filter it has already counts once. */
export function withLabel(search: Search, label: LabelFilter): Search {
	const labels = hasLabel(search.labels, label) ? search.labels : [...search.labels, label];
	return { ...search, labels, cursor: null };
}

/** The same search over the default states. */
export function withDefaultStates(search: Search): Search {
	return { ...search, states: null, cursor: null };
}

/** The same search at another page: a `next_cursor`, or `null` for the first page. */
export function atPage(search: Search, cursor: string | null): Search {
	return { ...search, cursor };
}

/**
 * How much query text, in characters, the links of one page to each organization's search may
 * repeat together: the organization switcher's on an organization's search, and the chooser's.
 */
export const SHARED_QUERY_LENGTH = 64 * 1024;

/** How much query text each of those links may repeat however many organizations there are. */
export const LINK_QUERY_LENGTH = 1024;

/**
 * The search that each of `count` links to an organization's search repeats: the search
 * without its cursor, while its query fits that link's share of `SHARED_QUERY_LENGTH` (at least
 * `LINK_QUERY_LENGTH`); else its text and states alone, while they fit; else none. A user may
 * see up to 500 organizations, and an address may hold a search of many kilobytes: repeated in
 * full, one crafted link made the switcher's 500 links 7.6 MB.
 */
export function sharedSearch(search: Search, count: number): Search {
	const budget = Math.max(LINK_QUERY_LENGTH, Math.floor(SHARED_QUERY_LENGTH / Math.max(1, count)));
	const fits = (candidate: Search) => searchQuery(candidate).length <= budget;
	const whole: Search = { ...search, cursor: null };
	if (fits(whole)) return whole;
	const text: Search = { ...whole, labels: [] };
	return fits(text) ? text : emptySearch();
}

/**
 * The same search for a catalog whose drafts the user may not see: without drafts, as the API
 * would search it there, so that it is never sent; `null` when no other state is left to search.
 */
export function withoutDrafts(search: Search): Search | null {
	if (search.states === null || !search.states.includes('draft')) return search;
	const states = search.states.filter((state) => state !== 'draft');
	if (states.length === 0) return null;
	return { ...search, states: chosenStates(states, false), cursor: null };
}

/**
 * The words of a search text that a search for one word can try: each once, in order, the first
 * `MAX_WORDS` of them.
 */
export function textWords(q: string): string[] {
	return [...new Set(q.split(/\s+/u).filter((word) => word !== ''))].slice(0, MAX_WORDS);
}

/** What the API is asked for a search, a page of `SEARCH_PAGE_SIZE` results. */
export function searchRequest(search: Search): SearchRequest {
	return {
		q: search.q,
		labels: search.labels.map(labelText),
		states: search.states ?? [],
		cursor: search.cursor,
		limit: SEARCH_PAGE_SIZE
	};
}

/**
 * The identifier inside `catalog` (`namespace.path.name`) that a search text names, for the
 * exact match; `null` when it names none. The text is trimmed and lowercased, as identifiers are
 * written. Text that starts with the catalog's name and a dot is a full identifier, as the CLI
 * reads it (`qualify()`); other text is an identifier inside the catalog. Either way the part
 * inside the catalog must be a well-formed path of at least a namespace and a name.
 */
export function exactIdentifier(q: string, catalog: string): string | null {
	const text = q.trim().toLowerCase();
	const prefix = `${catalog}.`;
	const rest = text.startsWith(prefix) ? text.slice(prefix.length) : text;
	return isDottedPath(rest) && rest.split('.').length >= 2 ? rest : null;
}

/**
 * The catalog among `catalogs` whose collection a search text names by its full identifier
 * (`catalog.namespace.path.name`, trimmed and in any case), for the exact match of a search
 * over several catalogs; `null` when it names none of them so. A text without a catalog's name
 * could be an identifier inside any of them, so only a full identifier counts.
 */
export function identifiedCatalog(q: string, catalogs: readonly string[]): string | null {
	const text = q.trim().toLowerCase();
	const dot = text.indexOf('.');
	if (dot <= 0) return null;
	const catalog = text.slice(0, dot);
	if (!catalogs.includes(catalog)) return null;
	return exactIdentifier(text, catalog) === null ? null : catalog;
}

/**
 * Whether a collection passes a search's state and label filters, as the API decides them: its
 * state is one the search includes, and its `labels` hold each filter's key with exactly that
 * text. The text filter is not checked.
 */
export function passesFilters(collection: Collection, search: Search): boolean {
	if (!searchedStates(search).some((state) => state === collection.state)) return false;
	if (search.labels.length === 0) return true;
	const labels = ownValue(collection.metadata, 'labels');
	if (!isRecord(labels)) return false;
	return search.labels.every(({ key, value }) => ownValue(labels, key) === value);
}

/** A collection as a search result, its long texts shortened: 25 make a page of modest size. */
export function searchResult(collection: Collection): SearchResult {
	const title = metadataTitle(collection.metadata);
	const description = metadataDescription(collection.metadata);
	const labels = resultLabels(collection.metadata);
	return {
		id: collection.id,
		identifier: collection.identifier,
		catalog: collection.catalog,
		state: collection.state,
		title: title === null ? null : shortened(title, TITLE_LENGTH),
		description: description === null ? null : shortened(description, DESCRIPTION_LENGTH),
		fileCount: collection.file_count,
		updatedAt: collection.updated_at,
		labels: labels.items,
		moreLabels: labels.more
	};
}

/**
 * A text split into the parts the search text matches and the parts between them, for `<mark>`:
 * every match, left to right, case-insensitively and literally (no character means more than
 * itself). Parts always hold whole code points of the text as it is, so they never split a
 * surrogate pair and join back into the text exactly.
 *
 * Case is compared with each code point folded (`ß` reads as `ss`, `İ` as `i̇`), never by offsets
 * into a lowered copy, whose length can differ: the folded text is searched, and a match counts
 * only where it starts and ends with whole code points of the text. The API folds with Python's
 * `casefold`; a match can fall inside one code point there (`s` in `ß`), which no part can mark:
 * where the API matched and these parts cannot, the text has no match. With no search text, it
 * has none either.
 */
export function highlight(text: string, q: string): TextPart[] {
	if (text === '') return [];
	const needle = [...q].map(fold).join('');
	if (needle === '') return [{ text, match: false }];
	const points = [...text];
	const folds = points.map(fold);
	const folded = folds.join('');
	// The code point whose fold starts at each offset of the folded text; -1 inside a fold.
	const pointAt = new Array<number>(folded.length + 1).fill(-1);
	let offset = 0;
	folds.forEach((part, index) => {
		pointAt[offset] = index;
		offset += part.length;
	});
	pointAt[folded.length] = points.length;
	const parts: TextPart[] = [];
	let plain = 0;
	for (let at = folded.indexOf(needle); at >= 0;) {
		const start = pointAt[at];
		const end = pointAt[at + needle.length];
		if (start < 0 || end < 0) {
			at = folded.indexOf(needle, at + 1);
			continue;
		}
		if (plain < start) parts.push({ text: points.slice(plain, start).join(''), match: false });
		parts.push({ text: points.slice(start, end).join(''), match: true });
		plain = end;
		at = folded.indexOf(needle, at + needle.length);
	}
	if (plain < points.length) parts.push({ text: points.slice(plain).join(''), match: false });
	return parts;
}

/** The error of a search text the API would refuse, or `null` for a text it accepts. */
function textError(q: string): string | null {
	const length = [...q].length;
	if (length <= MAX_TEXT_LENGTH) return null;
	return `Use at most ${formatCount(MAX_TEXT_LENGTH)} characters; this text has ${formatCount(length)}.`;
}

/** The error of a search with more label filters than it may have, or `null`. */
function countError(count: number): string | null {
	if (count <= MAX_LABEL_FILTERS) return null;
	return `Use at most ${formatCount(MAX_LABEL_FILTERS)} label filters; this search has ${formatCount(count)}.`;
}

/** Whether a label's key or value holds more code points than a filter may. */
function longerThan(text: string): boolean {
	return [...text].length > MAX_LABEL_LENGTH;
}

/** The text a `label_json` parameter holds, or `null` where it holds no JSON string. */
function jsonText(value: string): string | null {
	try {
		const text: unknown = JSON.parse(value);
		return typeof text === 'string' ? text : null;
	} catch {
		return null;
	}
}

/**
 * The states asked for, in `SEARCH_STATES` order, each once; `null` for none (unknown ones and
 * drafts the user may not see aside) or exactly the default ones.
 */
function chosenStates(values: readonly string[], drafts: boolean): SearchState[] | null {
	const chosen = SEARCH_STATES.filter(
		(state) => values.includes(state) && (state !== 'draft' || drafts)
	);
	const isDefault =
		chosen.length === DEFAULT_STATES.length &&
		chosen.every((state) => DEFAULT_STATES.includes(state));
	return chosen.length === 0 || isDefault ? null : chosen;
}

function hasLabel(labels: readonly LabelFilter[], label: LabelFilter): boolean {
	return labels.some((known) => sameLabel(known, label));
}

/**
 * The label chips of a result: its first labels (see `labelChips`), at most
 * `MAX_RESULT_LABELS` and while their text fits in `LABELS_LENGTH`, each key and value
 * shortened to `MAX_LABEL_LENGTH`; `more` counts the rest. A shortened chip searches for nothing:
 * `labelChips` gives a label that long no filter.
 */
function resultLabels(metadata: Readonly<Record<string, unknown>>): {
	items: LabelChip[];
	more: number;
} {
	const { items, more } = labelChips(metadata);
	const shown: LabelChip[] = [];
	let left = LABELS_LENGTH;
	for (const chip of items) {
		const key = shortened(chip.key, MAX_LABEL_LENGTH);
		const value = shortened(chip.value, MAX_LABEL_LENGTH);
		const length = [...key].length + [...value].length;
		if (shown.length === MAX_RESULT_LABELS || length > left) break;
		left -= length;
		shown.push({ key, value, filter: chip.filter });
	}
	return { items: shown, more: more + items.length - shown.length };
}

/**
 * A code point as case-insensitive comparison sees it: upper case then lower case, twice (`ẞ`
 * becomes `ß`, then `ss`). The dotless `ı` stays itself, as `casefold` keeps it. Two code points
 * compare equal so exactly when the API's `casefold` (Python 3.12, Unicode 15) makes them equal,
 * except case pairs later Unicode added, which compare equal here only.
 */
function fold(point: string): string {
	if (point === 'ı') return point;
	return point.toUpperCase().toLowerCase().toUpperCase().toLowerCase();
}
