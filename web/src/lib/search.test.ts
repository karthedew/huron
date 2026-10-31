import { describe, expect, it } from 'vitest';
import type { Collection } from '$api/types';
import { MAX_ITEMS, MAX_LABEL_LENGTH } from './metadata';
import { collectionFixture } from './testing/api-fixtures';
import { parsedObject } from './testing/json';
import { serializePageData } from './testing/page-data';
import {
	DESCRIPTION_LENGTH,
	JSON_LABEL,
	LABELS_LENGTH,
	LINK_QUERY_LENGTH,
	MAX_LABEL_FILTERS,
	MAX_RESULT_LABELS,
	MAX_TEXT_LENGTH,
	MAX_WORDS,
	SHARED_QUERY_LENGTH,
	TITLE_LENGTH,
	asksForDrafts,
	atPage,
	chipFilter,
	emptySearch,
	exactIdentifier,
	filtersBy,
	formLabel,
	hasErrors,
	highlight,
	identifiedCatalog,
	isEmptySearch,
	labelText,
	labelsContradict,
	parseLabel,
	passesFilters,
	readSearch,
	searchParams,
	searchQuery,
	searchRequest,
	searchResult,
	searchedStates,
	sharedSearch,
	textWords,
	tidySearchForm,
	withDefaultStates,
	withLabel,
	withText,
	withoutDrafts,
	withoutLabel,
	withoutText,
	type Search,
	type TextPart
} from './search';

const LABEL_ERROR = 'Write a label filter as key=value, for example mission=ace.';

function read(query: string, drafts = false) {
	return readSearch(new URLSearchParams(query), { drafts });
}

function search(overrides: Partial<Search> = {}): Search {
	return { ...emptySearch(), ...overrides };
}

/** The parts of a highlight, the matched ones in brackets. */
function marked(parts: readonly TextPart[]): string {
	return parts.map(({ text, match }) => (match ? `[${text}]` : text)).join('');
}

