<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { errorCopy } from '$lib/error-copy';
	import { pageTitle } from '$lib/title';

	const copy = $derived(errorCopy(page.status, page.error?.code));
</script>

<svelte:head><title>{pageTitle(copy.title)}</title></svelte:head>

<main class="grid min-h-dvh place-items-center bg-app-bg px-4 py-10 text-app-fg">
	<div class="w-full max-w-md rounded-card border border-app-line bg-app-card p-6">
		<p class="flex items-center gap-2.5 font-semibold">
			<span
				class="grid size-8 place-items-center rounded-md bg-brand text-sm font-black text-brand-ink"
				aria-hidden="true">H</span
			>
			Huron
		</p>
		<h1 class="mt-5 text-xl">{copy.heading}</h1>
		{#if copy.detail}<p class="mt-2 text-app-muted">{copy.detail}</p>{/if}
		{#if page.error?.id}
			<p class="mt-2 text-sm text-app-muted">
				Reference <code class="break-all">{page.error.id}</code>
			</p>
		{/if}
		<p class="mt-5 flex flex-wrap gap-4 text-sm font-semibold">
			{#if copy.retry}<a href={page.url.pathname + page.url.search} data-sveltekit-reload
					>Try again</a
				>{/if}
			<a href={resolve('/')}>Back to Huron</a>
		</p>
	</div>
</main>
