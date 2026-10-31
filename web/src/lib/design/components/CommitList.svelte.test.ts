import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import { commitFixture } from '$lib/testing/api-fixtures';
import CommitList from './CommitList.svelte';

const COMMITS = [
	commitFixture({
		id: '0192f2a4-0000-7000-8000-00000000c0de',
		message: 'Replace the README with release notes',
		adds: 1,
		removes: 1,
		base_version: 3,
		new_version: 4,
		host: 'dtn02.example.org',
		actor: 'dave',
		created_at: '2026-10-04T08:30:10+00:00'
	}),
	commitFixture({ message: null, adds: 1200, removes: 0 })
];

async function show() {
	render(CommitList, { props: { label: 'Commits of ACE MAG', commits: COMMITS } });
	await tick();
}

function commits() {
	return within(screen.getByRole('list', { name: 'Commits of ACE MAG' })).getAllByRole('listitem');
}

describe('CommitList', () => {
	it('shows each commit with its message, changes, revisions, actor, host and time', async () => {
		await show();
		const [latest] = commits();
		expect(latest).toHaveTextContent('Replace the README with release notes');
		expect(latest).toHaveTextContent('+1 / −1');
		expect(latest).toHaveTextContent('revision 3 → 4');
		expect(latest).toHaveTextContent('by dave');
		expect(latest).toHaveTextContent('from dtn02.example.org');
		const time = within(latest).getByText('2026-10-04 08:30 UTC');
		expect(time.tagName).toBe('TIME');
		expect(time).toHaveAttribute('datetime', '2026-10-04T08:30:10.000Z');
	});

	it('reads the changes and revisions to screen readers in words', async () => {
		await show();
		const [latest, first] = commits();
		expect(within(latest).getByText('1 added, 1 removed')).toHaveClass('sr-only');
		expect(within(latest).getByText('revision 3 to 4')).toHaveClass('sr-only');
		expect(within(first).getByText('1,200 added, 0 removed')).toBeInTheDocument();
	});

	it('says when a commit has no message', async () => {
		await show();
		expect(commits()[1]).toHaveTextContent('No message');
	});

	it('shows the end of the commit id, where ids differ, with the whole id as its title', async () => {
		await show();
		const id = within(commits()[0]).getByText('00000000c0de');
		expect(id).toHaveAttribute('title', '0192f2a4-0000-7000-8000-00000000c0de');
	});
});