describe('readSearch', () => {
	it('reads the text, the label filters, the states and the cursor', () => {
		expect(
			read('q=solar+wind&label=mission%3Dace&label=level=l2&state=incomplete&cursor=c2')
		).toEqual({
			search: {
				q: 'solar wind',
				labels: [
					{ key: 'mission', value: 'ace' },
					{ key: 'level', value: 'l2' }
				],
				states: ['incomplete'],
				cursor: 'c2'
			},
			errors: { q: null, label: null, form: null },
			pendingLabel: ''
		});
	});

	it('reads an empty query as the empty search', () => {
		expect(read('')).toEqual({
			search: emptySearch(),
			errors: { q: null, label: null, form: null },
			pendingLabel: ''
		});
		expect(read('q=&label=&cursor=').search).toEqual(emptySearch());
	});

	it('trims the text, and reads the first one given', () => {
		expect(read('q=%20%09wind%20%0A').search.q).toBe('wind');
		expect(read('q=%20%20').search.q).toBe('');
		expect(read('q=one&q=two').search.q).toBe('one');
		// Inside the text, spaces are part of what it matches.
		expect(read('q=solar%20%20wind').search.q).toBe('solar  wind');
	});

	it('accepts as many characters as the API counts, code points rather than UTF-16 units', () => {
		const emoji = '😀'.repeat(MAX_TEXT_LENGTH);
		expect(emoji.length).toBe(2 * MAX_TEXT_LENGTH);
		const longest = read(new URLSearchParams({ q: emoji }).toString());
		expect(longest.errors.q).toBeNull();
		expect(longest.search.q).toBe(emoji);
		expect(read(`q=${'a'.repeat(MAX_TEXT_LENGTH)}`).errors.q).toBeNull();
		// Trimmed first: the spaces around the text do not count.
		expect(read(`q=++${'a'.repeat(MAX_TEXT_LENGTH)}++`).errors.q).toBeNull();
	});

	it('refuses a text longer than the API accepts, keeping it to be shortened', () => {
		const tooLong = read(`q=${'a'.repeat(MAX_TEXT_LENGTH + 1)}`);
		expect(tooLong.errors.q).toBe('Use at most 200 characters; this text has 201.');
		expect(tooLong.search.q).toHaveLength(MAX_TEXT_LENGTH + 1);
		expect(hasErrors(tooLong.errors)).toBe(true);
		const astral = read(new URLSearchParams({ q: '😀'.repeat(MAX_TEXT_LENGTH + 50) }).toString());
		expect(astral.errors.q).toBe('Use at most 200 characters; this text has 250.');
		expect(read(`q=${'é'.repeat(1234)}`).errors.q).toBe(
			'Use at most 200 characters; this text has 1,234.'
		);
	});

	it('splits a label at its first =, so its value may hold = and :', () => {
		expect(read('label=a%3Db%3Dc&label=url%3Dhttps://x.org/?y=1&label=k%3D').search.labels).toEqual(
			[
				{ key: 'a', value: 'b=c' },
				{ key: 'url', value: 'https://x.org/?y=1' },
				{ key: 'k', value: '' }
			]
		);
	});

	it('reads key:value as the API does, as the filter key=value', () => {
		const { search: found } = read('label=mission:ace&label=time:12:00&label=a:b%3Dc');
		expect(found.labels).toEqual([
			{ key: 'mission', value: 'ace' },
			{ key: 'time', value: '12:00' },
			// An = comes first, wherever it is.
			{ key: 'a:b', value: 'c' }
		]);
		expect(searchParams(found).getAll('label')).toEqual(['mission=ace', 'time=12:00', 'a:b=c']);
	});

	it('keeps labels as written, as the API compares them', () => {
		expect(read('label=+mission+%3D+ace+').search.labels).toEqual([
			{ key: ' mission ', value: ' ace ' }
		]);
	});

	it('counts a label given twice once, in the order first given', () => {
		expect(
			read('label=b=2&label=a=1&label=b=2&label=a:1&label=a=2').search.labels.map(labelText)
		).toEqual(['b=2', 'a=1', 'a=2']);
	});

	it('ignores blank labels: the field for adding one, left empty', () => {
		const blank = read('label=&label=+++&label=mission=ace');
		expect(blank.search.labels).toEqual([{ key: 'mission', value: 'ace' }]);
		expect(blank.errors.label).toBeNull();
	});

	it.each(['mission', '=ace', ':ace', '=', 'no separator at all'])(
		'refuses the label %j and gives it back to be fixed',
		(text) => {
			const refused = read(`label=mission%3Dace&label=${encodeURIComponent(text)}`);
			expect(refused.errors.label).toBe(LABEL_ERROR);
			expect(refused.pendingLabel).toBe(text);
			expect(refused.search.labels).toEqual([{ key: 'mission', value: 'ace' }]);
			expect(hasErrors(refused.errors)).toBe(true);
		}
	);

	it('gives back the first of several labels it cannot read', () => {
		const refused = read('label=first&label=a=b&label=second');
		expect(refused.pendingLabel).toBe('first');
		expect(refused.search.labels).toEqual([{ key: 'a', value: 'b' }]);
	});

	it('accepts a key and a value as long as a label chip searches for, in code points', () => {
		const longest = '😀'.repeat(MAX_LABEL_LENGTH);
		const accepted = read(new URLSearchParams({ label: `${longest}=${longest}` }).toString());
		expect(accepted.errors.label).toBeNull();
		expect(accepted.search.labels).toEqual([{ key: longest, value: longest }]);
	});

	it.each([
		['a key', `${'k'.repeat(MAX_LABEL_LENGTH + 1)}=ace`],
		['a value', `mission=${'😀'.repeat(MAX_LABEL_LENGTH + 1)}`],
		['a value written after a colon', `mission:${'v'.repeat(MAX_LABEL_LENGTH + 1)}`]
	])('refuses a label filter with %s longer than a chip searches for', (_, text) => {
		const refused = read(
			new URLSearchParams([
				['label', 'level=l2'],
				['label', text]
			]).toString()
		);
		expect(refused.errors.label).toBe(
			"Use at most 100 characters in a label filter's key and in its value."
		);
		expect(refused.pendingLabel).toBe(text);
		expect(refused.search.labels).toEqual([{ key: 'level', value: 'l2' }]);
		expect(hasErrors(refused.errors)).toBe(true);
	});

	it('keeps the first label filters a search may have, and refuses more', () => {
		const labels = (count: number) =>
			Array.from({ length: count }, (_, index) => `label=k${index}%3Dv`).join('&');
		const most = read(labels(MAX_LABEL_FILTERS));
		expect(most.search.labels).toHaveLength(MAX_LABEL_FILTERS);
		expect(most.errors.label).toBeNull();
		// A label given twice counts once.
		expect(read(`${labels(MAX_LABEL_FILTERS)}&label=k0%3Dv`).errors.label).toBeNull();
		const tooMany = read(`q=wind&${labels(MAX_LABEL_FILTERS + 2)}`);
		expect(tooMany.errors.label).toBe('Use at most 10 label filters; this search has 12.');
		expect(tooMany.search.labels.map(labelText)).toEqual(
			Array.from({ length: MAX_LABEL_FILTERS }, (_, index) => `k${index}=v`)
		);
		expect(tooMany.pendingLabel).toBe('');
		// A label it cannot read is the one to fix first, there.
		const both = read(`${labels(MAX_LABEL_FILTERS + 2)}&label=mission`);
		expect(both.errors.label).toBe(LABEL_ERROR);
		expect(both.pendingLabel).toBe('mission');
	});

	it('reads a label kept as JSON in its place among the others', () => {
		const query = new URLSearchParams([
			['label', 'a=1'],
			[JSON_LABEL, JSON.stringify('note=two\nlines')],
			['label', 'b=2'],
			[JSON_LABEL, JSON.stringify('a=1')]
		]);
		const { search: found, errors } = readSearch(query, { drafts: false });
		expect(found.labels).toEqual([
			{ key: 'a', value: '1' },
			{ key: 'note', value: 'two\nlines' },
			{ key: 'b', value: '2' }
		]);
		expect(hasErrors(errors)).toBe(false);
	});

	it.each(['note=x', '"unclosed', '5', '["note=x"]', 'null'])(
		'refuses a label kept as JSON that holds no JSON text: %j',
		(value) => {
			const refused = readSearch(new URLSearchParams([[JSON_LABEL, value]]), { drafts: false });
			expect(refused.errors.label).toBe(LABEL_ERROR);
			expect(refused.pendingLabel).toBe(value);
			expect(refused.search.labels).toEqual([]);
		}
	);

	it('checks a label kept as JSON as any other', () => {
		const unreadable = readSearch(new URLSearchParams([[JSON_LABEL, '"no\\nseparator"']]), {
			drafts: false
		});
		expect(unreadable.errors.label).toBe(LABEL_ERROR);
		expect(unreadable.pendingLabel).toBe('no\nseparator');
		const long = `k=${'\n'.repeat(MAX_LABEL_LENGTH + 1)}`;
		const tooLong = readSearch(new URLSearchParams([[JSON_LABEL, JSON.stringify(long)]]), {
			drafts: false
		});
		expect(tooLong.errors.label).toBe(
			"Use at most 100 characters in a label filter's key and in its value."
		);
		expect(
			readSearch(new URLSearchParams([[JSON_LABEL, '"  "']]), { drafts: false }).errors.label
		).toBeNull();
	});

	it('searches the default states when the address names none, or exactly them', () => {
		for (const query of [
			'',
			'state=active&state=incomplete',
			'state=incomplete&state=active&state=active'
		]) {
			expect(read(query).search.states).toBeNull();
			expect(searchedStates(read(query).search)).toEqual(['active', 'incomplete']);
		}
	});

	it('reads other selections in a fixed order, each once', () => {
		expect(read('state=incomplete').search.states).toEqual(['incomplete']);
		expect(read('state=active&state=active').search.states).toEqual(['active']);
		expect(read('state=draft&state=active&state=incomplete', true).search.states).toEqual([
			'active',
			'incomplete',
			'draft'
		]);
		expect(read('state=draft', true).search.states).toEqual(['draft']);
	});

	it('ignores drafts unless the user may see them, and never sends them then', () => {
		expect(read('state=draft').search.states).toBeNull();
		expect(read('state=draft&state=incomplete').search.states).toEqual(['incomplete']);
		expect(searchRequest(read('state=draft').search).states).toEqual([]);
		expect(searchParams(read('state=draft&state=active').search).getAll('state')).toEqual([
			'active'
		]);
	});

	it('ignores states it does not know, rather than refusing the search', () => {
		const unknown = read('state=deleted&state=Active&state=incomplete');
		expect(unknown.search.states).toEqual(['incomplete']);
		expect(hasErrors(unknown.errors)).toBe(false);
		expect(read('state=bogus').search.states).toBeNull();
	});

	it('reads a blank cursor as the first page', () => {
		expect(read('cursor=').search.cursor).toBeNull();
		expect(read('cursor=abc').search.cursor).toBe('abc');
	});
});

