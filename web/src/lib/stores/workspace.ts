import type { PolarisBrowseBranch, PolarisCatalog } from '$api/types';

/** Catalog context comes from the authenticated server response and the URL. */
export function selectCatalog(catalogs: PolarisCatalog[], requested: string | null): string {
	return catalogs.find((catalog) => catalog.name === requested)?.name ?? catalogs[0]?.name ?? '';
}

export function browseHref(
	catalog: string,
	namespace: string[] = [],
	table = '',
	organization = ''
): '/browse' | `/browse?${string}` {
	const query = new URLSearchParams();
	if (catalog) query.set('catalog', catalog);
	if (namespace.length) query.set('namespace', JSON.stringify(namespace));
	if (table) query.set('table', table);
	if (organization) query.set('organization', organization);
	return query.size ? `/browse?${query}` : '/browse';
}

/** Keep the authorized selected path visible even when an ancestor cannot be listed. */
export function branchFolders(branch: PolarisBrowseBranch, selected: string[]): string[][] {
	const folders = [...branch.folders];
	if (
		selected.length > branch.namespace.length &&
		branch.namespace.every((level, index) => selected[index] === level)
	) {
		const selectedChild = selected.slice(0, branch.namespace.length + 1);
		if (!folders.some((folder) => JSON.stringify(folder) === JSON.stringify(selectedChild)))
			folders.push(selectedChild);
	}
	return folders;
}
