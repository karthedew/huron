<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { CircleAlert, Lock, SearchX, ServerOff } from '@lucide/svelte';
	import { errorCopy } from '$lib/error-copy';
	import { displayName } from '$lib/names';
	import { homeOrganization } from '$lib/organizations';
	import { shellOrganization } from '$lib/shell';
	import { pageTitle } from '$lib/title';

	const copy = $derived(errorCopy(page.status, page.error?.code));
	const Icon = $derived(
		page.status === 404
			? SearchX
			: page.status === 403
				? Lock
				: page.status === 503
					? ServerOff
					: CircleAlert
	);
	/**
	 * The failed page's data is gone; the shell still knows the organization the user was in, and
	 * below a catalog its layout names the catalog's.
	 */
	const current = shellOrganization();
	const home = $derived(homeOrganization(current(), page.data.organizations ?? []));
</script>

<svelte:head><title>{pageTitle(copy.title)}</title></svelte:head>

<section class="max-w-2xl">
	<span
		class="mb-4 grid size-10 place-items-center rounded-full bg-app-code text-app-muted"
		aria-hidden="true"><Icon size={20} /></span
	>
	<h1>{copy.heading}</h1>
	{#if copy.detail}<p class="mt-2 mb-0 text-app-muted">{copy.detail}</p>{/if}
	{#if page.error?.id}
		<p class="mt-2 mb-0 text-sm text-app-muted">
			Reference <code class="break-all">{page.error.id}</code>
		</p>
	{/if}
	<p class="mt-5 mb-0 flex flex-wrap gap-x-5 gap-y-2 text-sm font-semibold">
		{#if copy.retry}
			<a href={page.url.pathname + page.url.search} data-sveltekit-reload>Try again</a>
		{/if}
		{#if home}
			<a class="wrap-anywhere" href={resolve('/(app)/orgs/[org=segment]', { org: home.name })}
				>Back to {displayName(home)}</a
			>
		{:else}
			<a href={resolve('/')}>Back to Huron</a>
		{/if}
	</p>
</section>
