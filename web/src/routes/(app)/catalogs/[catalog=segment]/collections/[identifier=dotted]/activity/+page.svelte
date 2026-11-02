<script lang="ts">
	import { page } from '$app/state';
	import ActivityList from '$design/components/ActivityList.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { activityRows } from '$lib/activity';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const collection = $derived(data.collection);
	const name = $derived(collection.title ?? collection.identifier);
	// Every entry is about this collection: none needs a link back to it.
	const rows = $derived(
		activityRows(data.entries, data.schemas).map((row) => ({ ...row, target: null }))
	);
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
</script>

<svelte:head><title>{pageTitle('Activity', name)}</title></svelte:head>

<PageExpiredNotice />
<section aria-labelledby="collection-activity">
	<h2 id="collection-activity" class="m-0 border-0 p-0 text-base font-semibold">Activity</h2>
	<p class="mt-2 mb-4 text-sm text-app-muted">Changes to this collection, newest first.</p>
	{#if rows.length > 0}
		<ActivityList label="Collection activity" catalog={collection.catalog} {rows} />
	{:else if data.nextCursor || !firstPage}
		<p class="m-0 text-app-muted">No visible entries on this page.</p>
	{:else}
		<EmptyState title="No activity yet." />
	{/if}
	<Pager label="Activity pages" next={data.nextCursor} />
</section>
