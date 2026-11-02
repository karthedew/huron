import type { Namespace } from '$api/types';
import { countLabel } from './format';

/** What kind of namespace it is: one that holds collections, or one only for structure. */
export function namespaceKind(namespace: Namespace): { label: string; tone: 'accent' | 'neutral' } {
	return namespace.collections_allowed
		? { label: 'Holds collections', tone: 'accent' }
		: { label: 'Structure only', tone: 'neutral' };
}

/**
 * What a namespace holds, as the user sees it: `2 namespaces · 3 collections`. A structure-only
 * namespace never holds collections, so only its namespaces count; a namespace for collections
 * names its namespaces only when it has some.
 */
export function namespaceContents(namespace: Namespace): string {
	const parts: string[] = [];
	if (namespace.namespace_count > 0 || !namespace.collections_allowed) {
		parts.push(countLabel(namespace.namespace_count, 'namespace'));
	}
	if (namespace.collections_allowed || namespace.collection_count > 0) {
		parts.push(countLabel(namespace.collection_count, 'collection'));
	}
	return parts.join(' · ');
}
