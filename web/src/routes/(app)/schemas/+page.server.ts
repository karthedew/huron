import { error, redirect } from '@sveltejs/kit';
import { ORGANIZATION_LIMIT, shellOrganization, visibleOrganization } from '$lib/organizations';
import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { schemaSummary } from '$lib/schemas';
import { requestCookies } from '$lib/server/cookies';
import { api, guarded } from '$lib/server/guard';
import { match as isSegment } from '../../../params/segment';
import type { PageServerLoad } from './$types';

/** The schema registry at one explicit scope: the platform or a visible organization. */
export const load = (async (event) => {
	const selected = event.url.searchParams.get('organization');
	if (selected !== null && selected !== '' && !isSegment(selected)) {
		error(400, { message: 'Choose a valid organization.', code: 'INVALID_SEGMENT' });
	}
	const client = api(event);
	const organizations = await guarded(event, client.organizations({ limit: ORGANIZATION_LIMIT }));
	const remembered = requestCookies(event).rememberedOrganization();
	if (selected === null) {
		const current = visibleOrganization(remembered, organizations.items);
		redirect(303, `/schemas?organization=${encodeURIComponent(current?.name ?? '')}`);
	}
	const owner = selected === '' ? null : await guarded(event, client.organization(selected));
	const list = await guarded(
		event,
		selected === ''
			? client.platformSchemas({ cursor: cursorParam(event.url), limit: LIST_PAGE_SIZE })
			: client.organizationSchemas(selected, {
					cursor: cursorParam(event.url),
					limit: LIST_PAGE_SIZE
				})
	);
	const choices = organizations.items.map(shellOrganization);
	if (owner !== null && !choices.some(({ id }) => id === owner.id)) {
		choices.push(shellOrganization(owner));
	}
	return {
		organization: owner?.name ?? remembered,
		schemaOrganization: owner === null ? null : shellOrganization(owner),
		organizationChoices: choices,
		moreOrganizations: organizations.next_cursor !== null,
		schemas: list.items.map(schemaSummary),
		nextCursor: list.next_cursor
	};
}) satisfies PageServerLoad;
