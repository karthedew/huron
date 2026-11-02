import { error } from '@sveltejs/kit';
import { match as isSegment } from '../../../../params/segment';
import { ORGANIZATION_LIMIT, shellOrganization } from '$lib/organizations';
import { schemaView } from '$lib/schema-view';
import { schemaSummary } from '$lib/schemas';
import { requestCookies } from '$lib/server/cookies';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/** A visible registered version, its authored schema and the schema with its parents composed. */
export const load = (async (event) => {
	const requested = event.url.searchParams.get('organization');
	if (requested !== null && !isSegment(requested)) {
		error(400, { message: 'Choose a valid organization.', code: 'INVALID_SEGMENT' });
	}
	const client = api(event);
	const [entry, resolved, organizations] = await guarded(
		event,
		Promise.all([
			client.schema(event.params.id, { exact: true }),
			client.resolvedSchema(event.params.id),
			client.organizations({ limit: ORGANIZATION_LIMIT })
		])
	);
	let owner = organizations.items.find(({ id }) => id === entry.organization_id);
	if (requested !== null) {
		const selected =
			organizations.items.find(({ name }) => name === requested) ??
			(await guarded(event, client.organization(requested)));
		if (selected.id !== entry.organization_id) {
			error(400, { message: 'Choose the organization that published this schema.' });
		}
		owner = selected;
	}
	const parent =
		entry.extends_id === null ? null : await guarded(event, client.schema(entry.extends_id));
	return {
		organization: owner?.name ?? requestCookies(event).rememberedOrganization(),
		schemaOrganization: owner === undefined ? null : shellOrganization(owner),
		entry: schemaSummary(entry),
		parentSchema: parent === null ? null : schemaSummary(parent),
		resolvedSchema: schemaView(resolved),
		authoredSchema: schemaView(entry.document)
	};
}) satisfies PageServerLoad;
