import { describe, expect, it } from 'vitest';
import { addFilesHint, cliCommand, collectionHints, quote, type CliCommand } from './cli';

describe('cliCommand', () => {
	it.each<[CliCommand, string]>([
		[
			{
				verb: 'checkout',
				catalog: 'heliophysics',
				collection: 'heliophysics.solar-wind.ace.mag-l2-2024'
			},
			'huron --catalog heliophysics checkout heliophysics.solar-wind.ace.mag-l2-2024'
		],
		[{ verb: 'add', catalog: 'heliophysics' }, 'huron --catalog heliophysics add <file>…'],
		[{ verb: 'push', catalog: 'heliophysics' }, 'huron --catalog heliophysics push -m "<message>"'],
		[
			{
				verb: 'collection activate',
				catalog: 'heliophysics',
				collection: 'heliophysics.solar-wind.ace.mag-l1-draft'
			},
			'huron --catalog heliophysics collection activate heliophysics.solar-wind.ace.mag-l1-draft'
		],
		[
			{
				verb: 'meta edit',
				catalog: 'space-weather',
				collection: 'space-weather.alerts.flare-list-2024'
			},
			'huron --catalog space-weather meta edit space-weather.alerts.flare-list-2024'
		],
		[
			{
				verb: 'meta publish',
				catalog: 'space-weather',
				collection: 'space-weather.alerts.flare-list-2024'
			},
			'huron --catalog space-weather meta publish space-weather.alerts.flare-list-2024'
		],
		[
			{ verb: 'meta override set', catalog: 'adv-cat', collection: 'adv-cat.box.clash' },
			'huron --catalog adv-cat meta override set <override.json> adv-cat.box.clash'
		],
		[
			{ verb: 'meta override clear', catalog: 'adv-cat', collection: 'adv-cat.box.clash' },
			'huron --catalog adv-cat meta override clear adv-cat.box.clash'
		],
		[
			{ verb: 'collection create', catalog: 'heliophysics', namespace: 'heliophysics.fields' },
			'huron --catalog heliophysics collection create heliophysics.fields.<name>'
		],
		[
			{
				verb: 'namespace create',
				catalog: 'heliophysics',
				parent: 'heliophysics',
				allowCollections: false
			},
			'huron --catalog heliophysics namespace create heliophysics.<name>'
		],
		[
			{
				verb: 'namespace create',
				catalog: 'heliophysics',
				parent: 'heliophysics.solar-wind',
				allowCollections: true
			},
			'huron --catalog heliophysics namespace create heliophysics.solar-wind.<name> --allow-collections'
		],
		[
			{ verb: 'catalog grant', catalog: 'heliophysics' },
			'huron --catalog heliophysics catalog grant heliophysics <role> <ldap-group>'
		],
		[
			{ verb: 'acl apply', catalog: 'heliophysics' },
			'huron --catalog heliophysics acl apply heliophysics --recursive'
		],
		[{ verb: 'catalog create', organization: 'helio' }, 'huron catalog create helio <name>'],
		[{ verb: 'search', catalog: 'heliophysics' }, 'huron search heliophysics'],
		[
			{
				verb: 'search',
				catalog: 'heliophysics',
				q: "solar wind's",
				labels: ['mission=ace', 'note=a b'],
				states: ['active', 'draft']
			},
			`huron search heliophysics -q 'solar wind'\\''s' -l mission=ace -l 'note=a b' --state active --state draft`
		]
	])('writes %o as %s', (command, line) => {
		expect(cliCommand(command)).toBe(line);
	});

	it('keeps the full identifier when a namespace is named like its catalog', () => {
		const line = cliCommand({
			verb: 'checkout',
			catalog: 'heliophysics',
			collection: 'heliophysics.heliophysics.run-1'
		});
		expect(line).toBe('huron --catalog heliophysics checkout heliophysics.heliophysics.run-1');
		const create = cliCommand({
			verb: 'collection create',
			catalog: 'heliophysics',
			namespace: 'heliophysics.heliophysics'
		});
		expect(create).toBe(
			'huron --catalog heliophysics collection create heliophysics.heliophysics.<name>'
		);
	});
});

