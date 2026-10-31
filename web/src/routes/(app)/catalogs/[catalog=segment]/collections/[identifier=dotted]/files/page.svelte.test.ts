import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Collection, FileRecord, RoleGrant } from '$api/types';
import { fileFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, catalogRole, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const BASE = '/catalogs/heliophysics/collections/fields.run001/files';

interface ShowOptions {
	collection?: Partial<Collection>;
	files?: FileRecord[];
	nextCursor?: string | null;
	roles?: RoleGrant[];
	query?: string;
}

async function show({
	collection = {},
	files = [],
	nextCursor = null,
	roles = [],
	query = ''
}: ShowOptions = {}) {
	page.url = new URL(`http://localhost:4173${BASE}${query}`);
	render(Page, {
		props: {
			data: {
				...catalogPageData({ roles }),
				collection: collectionOf({
					identifier: 'heliophysics.fields.run001',
					namespace: 'fields',
					name: 'run001',
					metadata: { title: 'Encounter 17 run 001' },
					...collection
				}),
				trail: [],
				files,
				nextCursor
			},
			params: { catalog: 'heliophysics', identifier: 'fields.run001' },
			form: undefined
		}
	});
	await tick();
}

describe("a collection's files", () => {
	it('counts the recorded files and lists a page of them in a table', async () => {
		await show({
			collection: { file_count: 120 },
			files: [fileFixture({ rel_path: 'frames/frame-0001.dat' })],
			nextCursor: 'more'
		});
		expect(document.title).toBe('Files · Encounter 17 run 001 · Huron');
		expect(screen.getByText('120 files recorded, sorted by path.')).toBeInTheDocument();
		const table = screen.getByRole('table', { name: 'Files of Encounter 17 run 001' });
		expect(within(table).getByRole('rowheader', { name: 'frames/frame-0001.dat' })).toBeVisible();
		expect(
			within(screen.getByRole('navigation', { name: 'File pages' })).getByRole('link', {
				name: 'Next page'
			})
		).toHaveAttribute('href', `${BASE}?cursor=more`);
	});

	it('explains that a draft has no files yet', async () => {
		await show({ collection: { state: 'draft', path: null, file_count: 0 } });
		expect(screen.getByText(/A draft has no directory on the share/)).toBeInTheDocument();
		expect(screen.queryByRole('table')).toBeNull();
		expect(screen.queryByText(/files recorded/)).toBeNull();
	});

	it('shows contributors how to add the first files, checking this collection out first', async () => {
		await show({ collection: { file_count: 0 }, roles: [catalogRole('contributor')] });
		expect(screen.getByText('No files yet.')).toBeInTheDocument();
		expect(screen.queryByText(/files recorded/)).toBeNull();
		const hint = screen.getByRole('region', { name: 'Add files to this collection' });
		// `add` and `push` act on whichever collection was checked out last.
		expect(within(hint).getByRole('textbox')).toHaveValue(
			'huron --catalog heliophysics checkout heliophysics.fields.run001\n' +
				'huron --catalog heliophysics add <file>…\n' +
				'huron --catalog heliophysics push -m "<message>"'
		);
	});

	it('shows readers that there are no files, without a hint', async () => {
		await show({ collection: { file_count: 0 }, roles: [catalogRole('reader')] });
		expect(screen.getByText('No files yet.')).toBeInTheDocument();
		expect(screen.queryByRole('region', { name: 'Add files to this collection' })).toBeNull();
	});

	it('says a later page that came back empty holds no files', async () => {
		await show({ collection: { file_count: 50 }, query: '?cursor=old' });
		expect(screen.getByText('No files on this page.')).toBeInTheDocument();
		expect(
			within(screen.getByRole('navigation', { name: 'File pages' })).getByRole('link', {
				name: 'First page'
			})
		).toHaveAttribute('href', BASE);
	});

	it('says when a page link expired', async () => {
		await show({ files: [fileFixture()], query: '?notice=page_expired' });
		expect(screen.getByRole('note')).toHaveTextContent(
			'That page link expired; showing the first page.'
		);
	});
});
