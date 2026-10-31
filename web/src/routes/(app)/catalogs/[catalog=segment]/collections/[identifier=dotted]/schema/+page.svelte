<script lang="ts">
	import { resolve } from '$app/paths';
	import SchemaTable from '$design/components/SchemaTable.svelte';
	import { identifierInCatalog } from '$lib/explorer';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const collection = $derived(data.collection);
	const name = $derived(collection.title ?? collection.identifier);
	const metadataFile = $derived(
		resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata.json', {
			catalog: collection.catalog,
			identifier: identifierInCatalog(collection.identifier)
		})
	);
</script>

<svelte:head><title>{pageTitle('Schema', name)}</title></svelte:head>

<section aria-labelledby="collection-schema">
	<h2 id="collection-schema" class="m-0 border-0 p-0 text-base font-semibold">
		Schema <span class="mono font-semibold"
			>{collection.schema.name} v{collection.schema.version}</span
		>{#if data.override}{' '}with this collection's override{/if}
	</h2>
	{#if data.schema}
		<p class="mt-2 mb-4 max-w-3xl text-sm text-app-muted">
			What this collection's metadata must satisfy: its catalog's schema, with the schemas it
			extends{data.override ? ' and the override below' : ''} folded in.
		</p>
		<SchemaTable label="Fields of the collection's schema" schema={data.schema} />
	{:else}
		<p class="mt-2 mb-0 max-w-3xl text-sm">
			The override below no longer fits the catalog's schema, so there is no composed schema to show
			until the override changes.
		</p>
	{/if}
</section>

{#if data.override}
	<section aria-labelledby="collection-override" class="mt-10">
		<h2 id="collection-override" class="m-0 border-0 p-0 text-base font-semibold">
			Schema override
		</h2>
		<p class="mt-2 mb-4 max-w-3xl text-sm text-app-muted">
			This collection's own additions to its catalog's schema, as set with the CLI.
		</p>
		<SchemaTable label="Fields of the schema override" schema={data.override} />
		{#if data.override.shortened && collection.state !== 'draft'}
			<p class="mt-3 mb-0 text-sm text-app-muted">
				<!-- An endpoint, not a page: the browser loads it itself. -->
				<a href={metadataFile} data-sveltekit-reload class="underline underline-offset-2"
					>metadata.json</a
				> holds the whole override.
			</p>
		{/if}
	</section>
{/if}
