<script lang="ts">
	import CliHint from '$design/components/CliHint.svelte';
	import NamespaceHint from '$design/components/NamespaceHint.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const catalog = $derived(data.catalog);
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
	const grantCommand = $derived(
		[
			cliCommand({ verb: 'adm grant', catalog: catalog.name }),
			cliCommand({ verb: 'adm apply-acl', catalog: catalog.name })
		].join('\n')
	);
</script>

<svelte:head><title>{pageTitle('CLI', displayName(catalog))}</title></svelte:head>
<section aria-labelledby="catalog-cli" class="max-w-3xl">
	<h2 id="catalog-cli" class="m-0 mb-4 border-0 p-0 text-base font-semibold">With the CLI</h2>
	<div class="grid gap-4">
		<CliHint
			title="Search this catalog"
			command={cliCommand({ verb: 'search', catalog: catalog.name })}
		/>
		{#if can.administerCatalog}
			<NamespaceHint catalog={catalog.name} parent={catalog.name} />
			<CliHint title="Grant a role, then apply the directory ACLs" command={grantCommand} />
		{/if}
	</div>
</section>