describe('asksForDrafts', () => {
	it('says whether an address asks for drafts', () => {
		expect(asksForDrafts(new URLSearchParams('state=draft'))).toBe(true);
		expect(asksForDrafts(new URLSearchParams('state=active&state=draft'))).toBe(true);
		expect(asksForDrafts(new URLSearchParams('state=active&q=draft'))).toBe(false);
		expect(asksForDrafts(new URLSearchParams(''))).toBe(false);
	});
});

describe('labels', () => {
	it('parses a label as the API does', () => {
		expect(parseLabel('a=b')).toEqual({ key: 'a', value: 'b' });
		expect(parseLabel('a:b')).toEqual({ key: 'a', value: 'b' });
		expect(parseLabel('a:b=c:d')).toEqual({ key: 'a:b', value: 'c:d' });
		expect(parseLabel('a=')).toEqual({ key: 'a', value: '' });
		expect(parseLabel('a')).toBeNull();
		expect(parseLabel('=b')).toBeNull();
		expect(parseLabel(':b')).toBeNull();
		expect(parseLabel('')).toBeNull();
	});

	it('writes a filter so that it reads back as itself', () => {
		for (const label of [
			{ key: 'mission', value: 'ace' },
			{ key: 'a:b', value: 'c=d' },
			{ key: 'k', value: '' },
			{ key: '__proto__', value: 'x' },
			{ key: 'ünï cødé', value: '🚀 rocket' }
		]) {
			expect(parseLabel(labelText(label))).toEqual(label);
		}
	});

	it("gives a chip's filter, or none for a chip the search cannot find", () => {
		expect(chipFilter({ key: 'mission', value: 'ace', filter: 'mission=ace' })).toEqual({
			key: 'mission',
			value: 'ace'
		});
		expect(chipFilter({ key: 'x:y', value: 'z=w', filter: 'x:y=z=w' })).toEqual({
			key: 'x:y',
			value: 'z=w'
		});
		expect(chipFilter({ key: 'count', value: '17', filter: null })).toBeNull();
	});

	it('says whether a search filters by a label', () => {
		const filtered = search({ labels: [{ key: 'mission', value: 'ace' }] });
		expect(filtersBy(filtered, { key: 'mission', value: 'ace' })).toBe(true);
		expect(filtersBy(filtered, { key: 'mission', value: 'wind' })).toBe(false);
		expect(filtersBy(emptySearch(), { key: 'mission', value: 'ace' })).toBe(false);
	});

	it('says whether label filters give one key two values, which no collection passes', () => {
		const by = (...labels: Array<[string, string]>) =>
			search({ labels: labels.map(([key, value]) => ({ key, value })) });
		expect(labelsContradict(by(['mission', 'ace'], ['mission', 'wind']))).toBe(true);
		expect(labelsContradict(by(['level', 'l2'], ['mission', 'ace'], ['mission', '']))).toBe(true);
		expect(labelsContradict(by(['mission', 'ace'], ['level', 'l2']))).toBe(false);
		expect(labelsContradict(by(['mission', 'ace'], ['mission', 'ace']))).toBe(false);
		expect(labelsContradict(emptySearch())).toBe(false);
		const contradicting = by(['mission', 'ace'], ['mission', 'wind']);
		const found = collectionFixture({ metadata: { labels: { mission: 'ace' } } });
		expect(passesFilters(found, contradicting)).toBe(false);
	});
});

