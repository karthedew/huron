/**
 * What e2e tests use to drive the stack: its addresses, signing in through the fake IdP, fault
 * injection at the proxy and API calls as fixture users. The helpers stick to URLs, roles and
 * accessible names, so restyling a page does not break them.
 */
import {
	test as base,
	expect,
	type BrowserContext,
	type Cookie,
	type Locator,
	type Page
} from '@playwright/test';
import { SIGN_IN_HEADING, type FaultMode } from './fake-idp.mjs';
import type { Username } from './fixture.mjs';
import { huronToken } from './seed.mjs';
import { FAULTS_PROJECT, e2eStack } from './stack.mjs';

/** The running stack; the runner and its workers see the same `HURON_E2E_*` ports. */
export const stack = e2eStack(process.env);

/**
 * The session cookies `signIn` set during the test this worker runs (a worker runs one test at
 * a time), in its own pages and in contexts the test opened and closed itself.
 */
const signedIn = new Set<string>();

/**
 * Playwright's `test`, which ends every web session a test signed in to once the test is over.
 * A user holds at most 10 sessions (the oldest are evicted), and a test's sessions would
 * otherwise live on for the Huron token's 8 hours: then a test that outlives 10 later sign-ins
 * of its user, in other workers or tests, lost its session halfway.
 */
export const test = base.extend<{ endSessions: void }>({
	endSessions: [
		async ({ context, request }, use) => {
			signedIn.clear();
			await use();
			// The default context's session also covers sign-ins made with `chooseUser` alone.
			const current = await webCookie(context, COOKIES.session);
			if (current !== undefined) signedIn.add(current.value);
			for (const value of signedIn) {
				// The logout's own Origin check refuses a POST without the web's origin.
				const answer = await request.post(`${stack.webOrigin}/logout`, {
					headers: { cookie: `${COOKIES.session}=${value}`, origin: stack.webOrigin },
					maxRedirects: 0
				});
				if (answer.status() !== 303) {
					throw new Error(`ending a session answered ${answer.status()}, not 303`);
				}
			}
			signedIn.clear();
		},
		{ auto: true }
	]
});

/** The viewports layouts are checked at. */
export const VIEWPORTS = {
	phone: { width: 390, height: 844 },
	tablet: { width: 816, height: 900 },
	desktop: { width: 1440, height: 900 }
} as const;

/** The web's cookie names on plain http (on https they carry the `__Host-` prefix). */
export const COOKIES = {
	session: 'huron_session',
	organization: 'huron_org',
	transactionPrefix: 'huron_oidc_'
} as const;

export const SIGN_IN_LINK = 'Sign in with your company account';

/**
 * The one user whose API calls tests make fail. Faults follow the user, not the test, so only
 * tests in `e2e/faults/` inject them, and that project runs one test at a time; no other test
 * signs in as oscar.
 */
export const FAULT_USER = 'oscar' satisfies Username;

/** The login page that returns to `returnTo` after sign-in. */
export function loginPath(returnTo = '/'): string {
	return returnTo === '/' ? '/login' : `/login?returnTo=${encodeURIComponent(returnTo)}`;
}

/** From the login page to the fake IdP's sign-in page. */
export async function openSignIn(page: Page, returnTo = '/'): Promise<void> {
	await page.goto(loginPath(returnTo));
	await page.getByRole('link', { name: SIGN_IN_LINK }).click();
	await expectSignInPage(page);
}

/** The fake IdP's sign-in page is showing. */
export async function expectSignInPage(page: Page): Promise<void> {
	await expect(page.getByRole('heading', { name: SIGN_IN_HEADING, level: 1 })).toBeVisible();
}

/** Choose a user on the fake IdP's sign-in page. */
export async function chooseUser(page: Page, username: Username): Promise<void> {
	if (username === FAULT_USER && base.info().project.name !== FAULTS_PROJECT) {
		throw new Error(`${FAULT_USER} signs in only in e2e/faults/, where faults cannot leak`);
	}
	await page.getByRole('button', { name: username, exact: true }).click();
}

/** Cancel on the fake IdP's sign-in page. */
export async function cancelSignIn(page: Page): Promise<void> {
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
}

/**
 * Sign in through the login page and the fake IdP. Resolves once the browser is back on a page
 * of the web; a failed sign-in times out here, so tests of failures use `openSignIn` and
 * `chooseUser` instead. The harness's `test` ends the session once the test is over.
 */
