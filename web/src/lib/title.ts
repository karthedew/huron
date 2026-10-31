/** A document title: the page, then its context from narrow to wide, then Huron. */
export function pageTitle(...parts: readonly string[]): string {
	return [...parts.filter((part) => part !== ''), 'Huron'].join(' · ');
}
