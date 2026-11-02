<script lang="ts">
	import CliHint from '$design/components/CliHint.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { collectionHints } from '$lib/cli';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const collection = $derived(data.collection);
	const can = $derived(catalogCapabilities(data.roles, data.catalog, data.organizations));
	const hints = $derived(
		collectionHints({ ...collection, hasProblems: data.hasProblems }, can.contribute)
	);
</script>

<svelte:head
	><title>{pageTitle('CLI', collection.title ?? collection.identifier)}</title></svelte:head
>
<section aria-labelledby="collection-cli" class="max-w-3xl">
	<h2 id="collection-cli" class="m-0 mb-4 border-0 p-0 text-base font-semibold">With the CLI</h2>
	<div class="grid gap-4">
		{#each hints as hint (hint.title)}<CliHint title={hint.title} command={hint.command} />{/each}
	</div>
</section>