describe('formLabel', () => {
	/**
	 * What a browser submits for a form's fields without scripts: every line break of a value
	 * written as CR LF (HTML, "converting an entry list to a list of name-value pairs").
	 */
	function submitted(fields: Array<{ name: string; value: string }>): URLSearchParams {
		return new URLSearchParams(
			fields.map(({ name, value }) => [name, value.replace(/\r\n|\r|\n/gu, '\r\n')])
		);
	}

	it('keeps a filter in the field for labels where it holds no line break', () => {
		expect(formLabel({ key: 'mission', value: 'ace' })).toEqual({
			name: 'label',
			value: 'mission=ace'
		});
		expect(formLabel({ key: 'a:b', value: 'c "d" \\e' })).toEqual({
			name: 'label',
			value: 'a:b=c "d" \\e'
		});
	});

	it('keeps a filter with a line break as JSON, which a browser submits unchanged', () => {
		const labels = [
			{ key: 'mission', value: 'ace' },
			{ key: 'note', value: 'a\nb' },
			{ key: 'crlf', value: 'a\r\nb' },
			{ key: 'cr\r', value: 'b\r' },
			{ key: 'lf', value: '\n' }
		];
		const fields = labels.map(formLabel);
		expect(fields.map(({ name }) => name)).toEqual([
			'label',
			JSON_LABEL,
			JSON_LABEL,
			JSON_LABEL,
			JSON_LABEL
		]);
		expect(fields[1].value).toBe('"note=a\\nb"');
		const { search: again, errors } = readSearch(submitted(fields), { drafts: false });
		expect(again.labels).toEqual(labels);
		expect(hasErrors(errors)).toBe(false);
		// Read back, the search writes each filter as a label again.
		expect(searchParams(again).getAll('label')).toEqual(labels.map(labelText));
		expect(searchParams(again).has(JSON_LABEL)).toBe(false);
	});

	it('would lose a line break in the field for labels', () => {
		const text = labelText({ key: 'note', value: 'a\nb' });
		expect(
			readSearch(submitted([{ name: 'label', value: text }]), { drafts: false }).search.labels
		).not.toEqual([{ key: 'note', value: 'a\nb' }]);
	});
});

describe('searchParams', () => {
	it('writes text, labels, states and cursor in that order, each only when it holds something', () => {
		const written = searchParams(
			search({
				cursor: 'c2',
				states: ['incomplete', 'draft'],
				labels: [
					{ key: 'level', value: 'l2' },
					{ key: 'mission', value: 'ace' }
				],
				q: 'solar wind'
			})
		);
		expect([...written]).toEqual([
			['q', 'solar wind'],
			['label', 'level=l2'],
			['label', 'mission=ace'],
			['state', 'incomplete'],
			['state', 'draft'],
			['cursor', 'c2']
		]);
		expect(written.toString()).toBe(
			'q=solar+wind&label=level%3Dl2&label=mission%3Dace&state=incomplete&state=draft&cursor=c2'
		);
		expect(searchParams(emptySearch()).toString()).toBe('');
	});

	it('leaves the states out when they are the default ones', () => {
		expect(searchParams(search({ states: ['active', 'incomplete'] })).toString()).toBe('');
		expect(searchParams(search({ states: ['incomplete', 'active'] })).toString()).toBe('');
		expect(searchParams(search({ q: 'x', states: null })).toString()).toBe('q=x');
	});

	it('reads back as the same search', () => {
		const searches: Search[] = [
			emptySearch(),
			search({ q: 'wind' }),
			search({ q: 'a&b=c?d#e%f+g', labels: [{ key: 'k&#?', value: '&=#?' }] }),
			search({ labels: [{ key: 'a:b', value: 'c=d' }], states: ['incomplete'] }),
			search({ q: 'İstanbul 😀', states: ['active', 'draft'], cursor: 'xyz==' }),
			search({ q: 'x'.repeat(MAX_TEXT_LENGTH), labels: [{ key: 'k', value: '' }] })
		];
		for (const original of searches) {
			const again = readSearch(searchParams(original), { drafts: true });
			expect(again.search).toEqual(original);
			expect(hasErrors(again.errors)).toBe(false);
			expect(searchParams(again.search).toString()).toBe(searchParams(original).toString());
		}
	});

	it('gives the query string with its ?, or nothing for the empty search', () => {
		expect(searchQuery(search({ q: 'wind' }))).toBe('?q=wind');
		expect(searchQuery(emptySearch())).toBe('');
	});
});

describe('tidySearchForm', () => {
	function form(entries: Array<[string, string]>): FormData {
		const data = new FormData();
		for (const [key, value] of entries) data.append(key, value);
		return data;
	}

	it('submits the canonical query: no empty fields, no default states, the text trimmed', () => {
		const data = form([
			['q', '  solar wind '],
			['label', 'mission=ace'],
			['label', 'level:l2'],
			['label', ''],
			['state', 'active'],
			['state', 'incomplete']
		]);
		tidySearchForm(data, { drafts: false });
		expect([...data]).toEqual([
			['q', 'solar wind'],
			['label', 'mission=ace'],
			['label', 'level=l2']
		]);
		const empty = form([
			['q', ''],
			['label', ''],
			['state', 'active'],
			['state', 'incomplete']
		]);
		tidySearchForm(empty, { drafts: false });
		expect([...empty]).toEqual([]);
	});

	it('keeps a selection of states that is not the default, drafts where the form offers them', () => {
		const data = form([
			['q', 'x'],
			['label', ''],
			['state', 'incomplete'],
			['state', 'draft']
		]);
		tidySearchForm(data, { drafts: true });
		expect([...data]).toEqual([
			['q', 'x'],
			['state', 'incomplete'],
			['state', 'draft']
		]);
	});

	it('submits a label kept as JSON as a label again', () => {
		const data = form([
			['q', 'nn'],
			['label', 'mission=ace'],
			[JSON_LABEL, JSON.stringify('note=a\nb')],
			['label', ''],
			['state', 'active'],
			['state', 'incomplete']
		]);
		tidySearchForm(data, { drafts: false });
		expect([...data]).toEqual([
			['q', 'nn'],
			['label', 'mission=ace'],
			['label', 'note=a\nb']
		]);
	});

	it('leaves a form it cannot read as it was typed, for the page to explain', () => {
		const entries: Array<[string, string]> = [
			['q', ' x '],
			['label', 'mission'],
			['state', 'active'],
			['state', 'incomplete']
		];
		const data = form(entries);
		tidySearchForm(data, { drafts: false });
		expect([...data]).toEqual(entries);
		const tooLong = form([['q', 'a'.repeat(MAX_TEXT_LENGTH + 1)]]);
		tidySearchForm(tooLong, { drafts: false });
		expect([...tooLong]).toEqual([['q', 'a'.repeat(MAX_TEXT_LENGTH + 1)]]);
	});
});