describe('quote', () => {
	it('leaves plain words bare and single-quotes everything else', () => {
		expect(quote('heliophysics.solar-wind')).toBe('heliophysics.solar-wind');
		expect(quote('key=value')).toBe('key=value');
		expect(quote('a b')).toBe("'a b'");
		expect(quote('$(rm -rf ~)')).toBe("'$(rm -rf ~)'");
		expect(quote("it's")).toBe(`'it'\\''s'`);
		expect(quote('')).toBe("''");
		expect(quote('Straße 😀')).toBe("'Straße 😀'");
	});

	it('quotes a word that starts with =, which zsh would expand to a command path', () => {
		expect(quote('=ls')).toBe("'=ls'");
		expect(quote('=')).toBe("'='");
		expect(cliCommand({ verb: 'search', catalog: 'heliophysics', q: '=wind' })).toBe(
			"huron search heliophysics -q '=wind'"
		);
	});

	it.each([
		// Pasted into a terminal, Ctrl-U erases the line typed so far and a carriage return runs it.
		['x\u0015rm -rf ~ #\ry', "$'x\\025rm -rf ~ #\\ry'"],
		// An escape sequence that would end a bracketed paste early.
		['wind\u001b[201~\u0015echo pwned\r', "$'wind\\033[201~\\025echo pwned\\r'"],
		['line one\nline two', "$'line one\\nline two'"],
		['a\tb', "$'a\\tb'"],
		['\u007f and \u009b', "$'\\177 and \\302\\233'"],
		// Format characters redraw or hide text: a right-to-left override, a zero-width joiner.
		['abc\u202edef', "$'abc\\342\\200\\256def'"],
		['a\u200db', "$'a\\342\\200\\215b'"],
		['one\u2028two\u2029', "$'one\\342\\200\\250two\\342\\200\\251'"],
		// Inside $'…', only the backslash and the quote need escapes of their own.
		["it's a\\b\u0015", "$'it\\047s a\\\\b\\025'"]
	])('writes the control and format characters of %j as escapes: %s', (value, quoted) => {
		expect(quote(value)).toBe(quoted);
		expect(quote(value)).not.toMatch(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u);
		expect(unquote(quoted)).toBe(value);
	});

	it('keeps a search hint on one line of visible characters, whatever the address holds', () => {
		const command = cliCommand({
			verb: 'search',
			catalog: 'heliophysics',
			q: 'x\u0015rm -rf ~ #\ry',
			labels: ['note=\u202eevil', 'line=a\nb']
		});
		expect(command).toBe(
			"huron search heliophysics -q $'x\\025rm -rf ~ #\\ry' -l $'note=\\342\\200\\256evil' -l $'line=a\\nb'"
		);
		expect(command).not.toMatch(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u);
	});
});

