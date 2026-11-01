/**
 * `huron` commands shown as hints, in the CLI's `huron <verb> <noun>` form (IMPLEMENTATION_PLAN.md
 * §9). Verbs and flags follow `src/huron/applications/cli/commands/*.py`; each `verb` below is the
 * command's words as typed.
 *
 * Identifiers are always written in full and the catalog is passed with `--catalog`: the CLI's
 * `qualify()` prefixes the current catalog to any identifier that does not start with it, so a
 * shortened identifier, or a namespace named like its catalog, would resolve elsewhere. Every
 * command that acts in a catalog starts `huron --catalog <catalog>`, also `adm grant`, which grants a
 * catalog role on that catalog, and `search`, which searches it; only `create catalog`, which makes
 * one, and `adm grant` on an organization name the organization with `--org` instead.
 */

export type CliCommand =
	| { verb: 'checkout'; catalog: string; collection: string }
	| { verb: 'add'; catalog: string }
	| { verb: 'push'; catalog: string }
	| { verb: 'activate collection'; catalog: string; collection: string }
	| { verb: 'edit meta'; catalog: string; collection: string }
	| { verb: 'publish meta'; catalog: string; collection: string }
	| { verb: 'set override'; catalog: string; collection: string }
	| { verb: 'unset override'; catalog: string; collection: string }
	/** `namespace` is the full namespace identifier (`catalog.path`). */
	| { verb: 'create collection'; catalog: string; namespace: string }
	/** `parent` is the full parent identifier: the catalog, or `catalog.path`. */
	| { verb: 'create namespace'; catalog: string; parent: string; allowCollections: boolean }
	/** A catalog role (`catalog_admin`, `contributor`, `reader`) on the catalog given with `--catalog`. */
	| { verb: 'adm grant'; catalog: string }
	/**
	 * An organization role on the organization given with `adm grant`'s own `--org`: `org_admin`,
	 * or a catalog role, which then holds in every catalog of it.
	 */
	| { verb: 'adm grant'; organization: string }
	| { verb: 'adm apply-acl'; catalog: string }
	| { verb: 'create catalog'; organization: string }
	| {
			verb: 'search';
			catalog: string;
			q?: string;
			labels?: readonly string[];
			states?: readonly string[];
	  };

/** The command line for a hint. Placeholders the user replaces are written as `<name>`. */
export function cliCommand(command: CliCommand): string {
	switch (command.verb) {
		case 'checkout':
		case 'activate collection':
		case 'edit meta':
		case 'publish meta':
		case 'unset override':
			return line(command.catalog, command.verb, quote(command.collection));
		case 'set override':
			return line(command.catalog, command.verb, '<override.json>', quote(command.collection));
		case 'add':
			return line(command.catalog, 'add', '<file>…');
		case 'push':
			return line(command.catalog, 'push', '-m', '"<message>"');
		case 'create collection':
			return line(command.catalog, command.verb, `${quote(command.namespace)}.<name>`);
		case 'create namespace':
			return line(
				command.catalog,
				command.verb,
				`${quote(command.parent)}.<name>`,
				...(command.allowCollections ? ['--allow-collections'] : [])
			);
		case 'adm grant':
			if ('organization' in command) {
				return [
					'huron',
					command.verb,
					'<role>',
					'<ldap-group>',
					'--org',
					quote(command.organization)
				].join(' ');
			}
			return line(command.catalog, command.verb, '<role>', '<ldap-group>');
		case 'adm apply-acl':
			return line(command.catalog, command.verb, quote(command.catalog), '--recursive');
		case 'create catalog':
			return ['huron', command.verb, '<name>', '--org', quote(command.organization)].join(' ');
		case 'search':
			return line(
				command.catalog,
				'search',
				...(command.q ? ['-q', quote(command.q)] : []),
				...(command.labels ?? []).flatMap((label) => ['-l', quote(label)]),
				...(command.states ?? []).flatMap((state) => ['--state', quote(state)])
			);
	}
}

/** A hint: what the commands do, and the commands, one per line, to run in order. */
export interface Hint {
	title: string;
	command: string;
}

/** What the hints of a collection depend on. */
export interface HintedCollection {
	catalog: string;
	/** The full identifier. */
	identifier: string;
	state: string;
	/** Whether its metadata has problems the schema finds. */
	hasProblems: boolean;
	/**
	 * Whether its schema override no longer fits the catalog's schema. No schema can be resolved
	 * then, so `edit meta` cannot walk through one: the override has to be replaced or removed.
	 */
	overrideIncompatible: boolean;
}