describe('changing a search', () => {
	const base = search({
		q: 'solar wind',
		labels: [
			{ key: 'mission', value: 'ace' },
			{ key: 'level', value: 'l2' }
		],
		states: ['incomplete'],
		cursor: 'c3'
	});

	it('removes one filter and starts again at the first page', () => {
		expect(withoutText(base)).toEqual({ ...base, q: '', cursor: null });
		expect(withoutLabel(base, { key: 'mission', value: 'ace' })).toEqual({
			...base,
			labels: [{ key: 'level', value: 'l2' }],
			cursor: null
		});
		expect(withDefaultStates(base)).toEqual({ ...base, states: null, cursor: null });
	});

	it('adds a label filter once', () => {
		const added = withLabel(base, { key: 'instrument', value: 'mag' });
		expect(added.labels.map(labelText)).toEqual(['mission=ace', 'level=l2', 'instrument=mag']);
		expect(added.cursor).toBeNull();
		expect(withLabel(base, { key: 'level', value: 'l2' })).toEqual({ ...base, cursor: null });
		expect(searchQuery(withLabel(emptySearch(), { key: 'a', value: 'b' }))).toBe('?label=a%3Db');
	});

	it('searches for one word instead of the text', () => {
		expect(withText(base, 'wind')).toEqual({ ...base, q: 'wind', cursor: null });
	});

	it('moves to another page, and back to the first', () => {
		expect(atPage(base, 'c4')).toEqual({ ...base, cursor: 'c4' });
		expect(searchQuery(atPage(base, null))).toBe(
			'?q=solar+wind&label=mission%3Dace&label=level%3Dl2&state=incomplete'
		);
	});

	it('leaves the search it changes as it was', () => {
		const before = structuredClone(base);
		withoutText(base);
		withoutLabel(base, base.labels[0]);
		withLabel(base, { key: 'x', value: 'y' });
		withDefaultStates(base);
		atPage(base, 'c9');
		withoutDrafts({ ...base, states: ['incomplete', 'draft'] });
		expect(base).toEqual(before);
	});
});

describe('sharedSearch', () => {
	const base = search({
		q: 'solar wind',
		labels: [{ key: 'mission', value: 'ace' }],
		states: ['incomplete', 'draft'],
		cursor: 'c3'
	});
	/** A label of 100 + 100 four-byte code points: 2,400 characters in a query. */
	const wide = (index: number) => ({ key: `${index}${'𝕏'.repeat(99)}`, value: '𝕏'.repeat(100) });

	it('repeats a search that fits in full, without its cursor', () => {
		expect(sharedSearch(base, 500)).toEqual({ ...base, cursor: null });
		expect(searchQuery(sharedSearch(base, 2))).toBe(
			'?q=solar+wind&label=mission%3Dace&state=incomplete&state=draft'
		);
	});

	it('leaves out the labels of a search too long for each of many links, then everything', () => {
		const long = { ...base, labels: [wide(1), wide(2)] };
		expect(sharedSearch(long, 500)).toEqual({ ...base, labels: [], cursor: null });
		const text = { ...long, q: '𝕏'.repeat(200) };
		expect(sharedSearch(text, 500)).toEqual(emptySearch());
	});

	it('gives each of a few links a larger share of the page', () => {
		// Six such labels: a search of over 14,000 characters, which four links may each repeat.
		const long = { ...base, labels: Array.from({ length: 6 }, (_, index) => wide(index)) };
		expect(searchQuery(long).length).toBeGreaterThan(14_000);
		expect(sharedSearch(long, 4)).toEqual({ ...long, cursor: null });
		expect(sharedSearch(long, 64).labels).toEqual([]);
	});

	it('never lets the links repeat more than their shares, however long the search', () => {
		const long = { ...base, labels: Array.from({ length: 10 }, (_, index) => wide(index)) };
		for (const count of [1, 4, 64, 65, 500]) {
			const each = searchQuery(sharedSearch(long, count)).length;
			expect(each * count).toBeLessThanOrEqual(
				Math.max(SHARED_QUERY_LENGTH, count * LINK_QUERY_LENGTH)
			);
		}
	});
});

describe('isEmptySearch', () => {
	it('is true only for no text, no label filters and the default states', () => {
		expect(isEmptySearch(emptySearch())).toBe(true);
		expect(isEmptySearch(search({ cursor: 'c2' }))).toBe(true);
		expect(isEmptySearch(search({ q: 'wind' }))).toBe(false);
		expect(isEmptySearch(search({ labels: [{ key: 'mission', value: 'ace' }] }))).toBe(false);
		expect(isEmptySearch(search({ states: ['incomplete'] }))).toBe(false);
		expect(isEmptySearch(search({ states: ['draft'] }))).toBe(false);
	});
});

describe('withoutDrafts', () => {
	const base = search({ q: 'wind', labels: [{ key: 'mission', value: 'ace' }], cursor: 'c2' });

	it('leaves a search without drafts as it is', () => {
		expect(withoutDrafts(base)).toBe(base);
		const incomplete = search({ states: ['incomplete'] });
		expect(withoutDrafts(incomplete)).toBe(incomplete);
	});

	it('takes drafts out, back to the default states where those are left', () => {
		expect(withoutDrafts({ ...base, states: ['active', 'incomplete', 'draft'] })).toEqual({
			...base,
			states: null,
			cursor: null
		});
		expect(withoutDrafts({ ...base, states: ['incomplete', 'draft'] })).toEqual({
			...base,
			states: ['incomplete'],
			cursor: null
		});
	});

	it('leaves nothing to search when the search asks for drafts only', () => {
		expect(withoutDrafts({ ...base, states: ['draft'] })).toBeNull();
	});
});

