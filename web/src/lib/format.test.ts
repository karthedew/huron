import { describe, expect, it } from 'vitest';
import {
	countLabel,
	formatBytes,
	formatCount,
	formatDate,
	formatList,
	formatNumber,
	formatTimestamp,
	shortId,
	timestampAttribute
} from './format';

describe('lists', () => {
	it('names one, two or more things in a sentence, in en-US', () => {
		expect(formatList([])).toBe('');
		expect(formatList(['Heliophysics'])).toBe('Heliophysics');
		expect(formatList(['Heliophysics', 'Space Weather'])).toBe('Heliophysics and Space Weather');
		expect(formatList(['A', 'B', 'C'])).toBe('A, B, and C');
	});
});

describe('counts and numbers', () => {
	it('groups counts in en-US', () => {
		expect(formatCount(0)).toBe('0');
		expect(formatCount(1234567)).toBe('1,234,567');
	});

	it('keeps every digit of a count too large for a number', () => {
		expect(formatCount(9223372036854775807n)).toBe('9,223,372,036,854,775,807');
		expect(countLabel(9007199254740993n, 'item')).toBe('9,007,199,254,740,993 items');
		expect(countLabel(1n, 'item')).toBe('1 item');
	});

	it('pairs a count with its noun', () => {
		expect(countLabel(1, 'catalog')).toBe('1 catalog');
		expect(countLabel(0, 'catalog')).toBe('0 catalogs');
		expect(countLabel(1200, 'file')).toBe('1,200 files');
		expect(countLabel(2, 'namespace', 'namespaces in total')).toBe('2 namespaces in total');
	});

	it('writes metadata numbers without grouping or rounding', () => {
		expect(formatNumber(2024)).toBe('2024');
		expect(formatNumber(0.000125)).toBe('0.000125');
		expect(formatNumber(-17.5)).toBe('-17.5');
		expect(formatNumber(0.1 + 0.2)).toBe('0.30000000000000004');
		expect(formatNumber(0.000001)).toBe('0.000001');
		expect(formatNumber(1e20)).toBe('100000000000000000000');
		expect(formatNumber(-0)).toBe('0');
	});

	it('writes tiny and huge numbers with an exponent, keeping every digit', () => {
		expect(formatNumber(6.62607015e-34)).toBe('6.62607015e-34');
		expect(formatNumber(1.602176634e-19)).toBe('1.602176634e-19');
		expect(formatNumber(1e-22)).toBe('1e-22');
		expect(formatNumber(-1e-25)).toBe('-1e-25');
		expect(formatNumber(1e-7)).toBe('1e-7');
		expect(formatNumber(5e-324)).toBe('5e-324');
		expect(formatNumber(1e21)).toBe('1e+21');
		expect(formatNumber(-1e31)).toBe('-1e+31');
		expect(formatNumber(1.7976931348623157e308)).toBe('1.7976931348623157e+308');
	});

	it('writes every number so that it reads back as the same number', () => {
		for (const value of [
			1.67262192e-27, -2.2250738585072014e-308, 1.1e-22, 0.1, 123456789.125, 9007199254740991, 1e300
		]) {
			expect(Number(formatNumber(value))).toBe(value);
		}
	});
});

describe('formatBytes', () => {
	it.each([
		[0, '0 B'],
		[999, '999 B'],
		[1000, '1 kB'],
		[1234, '1.2 kB'],
		[999_949, '999.9 kB'],
		[999_950, '1 MB'],
		[1_234_567, '1.2 MB'],
		[5_000_000_000, '5 GB'],
		[1.5e15, '1.5 PB'],
		[2e21, '2,000 EB']
	])('formats %d bytes as %s', (bytes, text) => {
		expect(formatBytes(bytes)).toBe(text);
	});
});

describe('timestamps', () => {
	it('formats instants in UTC regardless of their offset', () => {
		expect(formatTimestamp('2026-10-29T10:05:59.999+00:00')).toBe('2026-10-29 10:05 UTC');
		expect(formatTimestamp('2026-10-29T23:30:00-02:00')).toBe('2026-10-30 01:30 UTC');
		expect(formatTimestamp('2026-10-02T09:00:00.123456+00:00')).toBe('2026-10-02 09:00 UTC');
	});

	it('normalizes the datetime attribute to UTC', () => {
		expect(timestampAttribute('2026-10-29T23:30:00-02:00')).toBe('2026-10-30T01:30:00.000Z');
	});

	it('returns unparseable input unchanged', () => {
		expect(formatTimestamp('yesterday')).toBe('yesterday');
		expect(timestampAttribute('yesterday')).toBe('yesterday');
		expect(formatDate('soon')).toBe('soon');
	});

	it('writes dates as YYYY-MM-DD', () => {
		expect(formatDate('2024-02-29')).toBe('2024-02-29');
		expect(formatDate('2024-02-29T23:59:00-01:00')).toBe('2024-03-01');
	});
});

describe('shortId', () => {
	it('keeps the last 12 hex digits, where UUIDv7 ids differ', () => {
		expect(shortId('0192f2a4-0000-7000-8000-00000000040a')).toBe('00000000040a');
		expect(shortId('abc')).toBe('abc');
	});
});