describe('collectionHints', () => {
	const ACTIVE = {
		catalog: 'heliophysics',
		identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
		state: 'active',
		hasProblems: false,
		overrideIncompatible: false
	};

	it('shows readers how to check the collection out, and nothing else', () => {
		expect(collectionHints(ACTIVE, false)).toEqual([
			{
				title: 'Check out this collection',
				command: 'huron --catalog heliophysics checkout heliophysics.solar-wind.ace.mag-l2-2024'
			}
		]);
		expect(
			collectionHints({ ...ACTIVE, state: 'incomplete', hasProblems: true }, false)
		).toHaveLength(1);
		expect(
			collectionHints({ ...ACTIVE, state: 'incomplete', overrideIncompatible: true }, false)
		).toHaveLength(1);
	});

	it('shows contributors how to add files to this collection and push them', () => {
		expect(collectionHints(ACTIVE, true).map(({ title }) => title)).toEqual([
			'Check out this collection',
			'Add files to this collection'
		]);
		expect(collectionHints(ACTIVE, true)[1]).toEqual(addFilesHint(ACTIVE));
	});

	it('shows contributors how to complete and publish the metadata of an incomplete collection', () => {
		const hints = collectionHints(
			{
				catalog: 'space-weather',
				identifier: 'space-weather.alerts.flare-list-2024',
				state: 'incomplete',
				hasProblems: true,
				overrideIncompatible: false
			},
			true
		);
		expect(hints.map(({ title }) => title)).toEqual([
			'Check out this collection',
			'Complete the metadata, then publish it',
			'Add files to this collection'
		]);
		expect(hints[1].command).toBe(
			'huron --catalog space-weather meta edit space-weather.alerts.flare-list-2024\n' +
				'huron --catalog space-weather meta publish space-weather.alerts.flare-list-2024'
		);
	});

	it('shows contributors how to activate a draft, after its metadata if that has problems', () => {
		const draft = {
			...ACTIVE,
			identifier: 'heliophysics.solar-wind.ace.mag-l1-draft',
			state: 'draft'
		};
		expect(collectionHints(draft, true).map(({ title }) => title)).toEqual([
			'Check out this collection',
			'Activate this draft'
		]);
		const lacking = collectionHints({ ...draft, hasProblems: true }, true);
		expect(lacking.map(({ title }) => title)).toEqual([
			'Check out this collection',
			'Complete the metadata, then publish it',
			'Activate this draft'
		]);
		expect(lacking[2].command).toBe(
			'huron --catalog heliophysics collection activate heliophysics.solar-wind.ace.mag-l1-draft'
		);
	});

	it('shows contributors how to replace or remove a schema override that no longer fits', () => {
		const clash = {
			catalog: 'adv-cat',
			identifier: 'adv-cat.box.clash',
			state: 'incomplete',
			hasProblems: true,
			overrideIncompatible: true
		};
		const hints = collectionHints(clash, true);
		// `meta edit` needs the resolved schema, which the API refuses while the override clashes.
		expect(hints).toEqual([
			{
				title: 'Check out this collection',
				command: 'huron --catalog adv-cat checkout adv-cat.box.clash'
			},
			{
				title: 'Replace the schema override with one that fits',
				command: 'huron --catalog adv-cat meta override set <override.json> adv-cat.box.clash'
			},
			{
				title: 'Remove the schema override',
				command: 'huron --catalog adv-cat meta override clear adv-cat.box.clash'
			},
			addFilesHint(clash)
		]);
		expect(collectionHints({ ...clash, state: 'draft' }, true).map(({ title }) => title)).toEqual([
			'Check out this collection',
			'Replace the schema override with one that fits',
			'Remove the schema override',
			'Activate this draft'
		]);
	});
});

describe('addFilesHint', () => {
	it('checks the collection out, stages files, then pushes them with a message', () => {
		// `add` and `push` act on the collection checked out last, whichever that is.
		expect(
			addFilesHint({ catalog: 'heliophysics', identifier: 'heliophysics.fields.run001' })
		).toEqual({
			title: 'Add files to this collection',
			command:
				'huron --catalog heliophysics checkout heliophysics.fields.run001\n' +
				'huron --catalog heliophysics add <file>…\n' +
				'huron --catalog heliophysics push -m "<message>"'
		});
	});
});

/**
 * What a shell makes of one word `quote` writes with escapes, `$'…'`: the escapes it uses, octal
 * bytes read as UTF-8.
 */
function unquote(word: string): string {
	const body = /^\$'(.*)'$/su.exec(word)?.[1];
	if (body === undefined) throw new Error(`not a $'…' word: ${word}`);
	const bytes: number[] = [];
	const encoder = new TextEncoder();
	const named: Record<string, string> = { t: '\t', n: '\n', r: '\r', '\\': '\\' };
	for (let at = 0; at < body.length;) {
		const octal = /^\\([0-7]{3})/.exec(body.slice(at));
		if (octal !== null) {
			bytes.push(Number.parseInt(octal[1], 8));
			at += 4;
		} else if (body[at] === '\\') {
			const letter = body[at + 1];
			if (!Object.hasOwn(named, letter)) throw new Error(`unknown escape \\${letter}`);
			bytes.push(...encoder.encode(named[letter]));
			at += 2;
		} else {
			const point = String.fromCodePoint(body.codePointAt(at) ?? 0);
			bytes.push(...encoder.encode(point));
			at += point.length;
		}
	}
	return new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(bytes));
}
