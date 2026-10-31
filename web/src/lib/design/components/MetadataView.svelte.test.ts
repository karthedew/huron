import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { JsonObject } from '$api/types';
import { MAX_ITEMS, humanizeKey, metadataView, type MetadataView as View } from '$lib/metadata';
import MetadataView from './MetadataView.svelte';

/** A schema with a property of every kind a schema document may describe. */
const SCHEMA: JsonObject = {
	type: 'object',
	required: ['title', 'description', 'mission'],
	properties: {
		title: { type: 'string' },
		description: { type: 'string' },
		mission: { type: 'string', title: 'Mission' },
		release: { type: 'string', format: 'date', title: 'Release date' },
		start_time: { type: 'string', format: 'date-time', title: 'Start time' },
		landing_page: { type: 'string', format: 'uri', title: 'Landing page' },
		mirror: { type: 'string', format: 'uri' },
		trap: { type: 'string', format: 'uri' },
		cadence: { type: 'integer' },
		calibrated: { type: 'boolean' },
		keywords: { type: 'array', items: { type: 'string' } },
		contacts: {
			type: 'array',
			items: {
				type: 'object',
				required: ['name'],
				properties: { name: { type: 'string' }, email: { type: 'string', format: 'email' } }
			}
		},
		processing: { type: 'object', properties: { level: { type: 'string', title: 'Level' } } },
		labels: { type: 'object', title: 'Labels' }
	}
};

const METADATA = {
	title: 'Wind SWE 2023',
	description: 'Ion moments.',
	release: '2024-03-15',
	start_time: '2023-01-01T00:00:00Z',
	landing_page: 'https://data.example.org/wind/swe',
	mirror: 'ftp://ftp.example.org/wind/',
	trap: 'javascript:alert(1)',
	cadence: 92,
	calibrated: false,
	keywords: ['solar wind', 'ions'],
	contacts: [{ name: 'SWE team', email: 'swe@example.org' }, { name: 'Archive' }],
	processing: { level: 'L2' },
	labels: { mission: 'wind', 'odd=key': 'x' },
	notes: '<script>alert(1)</script>\nsecond line'
};

function show(view: View = metadataView(METADATA, SCHEMA)) {
	return render(MetadataView, { props: { catalog: 'heliophysics', view } });
}

/** The value a field shows: the `dd` beside its label. */
function valueOf(label: string): HTMLElement {
	const term = screen.getAllByText(label, { selector: 'dt' })[0];
	const value = term.nextElementSibling;
	if (!(value instanceof HTMLElement)) throw new Error(`no value for ${label}`);
	return value;
}

