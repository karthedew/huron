<script lang="ts">
	import { resolve } from '$app/paths';
	import MetadataView from '$design/components/MetadataView.svelte';
	import { identifierInCatalog } from '$lib/explorer';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const collection = $derived(data.collection);
	const metadataFile = $derived(
		resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata.json', {
			catalog: collection.catalog,
			identifier: identifierInCatalog(collection.identifier)
		})
	);
</script>

<svelte:head
	><title>{pageTitle('Metadata', collection.title ?? collection.identifier)}</title></svelte:head
>

<section aria-labelledby="collection-metadata" class="max-w-4xl">
	<div
		class="mb-3 flex flex-wrap items-baseline justify-between gap-2 border-b border-app-line pb-3"
	>
		<h2 id="collection-metadata" class="m-0 border-0 p-0 text-sm font-semibold">Metadata</h2>
		{#if collection.state !== 'draft'}
			<a href={metadataFile} data-sveltekit-reload class="mono text-sm underline underline-offset-2"
				>metadata.json</a
			>
		{/if}
	</div>
	<p class="mt-0 mb-4 text-sm text-app-muted">
		Recorded details about this collection. The Schema tab describes the rules these fields must
		satisfy.
	</p>
	{#if !data.schemaResolved}
		<p class="mt-0 mb-3 text-sm text-app-muted">
			Its schema override no longer fits the catalog's schema, so the fields show by their keys.
		</p>
	{/if}
	<MetadataView catalog={collection.catalog} view={data.metadata} />
	{#if data.metadata.shortened || collection.shortened}
		<p class="mt-4 mb-0 text-sm text-app-muted">
			This metadata is too long to show in full here.
			{#if collection.state !== 'draft'}metadata.json holds all of it.{/if}
		</p>
	{/if}
</section>