describe('identifiedCatalog', () => {
	const catalogs = ['heliophysics', 'space-weather'];

	it.each([
		['heliophysics.solar-wind.ace.mag-l2-2024', 'heliophysics'],
		['  Space-Weather.Alerts.KP-INDEX-2024 ', 'space-weather'],
		['heliophysics.heliophysics.x', 'heliophysics']
	])('finds the catalog %j names by its full identifier', (q, catalog) => {
		expect(identifiedCatalog(q, catalogs)).toBe(catalog);
	});

	it.each([
		'',
		'wind',
		'heliophysics',
		'heliophysics.',
		'heliophysics.fields',
		// An identifier inside a catalog could be in either; only a full one counts.
		'solar-wind.ace.mag-l2-2024',
		'.heliophysics.fields.run001',
		'geoscience.ocean.sst-2024',
		'heliophysics.fields/run001.x',
		'heliophysics.fields..run001'
	])('finds no catalog for %j', (q) => {
		expect(identifiedCatalog(q, catalogs)).toBeNull();
	});

	it('finds nothing among no catalogs', () => {
		expect(identifiedCatalog('heliophysics.fields.run001', [])).toBeNull();
	});
});

describe('textWords', () => {
	it('gives the words of a text, each once, in order', () => {
		expect(textWords('solar wind  solar\tL1\nwind')).toEqual(['solar', 'wind', 'L1']);
		expect(textWords('wind')).toEqual(['wind']);
		expect(textWords('')).toEqual([]);
	});

	it('gives the first words of a long text only', () => {
		const words = Array.from({ length: 40 }, (_, index) => `w${index}`);
		expect(textWords(words.join(' '))).toEqual(words.slice(0, MAX_WORDS));
		expect(MAX_WORDS).toBe(10);
	});
});

describe('searchRequest', () => {
	it('asks the API for a page of 25, with labels as key=value and the default states unsaid', () => {
		expect(
			searchRequest(
				search({
					q: 'wind',
					labels: [{ key: 'a:b', value: 'c=d' }],
					states: ['incomplete', 'draft'],
					cursor: 'c2'
				})
			)
		).toEqual({
			q: 'wind',
			labels: ['a:b=c=d'],
			states: ['incomplete', 'draft'],
			cursor: 'c2',
			limit: 25
		});
		expect(searchRequest(emptySearch())).toEqual({
			q: '',
			labels: [],
			states: [],
			cursor: null,
			limit: 25
		});
	});
});

describe('exactIdentifier', () => {
	it.each([
		['heliophysics.solar-wind.ace.mag-l2-2024', 'solar-wind.ace.mag-l2-2024'],
		['solar-wind.ace.mag-l2-2024', 'solar-wind.ace.mag-l2-2024'],
		['  HelioPhysics.Fields.RUN001 ', 'fields.run001'],
		['fields.run001', 'fields.run001'],
		// A namespace named like its catalog: the CLI reads the text as a full identifier.
		['heliophysics.heliophysics.x', 'heliophysics.x'],
		['deep.a.b.c.leaf', 'deep.a.b.c.leaf']
	])('reads %j as the identifier %j inside the catalog', (q, identifier) => {
		expect(exactIdentifier(q, 'heliophysics')).toBe(identifier);
	});

	it.each([
		'',
		'wind',
		'heliophysics',
		'heliophysics.',
		'heliophysics.fields',
		'fields.',
		'.fields.run001',
		'fields..run001',
		'fields/run001.x',
		'fields.run 001',
		'fields.run%2F001',
		'fields.-run',
		'fields.Run_001.ü',
		`fields.${'a'.repeat(64)}`,
		`${'a.'.repeat(130)}a`
	])('names no collection for %j', (q) => {
		expect(exactIdentifier(q, 'heliophysics')).toBeNull();
	});
});

describe('passesFilters', () => {
	const collection = (overrides: Partial<Collection> = {}) =>
		collectionFixture({
			state: 'active',
			metadata: { title: 'T', labels: { mission: 'ace', count: 17, empty: '' } },
			...overrides
		});

	it('passes the states a search includes, by default active and incomplete ones', () => {
		expect(passesFilters(collection(), emptySearch())).toBe(true);
		expect(passesFilters(collection({ state: 'incomplete' }), emptySearch())).toBe(true);
		expect(passesFilters(collection({ state: 'draft' }), emptySearch())).toBe(false);
		expect(passesFilters(collection({ state: 'draft' }), search({ states: ['draft'] }))).toBe(true);
		expect(passesFilters(collection(), search({ states: ['incomplete'] }))).toBe(false);
	});

	it('passes label filters only where the labels hold exactly that text', () => {
		const by = (key: string, value: string) => search({ labels: [{ key, value }] });
		expect(passesFilters(collection(), by('mission', 'ace'))).toBe(true);
		expect(passesFilters(collection(), by('empty', ''))).toBe(true);
		expect(passesFilters(collection(), by('mission', 'ACE'))).toBe(false);
		expect(passesFilters(collection(), by('count', '17'))).toBe(false);
		expect(passesFilters(collection(), by('level', 'l2'))).toBe(false);
		expect(
			passesFilters(
				collection(),
				search({
					labels: [
						{ key: 'mission', value: 'ace' },
						{ key: 'empty', value: '' }
					]
				})
			)
		).toBe(true);
	});

	it('finds no label in metadata whose labels are not an object, nor inherited ones', () => {
		const filtered = search({ labels: [{ key: 'mission', value: 'ace' }] });
		for (const labels of [['mission'], 'mission=ace', null]) {
			expect(passesFilters(collection({ metadata: { labels } }), filtered)).toBe(false);
		}
		expect(passesFilters(collection({ metadata: {} }), filtered)).toBe(false);
		const inherited = search({ labels: [{ key: 'constructor', value: 'x' }] });
		expect(passesFilters(collection({ metadata: { labels: {} } }), inherited)).toBe(false);
		const own = parsedObject('{"labels":{"__proto__":"x"}}');
		expect(
			passesFilters(
				collection({ metadata: own }),
				search({ labels: [{ key: '__proto__', value: 'x' }] })
			)
		).toBe(true);
	});
});

