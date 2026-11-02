<script lang="ts">
	import { page } from '$app/state';
	import ActivityList from '$design/components/ActivityList.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { activityRows } from '$lib/activity';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const catalog = $derived(data.catalog);
	const rows = $derived(activityRows(data.entries, data.schemas));
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
</script>

<svelte:head><title>{pageTitle('Activity', displayName(catalog))}</title></svelte:head>

<PageExpiredNotice />
<section aria-labelledby="catalog-activity">
	<h2 id="catalog-activity" class="m-0 border-0 p-0 text-base font-semibold">Activity</h2>
	<p class="mt-2 mb-4 text-sm text-app-muted">Changes in this catalog, newest first.</p>
	{#if rows.length > 0}
		<ActivityList label="Catalog activity" catalog={catalog.name} {rows} />
	{:else if data.nextCursor || !firstPage}
		<!-- Entries readers may not see are left out, so a page can be empty and have a next one. -->
		<p class="m-0 text-app-muted">No visible entries on this page.</p>
	{:else}
		<EmptyState title="No activity yet." />
	{/if}
	<Pager label="Activity pages" next={data.nextCursor} />
</section>
