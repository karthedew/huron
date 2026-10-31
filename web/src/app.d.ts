declare global {
	interface JSON {
		/**
		 * Text `JSON.stringify` writes as it is, such as an integer's own digits. It comes with the
		 * reviver's `context.source` (the JSON.parse source text access proposal), which Node
		 * implements; TypeScript's lib does not declare either yet.
		 */
		rawJSON(text: string): { readonly rawJSON: string };
	}
	namespace App {
		interface Error {
			message: string;
			/** A reference for the logs: the web's error id, or the API's request id. */
			id?: string;
			code?: string;
		}
		interface Locals {
			/** Plain data about the signed-in user; credentials never live here. */
			user: import('$lib/server/sessions').SessionUser | null;
		}
		interface PageData {
			/** The organization the shell shows as current: a name, or `null` off organization pages. */
			organization?: string | null;
			/** The organizations the user can see; the `(app)` layout returns them for every page. */
			organizations?: import('$lib/organizations').ShellOrganization[];
			/** Explorer levels on the way to a namespace or collection page, below the root. */
			trail?: import('$lib/explorer').TrailLevel[];
			/** The catalog of a catalog's page, which the shell's search box searches. */
			catalog?: import('$api/types').Catalog;
			/** The search a search page shows; the shell's search box holds its text. */
			search?: import('$lib/search').Search;
		}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
