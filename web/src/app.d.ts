declare global {
	namespace App {
		// interface Error {}
		interface Locals {
			user: import('$api/types').HuronUser | null;
			polaris: import('$lib/server/polaris-client').PolarisClient | null;
		}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