/**
 * The hints of a collection's Overview. Everyone may check it out. Contributors also see how to
 * fix metadata the schema finds lacking (an incomplete collection, or a draft with problems,
 * which cannot be activated before) or a schema override that no longer fits, how to activate a
 * draft, and how to add files to a collection that has a directory.
 */
export function collectionHints(collection: HintedCollection, contribute: boolean): Hint[] {
	const { catalog, identifier, state } = collection;
	const target = { catalog, collection: identifier };
	const hints: Hint[] = [
		{ title: 'Check out this collection', command: cliCommand({ verb: 'checkout', ...target }) }
	];
	if (!contribute) return hints;
	if (collection.overrideIncompatible) {
		hints.push(
			{
				title: 'Replace the schema override with one that fits',
				command: cliCommand({ verb: 'set override', ...target })
			},
			{
				title: 'Remove the schema override',
				command: cliCommand({ verb: 'unset override', ...target })
			}
		);
	} else if (state === 'incomplete' || collection.hasProblems) {
		hints.push({
			title: 'Complete the metadata, then publish it',
			command: [
				cliCommand({ verb: 'edit meta', ...target }),
				cliCommand({ verb: 'publish meta', ...target })
			].join('\n')
		});
	}
	hints.push(
		state === 'draft'
			? {
					title: 'Activate this draft',
					command: cliCommand({ verb: 'activate collection', ...target })
				}
			: addFilesHint(collection)
	);
	return hints;
}

/**
 * How a contributor adds files to a collection: check it out, stage them, then push. `add` and
 * `push` act on whichever collection is checked out, so the hint checks this one out first;
 * without that, the files would go to the collection checked out last.
 */
export function addFilesHint(collection: { catalog: string; identifier: string }): Hint {
	const { catalog, identifier } = collection;
	return {
		title: 'Add files to this collection',
		command: [
			cliCommand({ verb: 'checkout', catalog, collection: identifier }),
			cliCommand({ verb: 'add', catalog }),
			cliCommand({ verb: 'push', catalog })
		].join('\n')
	};
}

/**
 * A word every shell reads as itself, bare: plain characters only, and no `=` first, which zsh
 * expands to the path of a command (`=ls` becomes `/usr/bin/ls`).
 */
const BARE = /^[A-Za-z0-9_.,:@%+/-][A-Za-z0-9_.,:=@%+/-]*$/;

/**
 * Characters a hint never holds as they are. A terminal or line editor acts on control characters
 * (C0, DEL and C1) in what is pasted into it: Ctrl-U erases the line typed so far, a carriage
 * return runs it, an escape sequence can end a bracketed paste. Format characters, such as a
 * right-to-left override, and the line and paragraph separators change how a line reads without
 * showing themselves. A search's text and labels come from its address, which anyone can write.
 */
const UNSAFE = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;

/** Escapes that read better than the bytes they stand for. */
const NAMED_ESCAPES: ReadonlyMap<string, string> = new Map([
	['\t', '\\t'],
	['\n', '\\n'],
	['\r', '\\r']
]);

/**
 * A value as one shell word: bare when it is plain, single-quoted otherwise. A value holding a
 * character from `UNSAFE` is written as `$'…'` (POSIX.1-2024; bash, zsh and ksh) with that
 * character as escapes in the form bash's `printf %q` uses, so the hint shows and copies visible
 * characters only and the shell still passes the value itself.
 */
export function quote(value: string): string {
	if (BARE.test(value)) return value;
	if (!UNSAFE.test(value)) return `'${value.replaceAll("'", `'\\''`)}'`;
	return `$'${[...value].map(escaped).join('')}'`;
}

/**
 * One code point inside `$'…'`. Bytes are three octal digits, which no digit after them extends.
 * The quote is octal too: a history expansion that does not know `$'…'` would take a `\'` for
 * the end of the quoted text.
 */
function escaped(point: string): string {
	if (point === '\\') return '\\\\';
	if (point === "'") return '\\047';
	if (!UNSAFE.test(point)) return point;
	return (
		NAMED_ESCAPES.get(point) ??
		[...new TextEncoder().encode(point)]
			.map((byte) => `\\${byte.toString(8).padStart(3, '0')}`)
			.join('')
	);
}

function line(catalog: string, verb: string, ...args: string[]): string {
	return ['huron', '--catalog', quote(catalog), verb, ...args].join(' ');
}