export async function signIn(
	page: Page,
	username: Username,
	{ returnTo = '/' }: { returnTo?: string } = {}
): Promise<void> {
	await openSignIn(page, returnTo);
	await chooseUser(page, username);
	await page.waitForURL(isSignedInPage);
	const session = await webCookie(page.context(), COOKIES.session);
	if (session !== undefined) signedIn.add(session.value);
}

/** Sign out from the shell's account menu; resolves on the signed-out login page. */
export async function logOut(page: Page): Promise<void> {
	await accountMenu(page).summary.click();
	await accountMenu(page).panel.getByRole('button', { name: 'Sign out', exact: true }).click();
	await page.waitForURL(`${stack.webOrigin}/login?status=signed-out`);
}

/** A menu of the shell's banner: its `<summary>` (Playwright gives that no role) and its panel. */
export interface HeaderMenu {
	details: Locator;
	summary: Locator;
	panel: Locator;
}

/** The organization switcher, when the user can choose between organizations. */
export function organizationSwitcher(page: Page): HeaderMenu {
	return headerMenu(page, /^Organization: |^Choose organization$/);
}

/** The account menu, named after the signed-in user. */
export function accountMenu(page: Page): HeaderMenu {
	return headerMenu(page, /^Account: /);
}

function headerMenu(page: Page, name: RegExp): HeaderMenu {
	const details = page
		.getByRole('banner')
		.locator('details')
		.filter({ has: page.locator('summary').getByText(name) });
	return { details, summary: details.locator('summary'), panel: details.locator('summary + div') };
}

/** How far the page scrolls sideways; 0 when everything fits the viewport's width. */
export async function horizontalOverflow(page: Page): Promise<number> {
	return page.evaluate(
		() => document.documentElement.scrollWidth - document.documentElement.clientWidth
	);
}

/** Whether a URL is a page of the web other than the login page and the sign-in endpoints. */
export function isSignedInPage(url: URL): boolean {
	return (
		url.origin === stack.webOrigin &&
		url.pathname !== '/login' &&
		!url.pathname.startsWith('/auth/')
	);
}

/** The web's cookie of that name in a context, if any. */
export async function webCookie(
	context: BrowserContext,
	name: string
): Promise<Cookie | undefined> {
	return (await context.cookies(stack.webOrigin)).find((cookie) => cookie.name === name);
}

/** The sign-in transaction cookies a context still holds. */
export async function transactionCookies(context: BrowserContext): Promise<Cookie[]> {
	return (await context.cookies(stack.webOrigin)).filter(({ name }) =>
		name.startsWith(COOKIES.transactionPrefix)
	);
}

/** Remember an organization the way the browser does after navigating to it. */
export async function rememberOrganization(context: BrowserContext, value: string): Promise<void> {
	await context.addCookies([{ name: COOKIES.organization, value, url: stack.webOrigin }]);
}

/**
 * Make the fault proxy fail every API request whose token names `subject`, or with `path` only
 * those whose path starts with it (`/api/v1/catalogs/heliophysics/search`); `null` clears every
 * fault of the subject, or with `path` that one. `requestId` is the request id an `error500`
 * answer carries.
 */
export async function faults(
	subject: typeof FAULT_USER,
	mode: FaultMode | null,
	{ path }: { path?: string } = {}
): Promise<{ requestId: string | null }> {
	const response = await fetch(`${stack.proxyUrl}/__test/faults`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ subject, mode, path })
	});
	if (!response.ok) {
		throw new Error(`the fault proxy refused ${String(mode)} for ${subject}: ${response.status}`);
	}
	const answer: unknown = await response.json();
	const requestId =
		typeof answer === 'object' &&
		answer !== null &&
		'requestId' in answer &&
		typeof answer.requestId === 'string'
			? answer.requestId
			: null;
	return { requestId };
}

/** An answer of the API itself. */
export interface ApiAnswer {
	status: number;
	body: unknown;
}

/** The API as one fixture user, bypassing the web: what the API itself answers that user. */
export class ApiSession {
	readonly #token: string;

	private constructor(token: string) {
		this.#token = token;
	}

	static async as(username: Username): Promise<ApiSession> {
		return new ApiSession(
			await huronToken({ apiUrl: stack.apiUrl, issuer: stack.issuer }, username)
		);
	}

	/** `GET /api/v1/<path>`. */
	async get(path: string): Promise<ApiAnswer> {
		const response = await fetch(`${stack.apiUrl}/api/v1/${path}`, {
			headers: { accept: 'application/json', authorization: `Bearer ${this.#token}` }
		});
		const text = await response.text();
		const body: unknown = text === '' ? null : JSON.parse(text);
		return { status: response.status, body };
	}
}
