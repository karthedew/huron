<script lang="ts">
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import DataTable from '$design/components/DataTable.svelte';
	import Badge from '$design/components/Badge.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	const s = $derived(data.slugs);
	const releaseBase = $derived(`/${s.org}/${s.project}/${s.dataset}/${s.release}`);
	const kib = (b: number) => (b / 1024).toFixed(1);
</script>

<svelte:head><title>{s.release} rev {data.revision.number} · Huron</title></svelte:head>

<Breadcrumbs
	crumbs={[
		{ label: 'Browse', href: '/browse' },
		{ label: s.org, href: `/${s.org}` },
		{ label: s.project, href: `/${s.org}/${s.project}` },
		{ label: s.dataset, href: `/${s.org}/${s.project}/${s.dataset}` },
		{ label: s.release, href: releaseBase },
		{ label: `rev ${data.revision.number}`, href: `${releaseBase}/${data.revision.number}` }
	]}
/>

<h1>Revision {data.revision.number}</h1>
<p class="muted">{data.revision.reason}</p>

<h2>Manifest</h2>
<!-- Virtualization for 10k-file manifests is UI-β; this renders the honest small case. -->
<DataTable caption="Every file with its checksum, retention category, and expiry.">
	{#snippet head()}
		<tr><th>Path</th><th>Size</th><th>Checksum</th><th>Retention</th><th>Expires</th></tr>
	{/snippet}
	{#each data.manifest as entry}
		<tr>
			<td class="mono">{entry.path}</td>
			<td class="mono">{kib(entry.bytes)} KiB</td>
			<td class="mono checksum" title={entry.checksum}>{entry.checksum.slice(0, 19)}…</td>
			<td>{entry.retentionCategory}</td>
			<td>
				{#if entry.expiresAt}
					<span class="mono">{entry.expiresAt.slice(0, 10)}</span>
				{:else}
					<Badge tone="ok">retained</Badge>
				{/if}
			</td>
		</tr>
	{/each}
</DataTable>

<h2>Extracted parameters</h2>
<p class="muted">Profile-driven extraction. Not built (P6).</p>

<h2>Effective metadata</h2>
<p class="muted">Amendment history folded into effective values. Not built (P5).</p>

<style>
	.checksum {
		white-space: nowrap;
	}
</style>
