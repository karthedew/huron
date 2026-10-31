// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { integerDigits } from '$lib/json';
import {
	DecodeError,
	JsonFields,
	asArray,
	asBoolean,
	asInteger,
	asNullable,
	asObject,
	asString,
	asStrings,
	isJsonObject,
	parseJson,
	parseJsonExactly
} from './json';

describe('parseJson', () => {
	it('parses JSON and answers undefined for anything else', () => {
		expect(parseJson('{"a":[1,true,null]}')).toEqual({ a: [1, true, null] });
		expect(parseJson('"text"')).toBe('text');
		expect(parseJson('not json')).toBeUndefined();
		expect(parseJson('')).toBeUndefined();
	});

	it('parses plainly, keeping no digits on the side', () => {
		const value = parseJson('{"maximum":9223372036854775807}');
		expect(isJsonObject(value) && integerDigits(value, 'maximum')).toBeNull();
	});
});

describe('parseJsonExactly', () => {
	it('keeps the digits of an integer too large for a number', () => {
		const text = '{"maximum":9223372036854775807}';
		const value = parseJsonExactly(text);
		expect(value).toEqual(JSON.parse(text));
		expect(isJsonObject(value) && integerDigits(value, 'maximum')).toBe('9223372036854775807');
	});

	it('answers undefined for anything that is not JSON', () => {
		expect(parseJsonExactly('not json')).toBeUndefined();
		expect(parseJsonExactly('')).toBeUndefined();
	});
});

describe('decoders', () => {
	it('accept their own type', () => {
		expect(asString('a', 'x')).toBe('a');
		expect(asInteger(3, 'x')).toBe(3);
		expect(asBoolean(false, 'x')).toBe(false);
		expect(asObject({ a: 1 }, 'x')).toEqual({ a: 1 });
		expect(asStrings(['a', 'b'], 'x')).toEqual(['a', 'b']);
		expect(asNullable(asString)(null, 'x')).toBeNull();
		expect(asNullable(asString)(undefined, 'x')).toBeNull();
		expect(asNullable(asString)('a', 'x')).toBe('a');
		expect(isJsonObject({})).toBe(true);
		expect(isJsonObject([])).toBe(false);
		expect(isJsonObject(null)).toBe(false);
	});

	it.each([
		[() => asString(1, 'answer.name'), 'answer.name is not a string'],
		[() => asInteger(1.5, 'answer.count'), 'answer.count is not an integer'],
		[() => asInteger('1', 'answer.count'), 'answer.count is not an integer'],
		[() => asBoolean('true', 'answer.flag'), 'answer.flag is not a boolean'],
		[() => asObject([], 'answer'), 'answer is not an object'],
		[() => asObject(null, 'answer'), 'answer is not an object'],
		[() => asArray(asString)({}, 'answer.items'), 'answer.items is not an array'],
		[() => asStrings(['a', 2], 'answer.groups'), 'answer.groups[1] is not a string']
	])('name the offending value', (decode, message) => {
		expect(decode).toThrow(DecodeError);
		expect(decode).toThrow(message);
	});
});

describe('JsonFields', () => {
	it('reads own properties only', () => {
		const fields = new JsonFields(parseJson('{"name":"helio","count":2,"tags":["a"]}'), 'answer');
		expect(fields.string('name')).toBe('helio');
		expect(fields.integer('count')).toBe(2);
		expect(fields.strings('tags')).toEqual(['a']);
		expect(fields.raw('constructor')).toBeUndefined();
		expect(fields.raw('toString')).toBeUndefined();
		expect(() => fields.string('missing')).toThrow('answer.missing is not a string');
	});

	it('reads nullable values', () => {
		const fields = new JsonFields({ a: null, b: 'x', c: 1, d: { e: true }, f: false }, 'answer');
		expect(fields.nullableString('a')).toBeNull();
		expect(fields.nullableString('b')).toBe('x');
		expect(fields.nullableInteger('a')).toBeNull();
		expect(fields.nullableInteger('c')).toBe(1);
		expect(fields.nullableObject('a')).toBeNull();
		expect(fields.nullableObject('d')).toEqual({ e: true });
		expect(fields.object('d')).toEqual({ e: true });
		expect(fields.boolean('f')).toBe(false);
		expect(fields.get('d', asObject)).toEqual({ e: true });
	});

	it('requires an object', () => {
		expect(() => new JsonFields('text', 'answer')).toThrow('answer is not an object');
	});
});
