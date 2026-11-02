/**
 * Deterministic formatting: a fixed locale and fixed units, so server and browser render the
 * same text and nothing depends on the viewer's locale or clock.
 */

const COUNT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const UNIT_VALUE = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const BYTE_UNITS = ['kB', 'MB', 'GB', 'TB', 'PB', 'EB'] as const;
const LIST = new Intl.ListFormat('en-US', { style: 'long', type: 'conjunction' });

/** Names in a sentence: `A`, `A and B`, `A, B, and C`. */
export function formatList(items: readonly string[]): string {
	return LIST.format(items);
}

/** A count with grouping: `1,234`; a `bigint` keeps every digit past 2^53. */
export function formatCount(value: number | bigint): string {
	return COUNT.format(value);
}

/** A count with its noun: `1 catalog`, `1,234 catalogs`. */
export function countLabel(
	value: number | bigint,
	singular: string,
	plural = `${singular}s`
): string {
	return `${formatCount(value)} ${value === 1 || value === 1n ? singular : plural}`;
}

/**
 * A metadata number as JSON writes it: the shortest text that reads back as the same number,
 * never grouped and never rounded to another. Plain digits from 1e-6 up to 1e21 (`2024`,
 * `0.000125`), an exponent beyond them (`6.62607015e-34`, `-1e+31`), so a tiny value never reads
 * as `0` and a huge one never as hundreds of digits. Unlike `toLocaleString`, it ignores the
 * locale.
 */
export function formatNumber(value: number): string {
	return String(value);
}

/** A size in decimal units: `999 B`, `1.2 MB`. The exact byte count belongs in a `title`. */
export function formatBytes(bytes: number): string {
	if (!Number.isFinite(bytes) || Math.abs(bytes) < 1000) return `${formatCount(bytes)} B`;
	let unit = 0;
	let value = bytes / 1000;
	while (Math.abs(oneDecimal(value)) >= 1000 && unit < BYTE_UNITS.length - 1) {
		value /= 1000;
		unit += 1;
	}
	return `${UNIT_VALUE.format(oneDecimal(value))} ${BYTE_UNITS[unit]}`;
}

/** `YYYY-MM-DD HH:mm UTC`; unparseable input is returned unchanged. */
export function formatTimestamp(iso: string): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return iso;
	const text = date.toISOString();
	return `${text.slice(0, 10)} ${text.slice(11, 16)} UTC`;
}

/** The value for `<time datetime>`: normalized ISO 8601 in UTC, or the input if unparseable. */
export function timestampAttribute(iso: string): string {
	const date = new Date(iso);
	return Number.isNaN(date.getTime()) ? iso : date.toISOString();
}

/** `YYYY-MM-DD` for a JSON Schema `date` (or the date part of a timestamp), in UTC. */
export function formatDate(value: string): string {
	if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
	const date = new Date(value);
	return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(0, 10);
}

/** A text cut to a length, and what the cut kept. */
export interface ClippedText {
	/** At most the limit's code points of the text, and `…` where it goes on. */
	text: string;
	/** How many code points of the text it holds, the `…` aside. */
	kept: number;
	/** Whether the text goes on beyond them. */
	cut: boolean;
}

/**
 * At most `limit` code points of a text, and `…` where it goes on. Whole code points only, so a
 * surrogate pair is never split; it reads no further than the limit, however long the text.
 * Contributors' texts may each take up a mebibyte, which a page must not repeat.
 */
export function clip(text: string, limit: number): ClippedText {
	let end = 0;
	let kept = 0;
	for (const point of text) {
		if (kept >= limit) return { text: `${text.slice(0, end)}…`, kept, cut: true };
		end += point.length;
		kept += 1;
	}
	return { text, kept, cut: false };
}

/** `clip`'s text alone: at most `limit` code points of a text, and `…` where it goes on. */
export function shortened(text: string, limit: number): string {
	return clip(text, limit).text;
}

/**
 * The last 12 hex digits of a UUID. UUIDv7 ids share their time prefix, so the tail is the part
 * that tells two ids apart.
 */
export function shortId(id: string): string {
	return id.replaceAll('-', '').slice(-12);
}

function oneDecimal(value: number): number {
	return Math.round(value * 10) / 10;
}
