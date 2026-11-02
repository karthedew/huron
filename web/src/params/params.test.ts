// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { match as dotted } from './dotted';
import { match as segment } from './segment';
import { match as uuid } from './uuid';

describe('segment', () => {
	it.each(['a', '0', 'helio', 'space-weather', 'run_001', `a${'b'.repeat(62)}`])(
		'accepts %j',
		(value) => {
			expect(segment(value)).toBe(true);
		}
	);

	it.each(['', '-a', '_a', 'Helio', 'a.b', 'a b', 'a/b', '..', `a${'b'.repeat(63)}`, 'café'])(
		'rejects %j',
		(value) => {
			expect(segment(value)).toBe(false);
		}
	);
});

describe('dotted', () => {
	it.each(['solar-wind', 'solar-wind.ace', 'deep.a.b.c', 'heliophysics.heliophysics'])(
		'accepts %j',
		(value) => {
			expect(dotted(value)).toBe(true);
		}
	);

	it('accepts up to 255 characters', () => {
		const segment63 = 'a'.repeat(63);
		const longest = [segment63, segment63, segment63, 'a'.repeat(63)].join('.');
		expect(longest).toHaveLength(255);
		expect(dotted(longest)).toBe(true);
		expect(dotted(`${longest.slice(0, 254)}.a`)).toBe(false);
	});

	it.each(['', '.', 'a.', '.a', 'a..b', 'a.B', 'a.-b', 'a/b', 'a.b c'])('rejects %j', (value) => {
		expect(dotted(value)).toBe(false);
	});
});

describe('uuid', () => {
	it.each(['0192f2a4-0000-7000-8000-000000000401', '0192F2A4-0000-7000-8000-00000000040A'])(
		'accepts %j',
		(value) => {
			expect(uuid(value)).toBe(true);
		}
	);

	it.each([
		'',
		'0192f2a400007000800000000000040a',
		'{0192f2a4-0000-7000-8000-000000000401}',
		'0192f2a4-0000-7000-8000-00000000040',
		'0192f2a4-0000-7000-8000-0000000004011',
		'g192f2a4-0000-7000-8000-000000000401'
	])('rejects %j', (value) => {
		expect(uuid(value)).toBe(false);
	});
});
