import { describe, expect, it } from 'vitest';
import { expiredLoginPath } from './sign-in-again';

describe('expiredLoginPath', () => {
	it('leads to the login page that says the session ended and returns afterwards', () => {
		expect(expiredLoginPath('/catalogs/heliophysics/namespaces/fields?collections_cursor=c2')).toBe(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics%2Fnamespaces%2Ffields%3Fcollections_cursor%3Dc2'
		);
		expect(expiredLoginPath('/')).toBe('/login?status=expired&returnTo=%2F');
	});
});
