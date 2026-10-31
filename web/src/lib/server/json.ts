import type { JsonObject, JsonValue } from '$api/types';
import { isJsonObject, parseExactly } from '../json';

export { isJsonObject };

/** A JSON document did not have the expected shape; `path` names the offending value. */
export class DecodeError extends Error {
	readonly path: string;

	constructor(path: string, expected: string) {
		super(`${path} is not ${expected}`);
		this.name = 'DecodeError';
		this.path = path;
	}
}

export type Decoder<T> = (value: JsonValue | undefined, path: string) => T;

/** Parse JSON text; `undefined` when it is not JSON. */
export function parseJson(text: string): JsonValue | undefined {
	try {
		// JSON.parse only ever produces JSON values, so the declared type is exact.
		const value: JsonValue = JSON.parse(text);
		return value;
	} catch {
		return undefined;
	}
}

/**
 * `parseJson`, keeping the digits of integers past 2^53 on the side (`parseExactly`), for the
 * answers whose digits a page shows: schema documents. Its reviver costs many times a plain
 * parse for every value, and any run of 16 digits sets it off (an ordinary float such as 1/3
 * writes 16), so lists, searches and collections are parsed plainly: their metadata can hold no
 * such integer, and one heavy answer would hold the web's single process for seconds.
 */
export function parseJsonExactly(text: string): JsonValue | undefined {
	try {
		return parseExactly(text);
	} catch {
		return undefined;
	}
}

export const asObject: Decoder<JsonObject> = (value, path) => {
	if (isJsonObject(value)) return value;
	throw new DecodeError(path, 'an object');
};

export const asString: Decoder<string> = (value, path) => {
	if (typeof value === 'string') return value;
	throw new DecodeError(path, 'a string');
};

export const asInteger: Decoder<number> = (value, path) => {
	if (typeof value === 'number' && Number.isSafeInteger(value)) return value;
	throw new DecodeError(path, 'an integer');
};

export const asBoolean: Decoder<boolean> = (value, path) => {
	if (typeof value === 'boolean') return value;
	throw new DecodeError(path, 'a boolean');
};

export function asNullable<T>(decode: Decoder<T>): Decoder<T | null> {
	return (value, path) => (value === null || value === undefined ? null : decode(value, path));
}

export function asArray<T>(decode: Decoder<T>): Decoder<T[]> {
	return (value, path) => {
		if (!Array.isArray(value)) throw new DecodeError(path, 'an array');
		return value.map((item, index) => decode(item, `${path}[${index}]`));
	};
}

export const asStrings: Decoder<string[]> = asArray(asString);

/** Typed access to the own properties of a JSON object. */
export class JsonFields {
	readonly #object: JsonObject;
	readonly #path: string;

	constructor(value: JsonValue | undefined, path: string) {
		this.#object = asObject(value, path);
		this.#path = path;
	}

	/** The raw value of an own property; inherited properties never count. */
	raw(key: string): JsonValue | undefined {
		return Object.hasOwn(this.#object, key) ? this.#object[key] : undefined;
	}

	get<T>(key: string, decode: Decoder<T>): T {
		return decode(this.raw(key), `${this.#path}.${key}`);
	}

	string(key: string): string {
		return this.get(key, asString);
	}

	integer(key: string): number {
		return this.get(key, asInteger);
	}

	boolean(key: string): boolean {
		return this.get(key, asBoolean);
	}

	strings(key: string): string[] {
		return this.get(key, asStrings);
	}

	object(key: string): JsonObject {
		return this.get(key, asObject);
	}

	nullableString(key: string): string | null {
		return this.get(key, asNullable(asString));
	}

	nullableInteger(key: string): number | null {
		return this.get(key, asNullable(asInteger));
	}

	nullableObject(key: string): JsonObject | null {
		return this.get(key, asNullable(asObject));
	}
}
