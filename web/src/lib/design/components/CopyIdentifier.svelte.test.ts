import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CopyIdentifier from './CopyIdentifier.svelte';
afterEach(() => Reflect.deleteProperty(navigator, 'clipboard'));
const value = 'heliophysics.solar-wind.ace.mag-l2-2024';
describe('CopyIdentifier', () => {
	it('copies the complete path and announces success without repeating the path', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		render(CopyIdentifier, { value });
		await tick();
		await fireEvent.click(screen.getByRole('button', { name: 'Copy full path' }));
		expect(writeText).toHaveBeenCalledWith(value);
		expect(screen.getByRole('status')).toHaveTextContent('Copied');
		expect(screen.queryByText(value)).toBeNull();
	});
	it('makes the complete path selectable when the clipboard is unavailable', async () => {
		render(CopyIdentifier, { value });
		await tick();
		expect(screen.queryByRole('button', { name: 'Copy full path' })).toBeNull();
		screen.getByLabelText('Show full path').click();
		const field = screen.getByRole('textbox', { name: 'Full path' });
		expect(field).toHaveValue(value);
		expect(field).toHaveAttribute('readonly');
		await fireEvent.focus(field);
		expect(field instanceof HTMLInputElement && field.selectionEnd).toBe(value.length);
	});
	it('reveals a selectable path after a rejected clipboard write', async () => {
		Object.defineProperty(navigator, 'clipboard', {
			value: { writeText: () => Promise.reject(new Error('denied')) },
			configurable: true
		});
		render(CopyIdentifier, { value });
		await tick();
		await fireEvent.click(screen.getByRole('button', { name: 'Copy full path' }));
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't copy");
		expect(screen.getByRole('textbox', { name: 'Full path' })).toHaveValue(value);
	});
});
