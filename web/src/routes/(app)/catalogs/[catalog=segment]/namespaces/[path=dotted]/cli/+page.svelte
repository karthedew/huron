<script lang="ts">
	import CliHint from '$design/components/CliHint.svelte';
	import NamespaceHint from '$design/components/NamespaceHint.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const namespace = $derived(data.namespace);
	const catalog = $derived(data.catalog);
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
</script>

<svelte:head><title>{pageTitle('CLI', namespace.identifier)}</title></svelte:head>
<section aria-labelledby="namespace-cli" class="max-w-3xl">
	<h2 id="namespace-cli" class="m-0 mb-4 border-0 p-0 text-base font-semibold">With the CLI</h2>
	<div class="grid gap-4">
		{#if can.contribute && namespace.collections_allowed}
			<CliHint
				title="Create a collection here"
				command={cliCommand({
					verb: 'create collection',
					catalog: catalog.name,
					namespace: namespace.identifier
				})}
			/>
		{:else if can.administerCatalog && !namespace.collections_allowed}
			<NamespaceHint catalog={catalog.name} parent={namespace.identifier} />
		{:else}
			<p class="m-0 text-sm text-app-muted">
				Open a collection to find its checkout command. Changes in this namespace require a
				contributor or catalog administrator.
			</p>
		{/if}
	</div>
</section>