describe('MetadataView', () => {
	it('lists the fields by label in walkthrough order, without the title and description', () => {
		show();
		const labels = [...document.querySelectorAll('dl')[0].children].map(
			(row) => row.querySelector('dt')?.textContent
		);
		expect(labels).toEqual([
			'Mission',
			'Cadence',
			'Calibrated',
			'Contacts',
			'Keywords',
			'Labels',
			'Landing page',
			'Mirror',
			'Processing',
			'Release date',
			'Start time',
			'Trap'
		]);
		expect(screen.queryByText('Wind SWE 2023')).toBeNull();
	});

	it('marks a required field the metadata lacks as missing', () => {
		show();
		expect(within(valueOf('Mission')).getByText('Missing')).toBeInTheDocument();
	});

	it('shows times in UTC on a time element and dates as written', () => {
		show();
		const start = within(valueOf('Start time')).getByText('2023-01-01 00:00 UTC');
		expect(start.tagName).toBe('TIME');
		expect(start).toHaveAttribute('datetime', '2023-01-01T00:00:00.000Z');
		expect(within(valueOf('Release date')).getByText('2024-03-15')).toHaveAttribute(
			'datetime',
			'2024-03-15'
		);
	});

	it('links web addresses with rel noopener noreferrer, and no other scheme', () => {
		show();
		const page = within(valueOf('Landing page')).getByRole('link', {
			name: 'https://data.example.org/wind/swe'
		});
		expect(page).toHaveAttribute('href', 'https://data.example.org/wind/swe');
		expect(page).toHaveAttribute('rel', 'noopener noreferrer');
		expect(within(valueOf('Mirror')).queryByRole('link')).toBeNull();
		expect(valueOf('Mirror')).toHaveTextContent('ftp://ftp.example.org/wind/');
		expect(within(valueOf('Trap')).queryByRole('link')).toBeNull();
		expect(valueOf('Trap')).toHaveTextContent('javascript:alert(1)');
		expect(document.querySelectorAll('a[href^="javascript"], a[href^="ftp"]')).toHaveLength(0);
	});

	it('shows numbers, booleans and keywords as plain text and chips', () => {
		show();
		expect(valueOf('Cadence')).toHaveTextContent('92');
		expect(valueOf('Calibrated')).toHaveTextContent('No');
		const keywords = within(valueOf('Keywords')).getAllByRole('listitem');
		expect(keywords.map((chip) => chip.textContent)).toEqual(['solar wind', 'ions']);
		expect(within(valueOf('Keywords')).queryByRole('link')).toBeNull();
	});

	it('lists contacts compactly, with their email addresses linked', () => {
		show();
		const [first, second] = within(valueOf('Contacts')).getAllByRole('listitem');
		expect(first).toHaveTextContent(/^Name\s*SWE team\s*Email\s*swe@example.org$/);
		expect(within(first).getByRole('link', { name: 'swe@example.org' })).toHaveAttribute(
			'href',
			'mailto:swe@example.org'
		);
		expect(second).toHaveTextContent(/^Name\s*Archive$/);
		expect(within(second).queryByText('Email')).toBeNull();
	});

	it('shows an object as its fields', () => {
		show();
		expect(within(valueOf('Processing')).getByText('Level').tagName).toBe('DT');
		expect(valueOf('Processing')).toHaveTextContent(/^Level\s*L2$/);
	});

	it('lets labels at every level and numbers break anywhere, so none widens the page', () => {
		const key = 'faradayCupEffectiveAreaCalibrationCoefficientsRevisionForSensorUnitB';
		show(
			metadataView(
				{ title: 't', calibration: { [key]: -1.7976931348623157e308, history: [{ [key]: 'r' }] } },
				null
			)
		);
		const labels = screen.getAllByText(humanizeKey(key), { selector: 'dt' });
		expect(labels).toHaveLength(2);
		for (const label of labels) expect(label).toHaveClass('wrap-anywhere');
		expect(screen.getByText('-1.7976931348623157e+308')).toHaveClass('wrap-anywhere');
	});

	it('sets each object inside another in by a line of its own, as it does list items', () => {
		show(
			metadataView({ title: 't', nested: { outer_note: 'a', inner: { inner_note: 'b' } } }, null)
		);
		const outer = valueOf('Nested').querySelector('dl');
		const inner = valueOf('Inner').querySelector('dl');
		expect(outer?.parentElement).toHaveClass('border-l-2', 'pl-2.5');
		expect(inner?.parentElement).toHaveClass('border-l-2', 'pl-2.5');
		expect(outer?.contains(inner ?? null)).toBe(true);
		expect(outer?.parentElement).not.toBe(inner?.parentElement);
	});

	it('links labels to the catalog search, saying so in their names, except those it cannot find', () => {
		show();
		const labels = within(valueOf('Labels'));
		const link = labels.getByRole('link', {
			name: 'mission: wind, search the catalog for this label'
		});
		expect(link).toHaveAttribute('href', '/catalogs/heliophysics/search?label=mission%3Dwind');
		expect(link).toHaveTextContent(/^mission: wind$/);
		expect(labels.getByText('odd=key: x').tagName).toBe('SPAN');
		expect(labels.getAllByRole('link')).toHaveLength(1);
	});

	it('shows the first items of a long value and counts the rest', () => {
		const many = (count: number) => Array.from({ length: count }, (_, index) => `item ${index}`);
		show(
			metadataView(
				{
					title: 't',
					keywords: many(MAX_ITEMS + 2950),
					contacts: many(MAX_ITEMS + 3).map((name) => ({ name })),
					labels: Object.fromEntries(many(MAX_ITEMS + 1).map((key) => [key, 'x'])),
					wide: Object.fromEntries(many(MAX_ITEMS + 4).map((key) => [key, 1]))
				},
				SCHEMA
			)
		);
		const keywords = within(valueOf('Keywords')).getAllByRole('listitem');
		expect(keywords).toHaveLength(MAX_ITEMS + 1);
		expect(keywords.at(-1)).toHaveTextContent('and 2,950 more');
		const contacts = within(valueOf('Contacts')).getAllByRole('listitem');
		expect(contacts.at(-1)).toHaveTextContent('and 3 more');
		expect(within(valueOf('Labels')).getAllByRole('listitem').at(-1)).toHaveTextContent(
			'and 1 more label'
		);
		expect(valueOf('Wide')).toHaveTextContent(/and 4 more fields$/);
	});

	it('counts the fields it leaves out once it shows as many values as it may', () => {
		const fields = Object.fromEntries(
			Array.from({ length: 1200 }, (_, index) => [`field_${String(index).padStart(4, '0')}`, 1])
		);
		show(metadataView({ title: 't', ...fields }, null));
		expect(screen.getByText('and 200 more fields')).toBeInTheDocument();
	});

	it('shows other fields under their own heading, text as text', () => {
		show();
		expect(screen.getByRole('heading', { name: 'Other fields', level: 3 })).toBeInTheDocument();
		const notes = valueOf('Notes');
		expect(notes).toHaveTextContent('<script>alert(1)</script> second line');
		expect(notes.querySelector('script')).toBeNull();
	});

	it('says so when there is nothing beyond the title and description', () => {
		show({ fields: [], other: [], more: 0, shortened: false });
		expect(screen.getByText('Nothing beyond the title and description.')).toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Other fields' })).toBeNull();
	});

	it('shows empty values as none', () => {
		show(metadataView({ title: 't', empty: [], nothing: null }, null));
		expect(valueOf('Empty')).toHaveTextContent('None');
		expect(valueOf('Nothing')).toHaveTextContent('None');
	});
});
