<script lang="ts">
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import Card from '$design/components/Card.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>{data.organization.name} · Huron</title></svelte:head>

<Breadcrumbs
	crumbs={[
		{ label: 'Browse', href: '/browse' },
		{ label: data.organization.name, href: `/${data.organization.slug}` }
	]}
/>

<h1>{data.organization.name}</h1>
<p class="muted">{data.organization.description}</p>

<h2>Projects</h2>
{#if data.projects.length === 0}
	<EmptyState
		title="No projects visible"
		detail="Projects you cannot discover do not appear here."
	/>
{:else}
	<ul class="grid">
		{#each data.projects as project}
			<li>
				<Card href="/{data.organization.slug}/{project.slug}">
					<h3>{project.name}</h3>
					<p class="muted">{project.description}</p>
					<p class="count muted">
						{project.datasetCount} dataset{project.datasetCount === 1 ? '' : 's'}
					</p>
				</Card>
			</li>
		{/each}
	</ul>
{/if}

<h2>Members and roles</h2>
<p class="muted">
	Role bindings for this organization — <code>org_admin</code> only. Not built (P1).
</p>

<h2>Science-profile registry</h2>
<p class="muted">
	Published profile versions, immutability notice, install-to-project — org admin only. Not built
	(P5).
</p>

<style>
	.grid {
		list-style: none;
		padding: 0;
		margin: 1rem 0 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
		gap: 0.9rem;
	}
	h3 {
		font-size: 1rem;
		margin: 0 0 0.3rem;
	}
	.count {
		font-size: 0.85rem;
		margin: 0.5rem 0 0;
	}
</style>
