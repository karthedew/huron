import { expect } from '@playwright/test';
import { CLIENT_ID } from './support/fixture.mjs';
import {
	COOKIES,
	SIGN_IN_LINK,
	cancelSignIn,
	chooseUser,
	expectSignInPage,
	logOut,
	openSignIn,
	signIn,
	stack,
	test,
	transactionCookies,
	webCookie
} from './support/harness.ts';

test.describe('without a session', () => {
	test('a page visit signs in first and comes back with its query', async ({ page }) => {
		await page.goto('/orgs/helio?tab=catalogs');
		await expect(page).toHaveURL('/login?returnTo=%2Forgs%2Fhelio%3Ftab%3Dcatalogs');
		await expect(page.getByRole('heading', { name: 'Sign in to Huron', level: 1 })).toBeVisible();
		await expect(page.getByRole('status')).toHaveCount(0);

		await page.getByRole('link', { name: SIGN_IN_LINK }).click();
		await expectSignInPage(page);
		await chooseUser(page, 'erin');
		await expect(page).toHaveURL('/orgs/helio?tab=catalogs');
		await expect(
			page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
		expect(await webCookie(page.context(), COOKIES.session)).toMatchObject({
			httpOnly: true,
			secure: false,
			sameSite: 'Lax',
			path: '/'
		});
		expect(await transactionCookies(page.context())).toEqual([]);
	});

	test('data and tree requests get answers a script can act on', async ({ request }) => {
		const data = await request.get('/__data.json');
		expect(await data.json()).toEqual({ type: 'redirect', location: '/login?returnTo=%2F' });

		const tree = await request.get('/catalogs/heliophysics/tree?parent=solar-wind', {
			headers: { 'x-huron-fetch': '1' }
		});
		expect(tree.status()).toBe(401);
		expect(await tree.json()).toEqual({ code: 'UNAUTHENTICATED' });

		const page = await request.get('/orgs/helio', { maxRedirects: 0 });
		expect(page.status()).toBe(303);
		expect(page.headers()['location']).toBe('/login?returnTo=%2Forgs%2Fhelio');
	});

	test('a session the server no longer knows counts as expired', async ({ page, context }) => {
		await context.addCookies([
			{ name: COOKIES.session, value: 'gone-after-a-restart', url: stack.webOrigin }
		]);
		await page.goto('/?from=bookmark');
		await expect(page).toHaveURL('/login?returnTo=%2F%3Ffrom%3Dbookmark&status=expired');
		await expect(page.getByRole('status')).toHaveText(
			'Your session ended. Sign in again to continue.'
		);
		expect(await webCookie(context, COOKIES.session)).toBeUndefined();
	});
});

test.describe('signing in and out', () => {
	test('logging out ends the session here and at the IdP', async ({ page, context }) => {
		/** The IdP logout requests, to check what the web sends there. */
		const idpLogouts: URL[] = [];
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.origin === stack.issuer && url.pathname === '/logout') idpLogouts.push(url);
		});
		await signIn(page, 'dave');
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Organizations', level: 1 })).toBeVisible();

		await logOut(page);
		await expect(page.getByRole('status')).toHaveText("You've signed out.");
		expect(await webCookie(context, COOKIES.session)).toBeUndefined();
		expect(idpLogouts).toHaveLength(1);
		expect([...idpLogouts[0].searchParams.keys()].sort()).toEqual([
			'client_id',
			'post_logout_redirect_uri'
		]);
		expect(idpLogouts[0].searchParams.get('client_id')).toBe(CLIENT_ID);
		expect(idpLogouts[0].searchParams.get('post_logout_redirect_uri')).toBe(
			`${stack.webOrigin}/login?status=signed-out`
		);

		await page.goto('/');
		await expect(page).toHaveURL('/login?returnTo=%2F');
	});

	test('Cancel at the IdP reports it and Try again keeps the destination', async ({ page }) => {
		await page.goto('/orgs/helio');
		await page.getByRole('link', { name: SIGN_IN_LINK }).click();
		await cancelSignIn(page);
		await expect(page).toHaveURL('/login?error=idp_error&returnTo=%2Forgs%2Fhelio');
		await expect(page.getByRole('alert')).toContainText("The company sign-in didn't complete.");
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();

		await page.getByRole('link', { name: 'Try again' }).click();
		await expectSignInPage(page);
		await chooseUser(page, 'erin');
		await expect(page).toHaveURL('/orgs/helio');
		await expect(
			page.getByRole('heading', { name: 'Heliophysics Division', level: 1 })
		).toBeVisible();
	});

	test('an ID token without the API audience is not accepted', async ({ page }) => {
		await openSignIn(page);
		await chooseUser(page, 'noaud');
		await expect(page).toHaveURL('/login?error=token_rejected');
		await expect(page.getByRole('alert')).toContainText("Huron didn't accept this sign-in.");
		await expect(page.getByRole('link', { name: 'Try again' })).toHaveAttribute(
			'href',
			/\/auth\/login$/
		);
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();
	});

	test('a failing token endpoint reports the IdP as unavailable', async ({ page }) => {
		await openSignIn(page);
		await chooseUser(page, 'idpfail');
		await expect(page).toHaveURL('/login?error=idp_unavailable');
		await expect(page.getByRole('alert')).toContainText(
			"The company sign-in service isn't responding."
		);
		expect(await webCookie(page.context(), COOKIES.session)).toBeUndefined();
	});

	test('two sign-ins interleaved in one browser both complete', async ({ browser, context }) => {
		const first = await context.newPage();
		const second = await context.newPage();
		await openSignIn(first, '/?tab=first');
		await openSignIn(second, '/?tab=second');
		expect(await transactionCookies(context)).toHaveLength(2);

		await chooseUser(second, 'dave');
		await expect(second).toHaveURL('/?tab=second');
		await expect(second.getByRole('link', { name: /^Earth Science/ })).toBeVisible();
		const daveSession = await webCookie(context, COOKIES.session);
		if (daveSession === undefined) throw new Error('the second sign-in set no session cookie');

		await chooseUser(first, 'mallory');
		await expect(first).toHaveURL('/?tab=first');
		await expect(first.getByText("You don't have access to any organization yet.")).toBeVisible();
		expect(await transactionCookies(context)).toEqual([]);

		// One cookie jar: the other tab is now mallory's too, and dave's session is gone.
		await second.reload();
		await expect(second.getByText("You don't have access to any organization yet.")).toBeVisible();
		const replay = await browser.newContext();
		try {
			await replay.addCookies([daveSession]);
			const replayed = await replay.newPage();
			await replayed.goto(`${stack.webOrigin}/`);
			await expect(replayed).toHaveURL(`${stack.webOrigin}/login?returnTo=%2F&status=expired`);
		} finally {
			await replay.close();
		}
	});
});

