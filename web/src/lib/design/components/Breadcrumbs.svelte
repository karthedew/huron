<script lang="ts">
	interface Crumb {
		label: string;
		href: string;
	}
	interface Props {
		crumbs: Crumb[];
	}
	let { crumbs }: Props = $props();
</script>

<nav aria-label="Breadcrumb" class="crumbs">
	<ol>
		{#each crumbs as crumb, i}
			<li>
				{#if i === crumbs.length - 1}
					<span aria-current="page">{crumb.label}</span>
				{:else}
					<a href={crumb.href}>{crumb.label}</a>
					<span class="sep" aria-hidden="true">/</span>
				{/if}
			</li>
		{/each}
	</ol>
</nav>

<style>
	.crumbs ol {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		list-style: none;
		margin: 0 0 0.4rem;
		padding: 0;
		font-size: 0.85rem;
		color: var(--muted);
	}
	.crumbs li {
		display: flex;
		gap: 0.3rem;
	}
	.sep {
		color: var(--line);
	}
	a {
		color: var(--muted);
		text-decoration: none;
	}
	a:hover {
		color: var(--accent);
	}
</style>
