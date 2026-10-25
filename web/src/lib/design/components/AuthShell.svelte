<script lang="ts">
	import { resolve } from '$app/paths';
	import { Database, Layers3, ShieldCheck } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	interface Props {
		eyebrow: string;
		title: string;
		detail: string;
		children: Snippet;
	}

	let { eyebrow, title, detail, children }: Props = $props();
</script>

<div class="grid min-h-dvh bg-app-bg text-app-fg lg:grid-cols-[minmax(360px,0.85fr)_1.15fr]">
	<aside
		class="relative hidden overflow-hidden border-r border-app-line bg-[#062d29] p-10 text-white lg:flex lg:flex-col xl:p-14"
	>
		<div
			class="pointer-events-none absolute -right-24 -top-24 size-80 rounded-full bg-brand/15 blur-3xl"
		></div>
		<div
			class="pointer-events-none absolute -bottom-32 -left-24 size-96 rounded-full bg-[#167a70]/30 blur-3xl"
		></div>

		<a
			href={resolve('/login')}
			class="relative flex w-fit items-center gap-3 text-white no-underline"
		>
			<span
				class="grid size-10 place-items-center rounded-lg bg-brand text-base font-black text-[#062d29]"
				>H</span
			>
			<span class="text-xl font-semibold tracking-[-0.025em]">Huron</span>
			<span
				class="rounded border border-white/15 bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/70"
				>Lakehouse</span
			>
		</a>

		<div class="relative my-auto max-w-lg py-16">
			<p class="text-xs font-semibold uppercase tracking-[0.15em] text-brand">Governed data</p>
			<h2
				class="mt-4 border-0 p-0 text-4xl font-semibold leading-[1.1] tracking-[-0.04em] xl:text-5xl"
			>
				Scientific data, organized with Polaris.
			</h2>
			<p class="mt-5 max-w-md text-base leading-7 text-white/65">
				Browse Icechunk repositories and manage access to your scientific catalogs from one
				workspace.
			</p>

			<ul class="mt-9 grid gap-4 text-sm text-white/80">
				<li class="flex items-center gap-3">
					<span class="grid size-8 place-items-center rounded-md bg-white/10 text-brand"
						><Database size={16} /></span
					>Browse live Icechunk repositories
				</li>
				<li class="flex items-center gap-3">
					<span class="grid size-8 place-items-center rounded-md bg-white/10 text-brand"
						><Layers3 size={16} /></span
					>Explore NASA data examples
				</li>
				<li class="flex items-center gap-3">
					<span class="grid size-8 place-items-center rounded-md bg-white/10 text-brand"
						><ShieldCheck size={16} /></span
					>Control access to each Polaris catalog
				</li>
			</ul>
		</div>

		<p class="relative text-xs text-white/45">Huron beta workspace</p>
	</aside>

	<main class="flex min-h-dvh items-center justify-center px-5 py-10 sm:px-8">
		<div class="w-full max-w-[440px]">
			<a
				href={resolve('/login')}
				class="mb-10 flex w-fit items-center gap-2.5 text-app-fg no-underline lg:hidden"
			>
				<span
					class="grid size-9 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29]"
					>H</span
				>
				<span class="text-lg font-semibold">Huron</span>
			</a>

			<p class="text-xs font-semibold uppercase tracking-[0.14em] text-brand-strong">{eyebrow}</p>
			<h1 class="mt-2 text-[2rem] tracking-[-0.035em]">{title}</h1>
			<p class="mt-2 text-sm leading-6 text-app-muted">{detail}</p>

			<div class="mt-7">{@render children()}</div>
		</div>
	</main>
</div>
