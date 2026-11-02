<script lang="ts">
	import NoOrganizations from '$design/components/NoOrganizations.svelte';
	import OrganizationCard from '$design/components/OrganizationCard.svelte';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>{pageTitle('Organizations')}</title></svelte:head>

<h1>Organizations</h1>
{#if data.organizationList.length === 0}
	<div class="mt-6"><NoOrganizations groups={data.user.groups} /></div>
{:else}
	<p class="mt-2 text-sm text-app-muted">Choose the organization to open.</p>
	<ul class="mt-6 grid list-none gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">
		{#each data.organizationList as organization (organization.id)}
			<li class="grid min-w-0"><OrganizationCard {organization} /></li>
		{/each}
	</ul>
{/if}
