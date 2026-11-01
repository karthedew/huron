<script lang="ts">
	import CliHint from '$design/components/CliHint.svelte';
	import { capabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const organization = $derived(data.organizationDetails);
	const can = $derived(capabilities(data.roles, { organizationId: organization.id }));
</script>

<svelte:head><title>{pageTitle('CLI', displayName(organization))}</title></svelte:head>
<section aria-labelledby="organization-cli" class="max-w-3xl">
	<h2 id="organization-cli" class="m-0 mb-4 border-0 p-0 text-base font-semibold">With the CLI</h2>
	<div class="grid gap-4">
		{#if can.administerOrganization}
			<CliHint
				title="Create a catalog in this organization"
				command={cliCommand({ verb: 'create catalog', organization: organization.name })}
			/>
			{#if !organization.declared}<CliHint
					title="Grant a role on the organization"
					command={cliCommand({ verb: 'adm grant', organization: organization.name })}
				/>{/if}
		{:else}
			<p class="m-0 text-sm text-app-muted">
				Open a catalog or collection for its CLI commands. Organization changes require an
				organization administrator.
			</p>
		{/if}
		{#if organization.declared}<p class="m-0 text-sm text-app-muted">
				Organization role groups are declared in the service configuration. An operator changes them
				there.
			</p>{/if}
	</div>
</section>
