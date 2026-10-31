/**
 * Chips: short values drawn as pills, in one shape. Text chips are plain; a chip that searches is
 * drawn as a link with an icon, so the cue never depends on color alone, and so are those that
 * remove a filter or show one the search already has.
 *
 * Their corners are rounded by more than half a line's height, which reads as a pill on one
 * line, but not fully: a long value wraps onto several, and a fully rounded box would be an
 * ellipse whose border crosses the ends of its first and last lines.
 */
const CHIP = 'max-w-full rounded-xl border px-2 py-0.5 text-xs wrap-anywhere';

/** A chip of text. */
export const PLAIN_CHIP = [CHIP, 'inline-block border-app-line bg-app-code text-app-fg'];

/** A chip that searches for its value. */
export const SEARCH_CHIP = [
	CHIP,
	'inline-flex items-center gap-1 border-app-line-strong bg-app-card font-semibold text-brand-strong no-underline hover:underline'
];

/** A chip for a filter the search already has. */
export const ACTIVE_CHIP = [
	CHIP,
	'inline-flex items-center gap-1 border-brand-strong bg-brand-soft font-semibold text-app-fg'
];

/** A chip that removes a filter from the search. */
export const REMOVE_CHIP = [
	CHIP,
	'inline-flex items-center gap-1 border-app-line-strong bg-app-code font-semibold text-app-fg no-underline hover:border-brand-strong hover:underline'
];

/** What a list of chips says after its first ones. */
export const CHIPS_MORE = 'self-center text-xs text-app-muted';
