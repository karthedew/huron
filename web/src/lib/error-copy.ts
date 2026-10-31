export interface ErrorCopy {
	/** The short name in the document title. */
	title: string;
	heading: string;
	detail: string | null;
	/** Whether trying the same page again may help. */
	retry: boolean;
}

/**
 * The `code` of a 404 for a collection linked by its id (from activity), which may have been
 * deleted since: its copy says so.
 */
export const LINKED_COLLECTION_GONE = 'LINKED_COLLECTION_GONE';

/**
 * Fixed copy for an error status, and for the few codes this web gives its own errors; the
 * API's own words are never shown.
 */
export function errorCopy(status: number, code?: string): ErrorCopy {
	switch (status) {
		case 400:
			return {
				title: 'Invalid request',
				heading: 'That request is not valid.',
				detail: null,
				retry: false
			};
		case 403:
			return {
				title: 'No permission',
				heading: "You don't have permission to see this.",
				detail: null,
				retry: false
			};
		case 404:
			return {
				title: 'Not found',
				heading:
					code === LINKED_COLLECTION_GONE
						? 'Not found, deleted, or you do not have access.'
						: "Not found, or you don't have access.",
				detail:
					'Groups are read when you sign in; if you were just given access, sign out and sign in again.',
				retry: false
			};
		case 503:
			return {
				title: 'Service unavailable',
				heading: "The Huron service isn't responding.",
				detail: null,
				retry: true
			};
		default:
			return {
				title: 'Error',
				heading: 'Something went wrong.',
				detail: null,
				retry: status >= 500
			};
	}
}
