/** Anything the API names twice: a unique `name` and an optional `display_name`. */
export interface Named {
	name: string;
	display_name: string;
}

/** How an organization or catalog is named on screen: its display name, else its name. */
export function displayName(item: Named): string {
	return item.display_name || item.name;
}

/** The name to show next to the display name, only when the two differ. */
export function secondaryName(item: Named): string | null {
	return item.display_name !== '' && item.display_name !== item.name ? item.name : null;
}
