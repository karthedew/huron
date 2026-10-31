<script lang="ts">
	import SchemaTable from '$design/components/SchemaTable.svelte';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const catalog = $derived(data.catalog);
</script>

<svelte:head><title>{pageTitle('Schema', displayName(catalog))}</title></svelte:head>

<section aria-labelledby="catalog-schema">
	<h2 id="catalog-schema" class="m-0 border-0 p-0 text-base font-semibold">
		Schema <span class="mono font-semibold">{catalog.schema.name} v{catalog.schema.version}</span>
	</h2>
	<p class="mt-2 mb-4 max-w-3xl text-sm text-app-muted">
		What the metadata of every collection in this catalog must satisfy, with the schemas it extends
		folded in.
	</p>
	<SchemaTable label="Fields of the catalog's schema" schema={data.schema} />
</section>