describe('searchResult', () => {
	it('gives a collection as plain values, with its labels as chips', () => {
		const found = collectionFixture({
			id: 'c-1',
			identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
			state: 'incomplete',
			file_count: 3,
			updated_at: '2026-10-03T09:00:00+00:00',
			metadata: {
				title: 'ACE MAG level 2, 2024',
				description: 'Field vectors.',
				labels: { mission: 'ace', count: 17, ratio: 6.62607015e-34 }
			}
		});
		expect(searchResult(found)).toEqual({
			id: 'c-1',
			identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
			catalog: 'heliophysics',
			state: 'incomplete',
			title: 'ACE MAG level 2, 2024',
			description: 'Field vectors.',
			fileCount: 3,
			updatedAt: '2026-10-03T09:00:00+00:00',
			labels: [
				{ key: 'count', value: '17', filter: null },
				{ key: 'mission', value: 'ace', filter: 'mission=ace' },
				{ key: 'ratio', value: '6.62607015e-34', filter: null }
			],
			moreLabels: 0
		});
	});

	it('gives no title or description where the metadata has none worth showing', () => {
		const bare = searchResult(collectionFixture({ metadata: { title: '  ', description: 5 } }));
		expect(bare.title).toBeNull();
		expect(bare.description).toBeNull();
		expect(bare.labels).toEqual([]);
	});

	it('shortens a long title and description, never inside a code point', () => {
		const result = searchResult(
			collectionFixture({
				metadata: {
					title: '😀'.repeat(TITLE_LENGTH + 5),
					description: `${'a'.repeat(DESCRIPTION_LENGTH - 1)}😀😀 and more`
				}
			})
		);
		expect(result.title).toBe(`${'😀'.repeat(TITLE_LENGTH)}…`);
		expect(result.description).toBe(`${'a'.repeat(DESCRIPTION_LENGTH - 1)}😀…`);
		const exact = searchResult(
			collectionFixture({ metadata: { title: 'x'.repeat(TITLE_LENGTH) } })
		);
		expect(exact.title).toBe('x'.repeat(TITLE_LENGTH));
	});

	it('shows the first labels and counts the rest', () => {
		const labels = Object.fromEntries(
			Array.from({ length: MAX_ITEMS + 3 }, (_, index) => [
				`k${String(index).padStart(2, '0')}`,
				'v'
			])
		);
		const result = searchResult(collectionFixture({ metadata: { labels } }));
		expect(MAX_RESULT_LABELS).toBe(12);
		expect(result.labels.map(({ key }) => key)).toEqual(
			Object.keys(labels).slice(0, MAX_RESULT_LABELS)
		);
		expect(result.moreLabels).toBe(MAX_ITEMS + 3 - MAX_RESULT_LABELS);
		const few = searchResult(
			collectionFixture({ metadata: { labels: { a: '1', b: '2', c: '3' } } })
		);
		expect(few.labels).toHaveLength(3);
		expect(few.moreLabels).toBe(0);
	});

	it('shortens long label keys and values, and searches for none of them', () => {
		const long = 'x'.repeat(MAX_LABEL_LENGTH + 1);
		const result = searchResult(
			collectionFixture({
				metadata: { labels: { mission: 'ace', [`k${long}`]: 'v', emoji: '😀'.repeat(150) } }
			})
		);
		expect(result.labels).toEqual([
			{ key: 'emoji', value: `${'😀'.repeat(MAX_LABEL_LENGTH)}…`, filter: null },
			{ key: `k${'x'.repeat(MAX_LABEL_LENGTH - 1)}…`, value: 'v', filter: null },
			{ key: 'mission', value: 'ace', filter: 'mission=ace' }
		]);
		expect(result.moreLabels).toBe(0);
	});

	it("shows only as many labels as a row's room for label text holds, and counts the rest", () => {
		// Each label is 40 code points of text: key and value together.
		const labels = Object.fromEntries(
			Array.from({ length: 20 }, (_, index) => [
				`key${String(index).padStart(2, '0')}`,
				'v'.repeat(35)
			])
		);
		const result = searchResult(collectionFixture({ metadata: { labels } }));
		const shown = Math.floor(LABELS_LENGTH / 40);
		expect(result.labels.map(({ key }) => key)).toEqual(Object.keys(labels).slice(0, shown));
		expect(result.moreLabels).toBe(20 - shown);
	});

	it('keeps a result small, however long its labels are', () => {
		const mebibyte = 'n'.repeat(1024 * 1024);
		const result = searchResult(
			collectionFixture({
				metadata: { labels: { [mebibyte]: 'key', note: mebibyte, mission: 'ace' } }
			})
		);
		for (const sent of serializePageData(result)) expect(sent.length).toBeLessThan(2000);
		expect(result.labels.map(({ filter }) => filter)).toEqual(['mission=ace', null, null]);
	});

	it('returns page data SvelteKit can send, whatever keys the metadata holds', () => {
		const metadata = parsedObject(
			'{"title":"Proto","__proto__":{"polluted":true},"labels":{"__proto__":"x","mission":"proto"}}'
		);
		const result = searchResult(collectionFixture({ metadata }));
		expect(() => serializePageData(result)).not.toThrow();
		expect(result.labels).toEqual([
			{ key: '__proto__', value: 'x', filter: '__proto__=x' },
			{ key: 'mission', value: 'proto', filter: 'mission=proto' }
		]);
		const read = readSearch(new URLSearchParams('label=__proto__=x&q=__proto__'), {
			drafts: false
		});
		expect(() => serializePageData(read)).not.toThrow();
	});
});

