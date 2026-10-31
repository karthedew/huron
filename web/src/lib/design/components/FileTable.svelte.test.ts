import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fileFixture } from '$lib/testing/api-fixtures';
import FileTable from './FileTable.svelte';

afterEach(() => {
	Reflect.deleteProperty(navigator, 'clipboard');
});

const HASH = '3f2a9c1b7d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeef0';
const FILES = [
	fileFixture({
		rel_path: 'data/ace_mag_l2_2024-01.cdf',
		size: 48_234_496,
		sha256: HASH,
		recorded_at: '2026-10-03T09:15:42+00:00',
		recorded_by: 'dave'
	}),
	fileFixture({ rel_path: 'RELEASE_NOTES.md', size: 512, sha256: 'b'.repeat(64) }),
	fileFixture({ rel_path: 'flags/done', size: 1, sha256: 'c'.repeat(64) })
];

async function show() {
	render(FileTable, { props: { label: 'Files of ACE MAG', files: FILES } });
	await tick();
}

function rowOf(path: string): HTMLElement {
	const header = screen.getByRole('rowheader', { name: path });
	const row = header.closest('tr');
	if (row === null) throw new Error(`no row for ${path}`);
	return row;
}

describe('FileTable', () => {
	it('scrolls inside a named region that the keyboard can reach', async () => {
		await show();
		const region = screen.getByRole('region', { name: 'Files of ACE MAG' });
		expect(region).toHaveAttribute('tabindex', '0');
		expect(within(region).getByRole('table', { name: 'Files of ACE MAG' })).toBeInTheDocument();
		expect(
			within(region)
				.getAllByRole('columnheader')
				.map((cell) => cell.textContent)
		).toEqual(['Path', 'Size', 'SHA-256', 'Recorded']);
	});

	it('heads each row with the path and gives the size in decimal units with the exact bytes', async () => {
		await show();
		const size = within(rowOf('data/ace_mag_l2_2024-01.cdf')).getByText('48.2 MB');
		expect(size.tagName).toBe('DATA');
		expect(size).toHaveAttribute('value', '48234496');
		expect(size).toHaveAttribute('title', '48,234,496 bytes');
		expect(within(rowOf('RELEASE_NOTES.md')).getByText('512 B')).toHaveAttribute(
			'title',
			'512 bytes'
		);
		expect(within(rowOf('flags/done')).getByText('1 B')).toHaveAttribute('title', '1 byte');
	});

	it('shows the start of each SHA-256 and the whole value in a disclosure', async () => {
		await show();
		const row = rowOf('data/ace_mag_l2_2024-01.cdf');
		const summary = within(row).getByText('3f2a9c1b7d4e…').closest('summary');
		expect(summary).toHaveAccessibleName('3f2a9c1b7d4e…, SHA-256 of data/ace_mag_l2_2024-01.cdf');
		const details = summary?.closest('details');
		expect(details?.open).toBe(false);
		expect(details).toHaveTextContent(HASH);
	});

	it('copies the whole SHA-256 where the browser has a clipboard', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		await show();
		await fireEvent.click(
			within(rowOf('data/ace_mag_l2_2024-01.cdf')).getByRole('button', {
				name: 'Copy SHA-256 of data/ace_mag_l2_2024-01.cdf'
			})
		);
		expect(writeText).toHaveBeenCalledWith(HASH);
	});

	it('says when and by whom each file was recorded, in UTC', async () => {
		await show();
		const row = rowOf('data/ace_mag_l2_2024-01.cdf');
		const time = within(row).getByText('2026-10-03 09:15 UTC');
		expect(time.tagName).toBe('TIME');
		expect(time).toHaveAttribute('datetime', '2026-10-03T09:15:42.000Z');
		expect(row).toHaveTextContent('by dave');
	});
});
