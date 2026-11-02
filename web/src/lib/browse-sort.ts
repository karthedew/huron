/** Columns supported by the API's globally sorted browse lists. */
export type BrowseColumn = 'name' | 'created_by' | 'created_at';

/** The order of every page in one browse list. */
export interface BrowseSort {
	sort: BrowseColumn;
	order: 'asc' | 'desc';
}

/** Read one list's sort from its URL; unknown values use the default name order. */
export function readBrowseSort(url: URL, prefix = ''): BrowseSort {
	const sort = url.searchParams.get(parameter(prefix, 'sort'));
	const order = url.searchParams.get(parameter(prefix, 'order'));
	return {
		sort: sort === 'created_by' || sort === 'created_at' ? sort : 'name',
		order: order === 'desc' ? 'desc' : 'asc'
	};
}

/** Change one column's order and restart only that list, preserving the other list's page. */
export function browseSortHref(url: URL, column: BrowseColumn, prefix = ''): string {
	const current = readBrowseSort(url, prefix);
	const target = new URL(url);
	target.searchParams.set(parameter(prefix, 'sort'), column);
	target.searchParams.set(
		parameter(prefix, 'order'),
		current.sort === column && current.order === 'asc' ? 'desc' : 'asc'
	);
	target.searchParams.delete(parameter(prefix, 'cursor'));
	target.searchParams.delete('notice');
	return target.pathname + target.search;
}

function parameter(prefix: string, name: string): string {
	return prefix === '' ? name : `${prefix}_${name}`;
}
