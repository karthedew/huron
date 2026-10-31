<script lang="ts">
	import { page } from '$app/state';
	import CliHint from '$design/components/CliHint.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import FileTable from '$design/components/FileTable.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { addFilesHint } from '$lib/cli';
	import { countLabel } from '$lib/format';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const collection = $derived(data.collection);
	const name = $derived(collection.title ?? collection.identifier);
	const can = $derived(catalogCapabilities(data.roles, data.catalog, data.organizations));
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
	const hint = $derived(addFilesHint(collection));
</script>

<svelte:head><title>{pageTitle('Files', name)}</title></svelte:head>

<PageExpiredNotice />
<section aria-labelledby="collection-files">
	<h2 id="collection-files" class="m-0 border-0 p-0 text-base font-semibold">Files</h2>
	{#if collection.state === 'draft'}
		<p class="mt-2 mb-0 max-w-3xl text-sm text-app-muted">
			A draft has no directory on the share, so it holds no files yet. Files can be pushed once it
			is activated.
		</p>
	{:else if data.files.length > 0 || data.nextCursor || !firstPage}
		<p class="mt-2 mb-4 text-sm text-app-muted">
			{countLabel(collection.fileCount, 'file')} recorded, sorted by path.
		</p>
		{#if data.files.length > 0}
			<FileTable label="Files of {name}" files={data.files} />
		{:else}
			<p class="m-0 text-app-muted">No files on this page.</p>
		{/if}
		<Pager label="File pages" next={data.nextCursor} />
	{:else}
		<div class="mt-3">
			<EmptyState
				title="No files yet."
				detail="Files appear here once someone pushes them from a working copy."
			>
				{#if can.contribute}
					<div class="mx-auto mt-4 max-w-2xl">
						<CliHint title={hint.title} command={hint.command} />
					</div>
				{/if}
			</EmptyState>
		</div>
	{/if}
</section>
