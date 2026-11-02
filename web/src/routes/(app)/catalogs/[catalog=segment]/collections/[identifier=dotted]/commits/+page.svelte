<script lang="ts">
	import { page } from '$app/state';
	import CommitList from '$design/components/CommitList.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const collection = $derived(data.collection);
	const name = $derived(collection.title ?? collection.identifier);
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
</script>

<svelte:head><title>{pageTitle('Commits', name)}</title></svelte:head>

<PageExpiredNotice />
<section aria-labelledby="collection-commits">
	<h2 id="collection-commits" class="m-0 border-0 p-0 text-base font-semibold">Commits</h2>
	{#if collection.state === 'draft'}
		<p class="mt-2 mb-0 max-w-3xl text-sm text-app-muted">
			A draft has no directory on the share, so nothing has been committed to it yet. Files can be
			pushed once it is activated.
		</p>
	{:else}
		<p class="mt-2 mb-4 text-sm text-app-muted">
			Each push records one commit, newest first. Revisions count changes to the collection's
			record, not versions of its data.
		</p>
		{#if data.commits.length > 0}
			<CommitList label="Commits of {name}" commits={data.commits} />
		{:else if data.nextCursor || !firstPage}
			<p class="m-0 text-app-muted">No commits on this page.</p>
		{:else}
			<EmptyState title="No commits yet." detail="A push from a working copy records the first." />
		{/if}
		<Pager label="Commit pages" next={data.nextCursor} />
	{/if}
</section>
