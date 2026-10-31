import { describe, expect, it } from 'vitest';
import { displayName, secondaryName } from './names';

describe('displayName', () => {
	it('prefers the display name', () => {
		expect(displayName({ name: 'helio', display_name: 'Heliophysics Division' })).toBe(
			'Heliophysics Division'
		);
	});

	it('falls back to the name when there is no display name', () => {
		expect(displayName({ name: 'geo', display_name: '' })).toBe('geo');
	});
});

describe('secondaryName', () => {
	it('shows the name next to a different display name', () => {
		expect(secondaryName({ name: 'helio', display_name: 'Heliophysics Division' })).toBe('helio');
	});

	it('shows nothing when the display name is missing or the same', () => {
		expect(secondaryName({ name: 'geo', display_name: '' })).toBeNull();
		expect(secondaryName({ name: 'geo', display_name: 'geo' })).toBeNull();
	});
});
