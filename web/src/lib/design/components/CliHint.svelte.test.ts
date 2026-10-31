import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CliHint from './CliHint.svelte';

const COMMAND = 'huron catalog create helio <name>';
const READ_ONLY =
	'This website is read-only; changes are made with the huron CLI on a machine that mounts the share.';

function withClipboard(writeText: (text: string) => Promise<void>) {
	Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
}

afterEach(() => {
	Reflect.deleteProperty(navigator, 'clipboard');
	vi.useRealTimers();
});

/** Render, then let the mount effect decide between the copy button and the field. */
async function show(command = COMMAND) {
	render(CliHint, { props: { title: 'Create a catalog', command } });
	await tick();
}

describe('CliHint', () => {
	it('shows the command with a copy button where the browser has a clipboard', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		withClipboard(writeText);
		await show();
		const hint = screen.getByRole('region', { name: 'Create a catalog' });
		expect(hint.querySelector('pre code')?.textContent).toBe(COMMAND);
		expect(screen.getByText(READ_ONLY)).toBeInTheDocument();
		const status = screen.getByRole('status');
		expect(status.textContent).toBe('');

		await fireEvent.click(screen.getByRole('button', { name: 'Copy: Create a catalog' }));
		expect(writeText).toHaveBeenCalledWith(COMMAND);
		expect(status).toHaveTextContent('Copied');
	});

	it('clears the confirmation after a few seconds', async () => {
		vi.useFakeTimers();
		withClipboard(() => Promise.resolve());
		await show();
		await fireEvent.click(screen.getByRole('button', { name: 'Copy: Create a catalog' }));
		expect(screen.getByRole('status')).toHaveTextContent('Copied');
		await vi.advanceTimersByTimeAsync(4000);
		expect(screen.getByRole('status').textContent).toBe('');
	});

	it('says so when copying fails', async () => {
		withClipboard(() => Promise.reject(new Error('denied')));
		await show();
		await fireEvent.click(screen.getByRole('button', { name: 'Copy: Create a catalog' }));
		expect(screen.getByRole('status')).toHaveTextContent(
			"Couldn't copy; select the command instead."
		);
	});

	it('keeps each word of the command whole, and the text the command', async () => {
		withClipboard(() => Promise.resolve());
		const first = 'huron --catalog helio namespace create helio.<name> --allow-collections';
		const command = `${first}\nhuron acl apply helio`;
		await show(command);
		const code = screen.getByRole('region', { name: 'Create a catalog' }).querySelector('pre code');
		expect(code?.textContent).toBe(command);
		const lines = [...(code?.children ?? [])];
		expect(lines.map((line) => line.textContent)).toEqual([`${first}\n`, 'huron acl apply helio']);
		// What a line wraps onto starts further in than the next line does.
		for (const line of lines) expect(line).toHaveClass('block', 'pl-hang', '-indent-hang');
		const words = lines.flatMap((line) => [...line.children]);
		expect(words.map((word) => word.textContent)).toEqual(command.split(/[ \n]/));
		// A word moves to the next line whole; only one wider than the block breaks inside.
		for (const word of words) expect(word).toHaveClass('inline-block', 'max-w-full', 'indent-0');
	});

	it('offers a field that selects itself without a clipboard, one row per command', async () => {
		await show('huron login\nhuron whoami');
		expect(screen.queryByRole('button')).not.toBeInTheDocument();
		const field = screen.getByRole('textbox', { name: 'Create a catalog' });
		expect(field).toHaveAttribute('readonly');
		expect(field).toHaveValue('huron login\nhuron whoami');
		// A field cannot indent what wraps: a long command scrolls sideways instead of wrapping
		// into a line that would read as a command of its own.
		expect(field).toHaveAttribute('wrap', 'off');
		expect(field).toHaveAttribute('rows', '2');
		await fireEvent.focus(field);
		expect(field instanceof HTMLTextAreaElement && field.selectionEnd).toBe(24);
	});

	it('shows the wrapped command where the hint is narrow and the field where it is wide', async () => {
		// Without a clipboard: a narrow field would cut each command off at its edge.
		await show('huron login\nhuron whoami');
		const hint = screen.getByRole('region', { name: 'Create a catalog' });
		const block = hint.querySelector('pre');
		expect(block?.querySelector('code')?.textContent).toBe('huron login\nhuron whoami');
		expect(block).toHaveClass('@md:hidden');
		expect(screen.getByRole('textbox', { name: 'Create a catalog' })).toHaveClass(
			'hidden',
			'@md:block'
		);
	});

	it('draws the code block alone, with neither class, where the browser has a clipboard', async () => {
		withClipboard(() => Promise.resolve());
		await show();
		expect(screen.queryByRole('textbox')).toBeNull();
		expect(document.querySelector('pre')).not.toHaveClass('@md:hidden');
	});
});