describe('highlight', () => {
	it('marks every match, case-insensitively, and joins back into the text', () => {
		const parts = highlight('Solar wind and SOLAR WIND, solarwind', 'solar wind');
		expect(marked(parts)).toBe('[Solar wind] and [SOLAR WIND], solarwind');
		expect(parts.map(({ text }) => text).join('')).toBe('Solar wind and SOLAR WIND, solarwind');
	});

	it('marks a match at either end and the whole text', () => {
		expect(marked(highlight('wind', 'WIND'))).toBe('[wind]');
		expect(marked(highlight('windmill', 'wind'))).toBe('[wind]mill');
		expect(marked(highlight('solar-wind', 'wind'))).toBe('solar-[wind]');
		expect(highlight('wind', 'wind')).toEqual([{ text: 'wind', match: true }]);
	});

	it('marks matches left to right without overlap', () => {
		expect(marked(highlight('aaaaa', 'aa'))).toBe('[aa][aa]a');
		expect(marked(highlight('abab', 'bab'))).toBe('a[bab]');
	});

	it('marks nothing without a search text, or where the text does not match', () => {
		expect(highlight('wind', '')).toEqual([{ text: 'wind', match: false }]);
		expect(highlight('wind', 'fire')).toEqual([{ text: 'wind', match: false }]);
		expect(highlight('', 'wind')).toEqual([]);
		expect(highlight('', '')).toEqual([]);
	});

	it('reads every character of the search text as itself', () => {
		expect(marked(highlight('a.b axb a*b', '.'))).toBe('a[.]b axb a*b');
		expect(marked(highlight('cost (USD) [v2] $5 ^up a+b c|d e\\f', '(usd) [v2] $5'))).toBe(
			'cost [(USD) [v2] $5] ^up a+b c|d e\\f'
		);
		expect(marked(highlight('a+b c|d e\\f ^x?', 'e\\f ^x?'))).toBe('a+b c|d [e\\f ^x?]');
		expect(marked(highlight('anything', '.*'))).toBe('anything');
	});

	it('marks the characters of the text itself, not offsets of a lowered copy', () => {
		// 'İ' lowers to two code units: offsets into a lowered copy would be one off per 'İ'.
		expect('İ'.toLowerCase()).toHaveLength(2);
		expect(marked(highlight('İİ wind İ', 'wind'))).toBe('İİ [wind] İ');
		expect(marked(highlight('İstanbul', 'i̇stanbul'))).toBe('[İstanbul]');
		expect(marked(highlight('i̇stanbul', 'İSTANBUL'))).toBe('[i̇stanbul]');
		// A match that would end inside 'İ' (lowered 'i' + combining dot) cannot be marked.
		expect(marked(highlight('İstanbul', 'i'))).toBe('İstanbul');
	});

	it('never splits a surrogate pair', () => {
		expect(marked(highlight('🚀 launch 🚀', '🚀'))).toBe('[🚀] launch [🚀]');
		expect(marked(highlight('a😀b', 'a😀'))).toBe('[a😀]b');
		expect(highlight('😀x😀', 'x')).toEqual([
			{ text: '😀', match: false },
			{ text: 'x', match: true },
			{ text: '😀', match: false }
		]);
		// A lone surrogate is one character of its own, and half of a pair matches no pair.
		expect(marked(highlight('a\uD800b', '\uD800'))).toBe('a[\uD800]b');
		expect(highlight('😀', '\uDE00')).toEqual([{ text: '😀', match: false }]);
		expect(highlight('😀', '\uD83D')).toEqual([{ text: '😀', match: false }]);
	});

	it('takes time in proportion to the text, however nearly the search text matches', () => {
		// Comparing each start's partial match afresh would take minutes here.
		const text = 'a'.repeat(5000);
		expect(highlight(text, `${'a'.repeat(1999)}b`)).toEqual([{ text, match: false }]);
		expect(highlight(text, 'A'.repeat(2000))).toEqual([
			{ text: 'a'.repeat(2000), match: true },
			{ text: 'a'.repeat(2000), match: true },
			{ text: 'a'.repeat(1000), match: false }
		]);
		// Folded text runs longer than the text: each 'ß' reads as 'ss'.
		expect(highlight('ß'.repeat(3000), 'ss'.repeat(1000))).toEqual([
			{ text: 'ß'.repeat(1000), match: true },
			{ text: 'ß'.repeat(1000), match: true },
			{ text: 'ß'.repeat(1000), match: true }
		]);
		expect(highlight('ß'.repeat(3000), 's'.repeat(1999))).toEqual([
			{ text: 'ß'.repeat(3000), match: false }
		]);
	});

	it('folds case as Python does where it can, and marks nothing where it cannot', () => {
		// The API folds 'ß' to 'ss', so both find each other.
		expect(marked(highlight('Straße', 'STRASSE'))).toBe('[Straße]');
		expect(marked(highlight('Strasse', 'straße'))).toBe('[Strasse]');
		expect(marked(highlight('GROẞ', 'groß'))).toBe('[GROẞ]');
		// The API matches 's' inside 'ß'; no mark can show half of it.
		expect(marked(highlight('ß', 's'))).toBe('ß');
		// Python keeps the dotless 'ı' apart from 'i'.
		expect(marked(highlight('Kırmızı', 'kirmizi'))).toBe('Kırmızı');
		expect(marked(highlight('Kırmızı', 'KIRMIZI'))).toBe('Kırmızı');
		expect(marked(highlight('Kırmızı', 'kır'))).toBe('[Kır]mızı');
		// The Kelvin sign and final sigma fold as Python folds them.
		expect(marked(highlight('20 K', 'k'))).toBe('20 [K]');
		expect(marked(highlight('λόγος', 'ΛΌΓΟΣ'))).toBe('[λόγος]');
	});
});
