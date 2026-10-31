<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** The sign-in content. */
		children: Snippet;
		/** What Huron is for; beside the content on wide screens, below it on narrow ones. */
		aside: Snippet;
	}

	let { children, aside }: Props = $props();
</script>

<div class="grid min-h-dvh bg-app-bg text-app-fg lg:grid-cols-auth">
	<main
		class="flex items-center justify-center px-5 py-10 sm:px-8 lg:col-start-2 lg:row-start-1 lg:min-h-dvh"
	>
		<div class="w-full max-w-auth">
			<p class="mb-10 flex w-fit items-center gap-2.5 text-lg font-semibold lg:hidden">
				<span
					class="grid size-9 place-items-center rounded-md bg-brand text-sm font-black text-brand-ink"
					aria-hidden="true">H</span
				>
				Huron
			</p>
			{@render children()}
		</div>
	</main>

	<aside
		class="relative overflow-hidden border-t border-app-line bg-brand-ink px-5 py-10 text-on-ink sm:px-8 lg:col-start-1 lg:row-start-1 lg:flex lg:flex-col lg:border-t-0 lg:border-r lg:p-10 xl:p-14"
	>
		<div
			class="pointer-events-none absolute -top-24 -right-24 size-80 rounded-full bg-brand/15 blur-3xl"
		></div>
		<p class="relative hidden w-fit items-center gap-3 text-xl font-semibold lg:flex">
			<span
				class="grid size-10 place-items-center rounded-lg bg-brand text-base font-black text-brand-ink"
				aria-hidden="true">H</span
			>
			Huron
		</p>
		<div class="relative mx-auto w-full max-w-auth lg:my-auto lg:mx-0 lg:max-w-lg lg:py-16">
			{@render aside()}
		</div>
	</aside>
</div>
