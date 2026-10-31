<script lang="ts">
	import { page } from '$app/state';
	import NoOrganizations from '$design/components/NoOrganizations.svelte';
	import OrganizationCard from '$design/components/OrganizationCard.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const firstPage = $derived(!page.url.searchParams.get('cursor'));
</script>

<svelte:head><title>{pageTitle('All organizations')}</title></svelte:head>

<h1>All organizations</h1>
<p class="mt-2 text-sm text-app-muted">Every organization you can see.</p>
<PageExpiredNotice />
{#if data.organizationList.length > 0}
	<ul class="mt-6 grid list-none gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">
		{#each data.organizationList as organization (organization.id)}
			<li class="grid min-w-0"><OrganizationCard {organization} /></li>
		{/each}
	</ul>
{:else if firstPage}
	<div class="mt-6"><NoOrganizations groups={data.user.groups} /></div>
{:else}
	<p class="mt-6 text-app-muted">No organizations on this page.</p>
{/if}
<Pager label="Organization pages" next={data.nextCursor} />
