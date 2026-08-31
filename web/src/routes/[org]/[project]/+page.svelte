<script lang="ts">
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import Card from '$design/components/Card.svelte';
	import LayerBadges from '$design/components/LayerBadges.svelte';
	import LifecycleChip from '$design/components/LifecycleChip.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const gib = (bytes: number) => (bytes / 1_073_741_824).toFixed(1);
	const pct = (used: number, limit: number) => Math.min(100, (used / limit) * 100);
</script>

<svelte:head><title>{data.project.name} · Huron</title></svelte:head>

<Breadcrumbs
	crumbs={[
		{ label: 'Browse', href: '/browse' },
		{ label: data.project.orgSlug, href: `/${data.project.orgSlug}` },
		{ label: data.project.name, href: `/${data.project.orgSlug}/${data.project.slug}` }
	]}
/>

<h1>{data.project.name}</h1>
<p class="muted">{data.project.description}</p>

<h2>Storage</h2>
<!-- Raw on NFS and derived layers on object storage are separate budgets; never summed. -->
<div class="quotas">
	<div class="quota">
		<div class="quota-head">
			<span>Raw <span class="muted">(NFS)</span></span>
			<span class="muted"
				>{gib(data.project.quota.rawUsed)} / {gib(data.project.quota.rawLimit)} GiB</span
			>
		</div>
		<div class="bar">
			<div
				class="fill"
				style="width: {pct(data.project.quota.rawUsed, data.project.quota.rawLimit)}%"
			></div>
		</div>
	</div>
	<div class="quota">
		<div class="quota-head">
			<span>Derived layers <span class="muted">(object storage)</span></span>
			<span class="muted"
				>{gib(data.project.quota.objectUsed)} / {gib(data.project.quota.objectLimit)} GiB</span
			>
		</div>
		<div class="bar">
			<div
				class="fill"
				style="width: {pct(data.project.quota.objectUsed, data.project.quota.objectLimit)}%"
			></div>
		</div>
	</div>
</div>

<h2>Datasets</h2>
{#if data.datasets.length === 0}
	<EmptyState title="No datasets" detail="This project has no datasets you can see." />
{:else}
	<ul class="grid">
		{#each data.datasets as dataset}
			<li>
				<Card href="/{data.project.orgSlug}/{data.project.slug}/{dataset.slug}">
					<div class="head">
						<h3>{dataset.name}</h3>
						<LifecycleChip state={dataset.lifecycle} />
					</div>
					<p class="muted">{dataset.description}</p>
					<LayerBadges layers={dataset.layers} />
				</Card>
			</li>
		{/each}
	</ul>
{/if}

<h2>Retention policy</h2>
<p class="muted">Per-category TTL with its consequence text. Not built (P5).</p>

<h2>Pending steward actions</h2>
<p class="muted">Draft activations and publication approvals as a work queue. Not built (P5).</p>

<style>
	.quotas {
		display: grid;
		gap: 0.9rem;
		margin: 1rem 0;
	}
	.quota-head {
		display: flex;
		justify-content: space-between;
		font-size: 0.88rem;
		margin-bottom: 0.3rem;
	}
	.bar {
		height: 8px;
		background: var(--code-bg);
		border-radius: var(--radius-pill);
		overflow: hidden;
	}
	.fill {
		height: 100%;
		background: var(--accent);
	}
	.grid {
		list-style: none;
		padding: 0;
		margin: 1rem 0 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
		gap: 0.9rem;
	}
	.head {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
		flex-wrap: wrap;
	}
	h3 {
		font-size: 1rem;
		margin: 0 0 0.3rem;
	}
</style>
