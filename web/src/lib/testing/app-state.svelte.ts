import type { NavigationTarget } from '@sveltejs/kit';

/**
 * A reactive stand-in for `$app/state`, for components that react to navigation:
 * `vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'))`, then change these
 * objects in the test.
 */
export const page = $state<{
	data: App.PageData;
	route: { id: string | null };
	url: URL;
	params: Record<string, string>;
	error: App.Error | null;
	status: number;
}>({
	data: {},
	route: { id: '/(app)' },
	url: new URL('http://localhost:4173/'),
	params: {},
	error: null,
	status: 200
});

export const navigating = $state<{ to: NavigationTarget | null }>({ to: null });

/** Back to the start page, with no navigation in progress. */
export function resetAppState(): void {
	page.data = {};
	page.route = { id: '/(app)' };
	page.url = new URL('http://localhost:4173/');
	page.params = {};
	page.error = null;
	page.status = 200;
	navigating.to = null;
}