test.describe('returnTo stays on this origin', () => {
	const offSite = [
		'/..//evil.example',
		'/.//evil.example',
		'/%2e//evil.example',
		'/x/..//evil.com',
		'//evil.example',
		'/\\evil.example',
		'https://evil.example/'
	];

	test('through a full sign-in', async ({ page }) => {
		const leaks: string[] = [];
		page.on('request', (request) => {
			if (new URL(request.url()).hostname.startsWith('evil.')) leaks.push(request.url());
		});
		for (const returnTo of offSite) {
			await page.goto(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
			await expectSignInPage(page);
			await chooseUser(page, 'mallory');
			await expect(page, `returnTo ${returnTo}`).toHaveURL('/');
		}
		expect(leaks).toEqual([]);
	});

	test('when already signed in', async ({ page }) => {
		const leaks: string[] = [];
		page.on('request', (request) => {
			if (new URL(request.url()).hostname.startsWith('evil.')) leaks.push(request.url());
		});
		await signIn(page, 'mallory');
		for (const returnTo of offSite) {
			await page.goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
			await expect(page, `returnTo ${returnTo}`).toHaveURL('/');
		}
		await page.goto('/login?returnTo=%2F%3Fkept%3D1');
		await expect(page).toHaveURL('/?kept=1');
		expect(leaks).toEqual([]);
	});
});
