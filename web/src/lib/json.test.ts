import { describe, expect, it } from 'vitest';
import type { JsonObject, JsonValue } from '$api/types';
import { parsedObject } from '$lib/testing/json';
import {
	booleanField,
	exactJson,
	hasInexactIntegers,
	integerDigits,
	isJsonDocument,
	isJsonObject,
	isJsonValue,
	isRecord,
	numberField,
	ownValue,
	parseExactly,
	stringField
} from './json';

describe('fields of an object', () => {
	const object = parsedObject('{"text":"a","count":2,"flag":false,"none":null,"__proto__":"own"}');

	it('reads own properties of the expected kind only', () => {
		expect(stringField(object, 'text')).toBe('a');
		expect(stringField(object, 'count')).toBeNull();
		expect(numberField(object, 'count')).toBe(2);
		expect(numberField(object, 'text')).toBeNull();
		expect(booleanField(object, 'flag')).toBe(false);
		expect(booleanField(object, 'none')).toBeNull();
		expect(ownValue(object, '__proto__')).toBe('own');
	});

	it('never reads inherited properties', () => {
		expect(ownValue({}, 'toString')).toBeUndefined();
		expect(stringField({}, 'constructor')).toBeNull();
		const child: Record<string, unknown> = Object.create({ inherited: 1 });
		expect(ownValue(child, 'inherited')).toBeUndefined();
	});

	it('knows an object from an array and null', () => {
		expect(isJsonObject({})).toBe(true);
		expect(isJsonObject([])).toBe(false);
		expect(isJsonObject(null)).toBe(false);
		expect(isJsonObject(undefined)).toBe(false);
	});
});

describe('isJsonValue', () => {
	it('accepts what JSON can hold, all the way down', () => {
		for (const value of [null, true, 0, -1.5, '', 'text', [], {}, { a: [1, { b: null }] }]) {
			expect(isJsonValue(value), JSON.stringify(value)).toBe(true);
		}
	});

	it('refuses what JSON cannot hold, also deep inside', () => {
		for (const value of [
			undefined,
			Number.NaN,
			Number.POSITIVE_INFINITY,
			() => 1,
			Symbol('s'),
			10n,
			{ a: [1, undefined] },
			[{ b: Number.NaN }]
		]) {
			expect(isJsonValue(value), String(typeof value)).toBe(false);
		}
	});
});

describe('isJsonDocument', () => {
	it('accepts a JSON object', () => {
		expect(isJsonDocument({ type: 'object', properties: { a: { type: 'string' } } })).toBe(true);
		expect(isJsonDocument(parsedObject('{"__proto__":{"x":1}}'))).toBe(true);
	});

	it('refuses anything else', () => {
		for (const value of [null, undefined, [], 'text', 1, { a: () => 1 }]) {
			expect(isJsonDocument(value)).toBe(false);
		}
	});
});

describe('integers too large for a number', () => {
	const TEXT =
		'{"minimum":-9223372036854775807,"maximum":9223372036854775807,' +
		'"enum":[9007199254740993,9007199254740991,1.5],"deep":{"rows":[[12345678901234567890]]},' +
		'"label":"12345678901234567890","small":2}';

	function object(value: JsonValue | undefined): JsonObject {
		if (!isJsonObject(value)) throw new Error('not a JSON object');
		return value;
	}

	function array(value: JsonValue | undefined): JsonValue[] {
		if (!Array.isArray(value)) throw new Error('not a JSON array');
		return value;
	}

	it('parse to the numbers JSON.parse gives, with their own digits kept beside them', () => {
		const value = object(parseExactly(TEXT));
		expect(value).toEqual(JSON.parse(TEXT));
		expect(integerDigits(value, 'minimum')).toBe('-9223372036854775807');
		expect(integerDigits(value, 'maximum')).toBe('9223372036854775807');
		const enumeration = array(value.enum);
		expect(['0', '1', '2'].map((index) => integerDigits(enumeration, index))).toEqual([
			'9007199254740993',
			null,
			null
		]);
		const row = array(array(object(value.deep).rows)[0]);
		expect(integerDigits(row, '0')).toBe('12345678901234567890');
		expect(integerDigits(value, 'label')).toBeNull();
		expect(integerDigits(value, 'small')).toBeNull();
	});

	it('are written back with their own digits', () => {
		const value = parseExactly(TEXT);
		expect(JSON.stringify(value)).not.toBe(TEXT);
		expect(exactJson(value)).toBe(TEXT);
		expect(exactJson(value, 2)).toContain('"maximum": 9223372036854775807,');
	});

	it('leave everything else as JSON.parse and JSON.stringify have it', () => {
		const text =
			'{"id":"0192f2a4","count":9007199254740991,"sha":"98765432109876543210","x":[1e300,-0.5]}';
		const value = parseExactly(text);
		expect(value).toEqual(JSON.parse(text));
		expect(exactJson(value)).toBe(JSON.stringify(value));
		expect(exactJson(value, 2)).toBe(JSON.stringify(value, null, 2));
		expect(integerDigits(object(value), 'count')).toBeNull();
	});

	it('keep a __proto__ key a property of its own, as JSON.parse does', () => {
		const value = object(parseExactly('{"__proto__":{"epoch":9223372036854775807}}'));
		expect(Object.getPrototypeOf(value)).toBe(Object.prototype);
		expect(integerDigits(object(ownValue(value, '__proto__')), 'epoch')).toBe(
			'9223372036854775807'
		);
	});

	it('come only from text that is JSON', () => {
		expect(() => parseExactly('not json')).toThrow(SyntaxError);
		expect(() => parseExactly('[12345678901234567890')).toThrow(SyntaxError);
	});
});

describe('isRecord', () => {
	it('knows an object from an array, null and other values', () => {
		expect(isRecord({})).toBe(true);
		expect(isRecord(parsedObject('{"__proto__":1}'))).toBe(true);
		expect(isRecord([])).toBe(false);
		expect(isRecord(null)).toBe(false);
		expect(isRecord('{}')).toBe(false);
		expect(isRecord(undefined)).toBe(false);
	});
});

describe('hasInexactIntegers', () => {
	it('finds a number past 2^53 anywhere a plain parse may have rounded one', () => {
		expect(hasInexactIntegers(JSON.parse('{"a":[{"b":9223372036854775807}]}'))).toBe(true);
		expect(hasInexactIntegers(-(2 ** 60))).toBe(true);
		// Every number that large is an integer; only an exact parse can tell what was written.
		expect(hasInexactIntegers({ a: 1e300 })).toBe(true);
	});

	it('finds none among safe integers, fractions, text and other values', () => {
		expect(
			hasInexactIntegers({
				safe: Number.MAX_SAFE_INTEGER,
				third: 1 / 3,
				text: '9223372036854775807',
				list: [null, true, -1.5e-300]
			})
		).toBe(false);
		expect(hasInexactIntegers(null)).toBe(false);
	});

	it('walks a value that nests deeper than the call stack allows', () => {
		let deep: unknown = 2 ** 60;
		for (let level = 0; level < 100_000; level += 1) deep = [deep];
		expect(hasInexactIntegers(deep)).toBe(true);
		expect(hasInexactIntegers(new Array(200_000).fill(1))).toBe(false);
	});
});
