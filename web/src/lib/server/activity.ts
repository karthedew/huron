import type { AuditEntry } from '$api/types';
import { activitySchemaIds, type SchemaName } from '../activity';
import { degrade, settled, type GuardEvent } from './guard';
import { HuronApiError, type HuronApi } from './huron-api';

/**
 * The names of the schemas a page of audit entries refers to, looked up once each and in
 * parallel. A schema the user may not see, or a failed lookup, stays unnamed: the entry then
 * shows the schema's short id. Failures other than those two are logged, and an expired token
 * still ends the session.
 */
export async function schemaNames(
	event: GuardEvent,
	client: HuronApi,
	entries: readonly AuditEntry[]
): Promise<Record<string, SchemaName>> {
	const ids = activitySchemaIds(entries);
	const outcomes = await Promise.all(ids.map((id) => settled(client.schema(id))));
	const names: Record<string, SchemaName> = {};
	for (const [index, outcome] of outcomes.entries()) {
		if (outcome.ok) {
			names[ids[index]] = { name: outcome.value.name, version: outcome.value.version };
		} else if (!isHidden(outcome.failure)) {
			degrade(event, outcome.failure);
		}
	}
	return names;
}

function isHidden(failure: unknown): boolean {
	return failure instanceof HuronApiError && (failure.status === 403 || failure.status === 404);
}
