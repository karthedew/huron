<script lang="ts">
	import type { Watermark } from '$api/types';

	interface Props {
		watermark: Watermark;
	}
	let { watermark }: Props = $props();
</script>

<!--
	Honest staleness (design/frontend.html §1): every search view states how far the
	projection is behind. When the projection is down, /search returns 503 and the UI
	says so plainly rather than silently falling back to structural browse.
-->
{#if watermark.state === 'unavailable'}
	<p class="mark down" role="status">
		Search index unavailable — structural <a href="/browse">browse</a> still works.
	</p>
{:else}
	<p class="mark" role="status">
		Index {watermark.lagSeconds}s behind
		<span class="muted">· projection healthy</span>
	</p>
{/if}

<style>
	.mark {
		font-size: 0.82rem;
		color: var(--muted);
		margin: 0.2rem 0 1rem;
	}
	.down {
		color: var(--del);
		font-weight: 600;
	}
</style>
