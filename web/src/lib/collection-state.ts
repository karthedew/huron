/** How the web presents a collection's state (`active`, `incomplete`, `draft`). */
export interface StatePresentation {
	label: string;
	tone: 'ok' | 'warn' | 'neutral';
	/** What the state means for the collection; `null` for the normal, active state. */
	explanation: string | null;
}

const PRESENTATIONS: Readonly<Record<string, StatePresentation>> = {
	active: { label: 'Active', tone: 'ok', explanation: null },
	incomplete: {
		label: 'Incomplete',
		tone: 'warn',
		explanation:
			"The catalog's schema now requires fields this collection lacks. Its files are unaffected."
	},
	draft: {
		label: 'Draft',
		tone: 'neutral',
		explanation:
			'Reserved, not yet activated: no directory or files on the share; visible to contributors only.'
	}
};

/** An incomplete collection whose schema override no longer fits the catalog's schema. */
const INCOMPATIBLE_OVERRIDE: StatePresentation = {
	label: 'Incomplete',
	tone: 'warn',
	explanation: "Its schema override no longer fits the catalog's schema. Its files are unaffected."
};

/**
 * The presentation of a state; a state this web does not know shows by its name. An incomplete
 * collection whose schema override no longer fits says so instead: no field is known to be
 * missing then, as its metadata cannot be checked against any schema.
 */
export function statePresentation(
	state: string,
	{ overrideIncompatible = false }: { overrideIncompatible?: boolean } = {}
): StatePresentation {
	if (state === 'incomplete' && overrideIncompatible) return INCOMPATIBLE_OVERRIDE;
	return Object.hasOwn(PRESENTATIONS, state)
		? PRESENTATIONS[state]
		: { label: state, tone: 'neutral', explanation: null };
}

/** The badge a list shows for a state: none for active collections. */
export function listBadge(state: string): StatePresentation | null {
	return state === 'active' ? null : statePresentation(state);
}
