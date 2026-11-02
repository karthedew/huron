import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CopyText from './CopyText.svelte';

const PATH = '/projects/huron/helio/heliophysics/fields';

afterEach(() => {
	Reflect.deleteProperty(navigator, 'clipboard');
	vi.useRealTimers();
});

function withClipboard(writeText: (text: string) => Promise<void>) {
	Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
}

async function show() {
	render(CopyText, { props: { label: 'share path', value: PATH } });
	await tick();
}

describe('CopyText', () => {
	it('shows the value and copies it, saying so for a while', async () => {
		vi.useFakeTimers();
		const writeText = vi.fn(() => Promise.resolve());
		withClipboard(writeText);
		await show();
		expect(screen.getByText(PATH).tagName).toBe('CODE');
		const status = screen.getByRole('status');
		expect(status.textContent).toBe('');
		await fireEvent.click(screen.getByRole('button', { name: 'Copy share path' }));
		expect(writeText).toHaveBeenCalledWith(PATH);
		expect(status).toHaveTextContent('Copied');
		await vi.advanceTimersByTimeAsync(4000);
		expect(status.textContent).toBe('');
	});

	it('says when copying failed', async () => {
		withClipboard(() => Promise.reject(new Error('denied')));
		await show();
		await fireEvent.click(screen.getByRole('button', { name: 'Copy share path' }));
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't copy; select the text instead.");
	});

	it('shows the text alone without a clipboard', async () => {
		await show();
		expect(screen.getByText(PATH)).toBeInTheDocument();
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('offers a line break after each slash of a path, and copies the path as it is', async () => {
		// Browsers offer no break after a slash: a path would break inside a segment.
		const writeText = vi.fn(() => Promise.resolve());
		withClipboard(writeText);
		await show();
		const code = screen.getByText(PATH);
		expect(code.textContent).toBe(PATH);
		const segments = [...code.childNodes]
			.filter((node) => node.nodeType === Node.TEXT_NODE && node.textContent !== '')
			.map((node) => node.textContent);
		expect(segments).toEqual(['/', 'projects/', 'huron/', 'helio/', 'heliophysics/', 'fields']);
		expect(code.querySelectorAll('wbr')).toHaveLength(segments.length - 1);
		await fireEvent.click(screen.getByRole('button', { name: 'Copy share path' }));
		expect(writeText).toHaveBeenCalledWith(PATH);
	});
});
