/**
 * The server's part of a search: whether the user may search a catalog's drafts, the exact match
 * a search text names, and the fields an API refusal is about. The catalog search uses them for
 * one catalog; the organization search for each of its catalogs.
 */
import type { Catalog, Organization, RoleGrant } from '$api/types';
import { catalogCapabilities } from '$lib/capabilities';
import { ownValue } from '$lib/json';
import { ORGANIZATION_LIMIT } from '$lib/organizations';
import {
	exactIdentifier,
	passesFilters,
	searchResult,
	type Search,
	type SearchErrors,
	type SearchResult
} from '$lib/search';
import { degrade, settled, type GuardEvent } from './guard';
import { HuronApiError, type HuronApi, type RequestOptions } from './huron-api';

/** What the form says where the API refused a part of a search. */
const REFUSED = {
	q: "The Huron service didn't accept this text.",
	label: "The Huron service didn't accept these label filters.",
	form: "The Huron service didn't accept this search."
} as const;

/** What decides whether a user may search a catalog's drafts: their roles and organizations. */
export interface DraftAccess {
	roles: RoleGrant[];
	/** The organizations the user can see, to tell which one owns a catalog. */
	organizations: Organization[];
}

/**
 * The user's roles and visible organizations, read once per request: they are the reads the
 * shell makes, shared through the request's client. A read that fails counts as none, so drafts
 * stay out; it is logged, and an expired Huron token still ends the session.
 */
export async function draftAccess(event: GuardEvent, client: HuronApi): Promise<DraftAccess> {
	const [whoami, organizations] = await Promise.all([
		settled(client.whoami()),
		settled(client.organizations({ limit: ORGANIZATION_LIMIT }))
	]);
	for (const outcome of [whoami, organizations]) {
		if (!outcome.ok) degrade(event, outcome.failure);
	}
	return {
		roles: whoami.ok ? whoami.value.roles : [],
		organizations: organizations.ok ? organizations.value.items : []
	};
}

/**
 * Whether the user may create collections in a catalog, so a search there includes drafts when
 * asked: the API includes them only then. An organization admin needs the catalog's organization
 * among the visible ones.
 */
export function maySeeDrafts(
	access: DraftAccess,
	catalog: Pick<Catalog, 'id' | 'organization'>
): boolean {
	return catalogCapabilities(access.roles, catalog, access.organizations).contribute;
}

/**
 * The collection a search text names exactly in a catalog (see `exactIdentifier`), on the
 * search's first page only, when it passes the search's state and label filters as any result
 * must: the exact match is the result whose identifier is the text, lifted to the top. The API
 * conceals what the user may not see, drafts included, as not found. A lookup that finds
 * nothing (403, 404, or a path the client refuses to send) shows nothing; an expired Huron token
 * still ends the session; any other failure is logged, and the results show without it. A
 * lookup aborted by its `signal` (a deadline the caller gave up at) shows nothing either, and
 * is no failure.
 */
export async function exactMatch(
	event: GuardEvent,
	client: HuronApi,
	catalog: string,
	search: Search,
	{ signal }: RequestOptions = {}
): Promise<SearchResult | null> {
	if (search.cursor !== null) return null;
	const identifier = exactIdentifier(search.q, catalog);
	if (identifier === null) return null;
	try {
		const found = await client.collectionByIdentifier(catalog, identifier, { signal });
		return passesFilters(found, search) ? searchResult(found) : null;
	} catch (failure) {
		if (signal?.aborted) return null;
		if (!isNothingFound(failure)) degrade(event, failure);
		return null;
	}
}

/**
 * The errors to show for a search the API refused as invalid (422), by the fields its problem
 * names: the text, the labels, or else the search as a whole. Only fixed copy shows; the API's
 * own words never do. `null` for any other failure.
 */
export function refusedSearch(failure: unknown): SearchErrors | null {
	if (!(failure instanceof HuronApiError) || failure.status !== 422) return null;
	const fields = refusedFields(failure.context);
	const named = fields.has('q') || fields.has('label');
	return {
		q: fields.has('q') ? REFUSED.q : null,
		label: fields.has('label') ? REFUSED.label : null,
		form: named && !fields.has('other') ? null : REFUSED.form
	};
}

function isNothingFound(failure: unknown): boolean {
	if (!(failure instanceof HuronApiError)) return false;
	const { status, code } = failure;
	return status === 403 || status === 404 || (status === 400 && code === 'INVALID_SEGMENT');
}

/**
 * The fields of a search a refusal is about: the request validation's problem paths
 * (`/query/q`, `/query/label/0`, …), or the `label` its own label check names.
 */
function refusedFields(context: Readonly<Record<string, unknown>>): Set<'q' | 'label' | 'other'> {
	const fields = new Set<'q' | 'label' | 'other'>();
	if (Object.hasOwn(context, 'label')) fields.add('label');
	const problems = ownValue(context, 'problems');
	const list: readonly unknown[] = Array.isArray(problems) ? problems : [];
	for (const problem of list) {
		const path =
			typeof problem === 'object' && problem !== null && 'path' in problem ? problem.path : null;
		if (path === '/query/q') fields.add('q');
		else if (typeof path === 'string' && path.startsWith('/query/label')) fields.add('label');
		else fields.add('other');
	}
	return fields;
}
