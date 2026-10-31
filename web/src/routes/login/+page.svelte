<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		ArrowRight,
		CircleAlert,
		CircleCheck,
		Clock,
		FolderTree,
		Search,
		Terminal,
		Users
	} from '@lucide/svelte';
	import AuthShell from '$design/components/AuthShell.svelte';
	import type { PageData, PageProps } from './$types';

	let { data }: PageProps = $props();

	// An ended session is no success: it gets a clock, not the check of a completed sign-out.
	const STATUS_COPY: Record<
		NonNullable<PageData['status']>,
		{ text: string; icon: typeof CircleCheck; tone: string }
	> = {
		'signed-out': { text: "You've signed out.", icon: CircleCheck, tone: 'text-app-success' },
		expired: {
			text: 'Your session ended. Sign in again to continue.',
			icon: Clock,
			tone: 'text-brand-strong'
		}
	};
	const ERROR_COPY: Record<NonNullable<PageData['error']>, string> = {
		state_mismatch: 'That sign-in expired or was already used.',
		idp_error: "The company sign-in didn't complete.",
		idp_unavailable: "The company sign-in service isn't responding.",
		token_rejected: "Huron didn't accept this sign-in.",
		groups_unavailable: "Huron couldn't read your groups.",
		service_unavailable: "The Huron service isn't responding.",
		config: "Sign-in isn't set up correctly. Contact your Huron administrator."
	};
	const FEATURES = [
		{ icon: FolderTree, text: 'Browse catalogs, namespaces and collections' },
		{ icon: Search, text: 'Search metadata across your organization' },
		{ icon: Users, text: 'See who can read each catalog' },
		{ icon: Terminal, text: 'Read-only — use the huron CLI to create collections and push files.' }
	];

	const signInHref = $derived(
		data.returnTo === '/'
			? resolve('/auth/login')
			: resolve(`/auth/login?returnTo=${encodeURIComponent(data.returnTo)}`)
	);
</script>

<svelte:head><title>Sign in · Huron</title></svelte:head>

<AuthShell>
	<h1>Sign in to Huron</h1>
	<p class="mt-2 text-sm leading-6 text-app-muted">
		The catalog of raw scientific data on the Huron share.
	</p>

	{#if data.error}
		<div
			role="alert"
			class="mt-6 flex items-start gap-2.5 rounded-md border border-app-danger/35 bg-app-danger/10 px-3.5 py-3 text-sm"
		>
			<CircleAlert size={17} class="mt-0.5 shrink-0 text-app-danger" aria-hidden="true" />
			<p>
				{ERROR_COPY[data.error]}
				<a
					href={signInHref}
					data-sveltekit-reload
					class="font-semibold text-app-fg underline underline-offset-2">Try again</a
				>
			</p>
		</div>
	{:else if data.status}
		{@const status = STATUS_COPY[data.status]}
		{@const StatusIcon = status.icon}
		<div
			role="status"
			class="mt-6 flex items-start gap-2.5 rounded-md border border-app-note-line bg-app-note px-3.5 py-3 text-sm"
		>
			<StatusIcon size={17} class={['mt-0.5 shrink-0', status.tone]} aria-hidden="true" />
			<p>{status.text}</p>
		</div>
	{/if}

	<!-- The transparent border keeps the link's box where forced colors drop its fill. -->
	<a
		href={signInHref}
		data-sveltekit-reload
		class="mt-7 inline-flex h-11 w-full items-center justify-center gap-2 rounded-md border border-transparent bg-brand px-4 text-sm font-semibold text-brand-ink no-underline transition hover:brightness-95"
		>Sign in with your company account <ArrowRight size={16} aria-hidden="true" /></a
	>

	{#snippet aside()}
		<ul class="grid gap-4 text-sm text-on-ink/85">
			{#each FEATURES as feature (feature.text)}
				{@const Icon = feature.icon}
				<li class="flex items-center gap-3">
					<span class="grid size-8 shrink-0 place-items-center rounded-md bg-on-ink/10 text-brand"
						><Icon size={16} aria-hidden="true" /></span
					>{feature.text}
				</li>
			{/each}
		</ul>
	{/snippet}
</AuthShell>
