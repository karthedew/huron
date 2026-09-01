<script lang="ts">
	import { ArrowRight, CheckCircle2, LockKeyhole, Mail } from '@lucide/svelte';
	import AuthShell from '$design/components/AuthShell.svelte';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	const signupHref = $derived(`/signup?returnTo=${encodeURIComponent(data.returnTo)}`);
</script>

<svelte:head>
	<title>Sign in · Huron</title>
	<meta name="description" content="Sign in to your Huron lakehouse workspace." />
</svelte:head>

<AuthShell
	eyebrow="Welcome back"
	title="Sign in to Huron"
	detail="Use your organization identity to continue to the lakehouse workspace."
>
	{#if data.signedOut}
		<div
			class="mb-5 flex items-start gap-2.5 rounded-md border border-[var(--note-line)] bg-[var(--note-bg)] px-3.5 py-3 text-sm"
		>
			<CheckCircle2 size={17} class="mt-0.5 shrink-0 text-app-success" />
			<span>You’ve been signed out successfully.</span>
		</div>
	{/if}

	{#if form?.message}
		<div
			role="alert"
			class="mb-5 rounded-md border border-app-danger/35 bg-app-danger/10 px-3.5 py-3 text-sm text-app-danger"
		>
			{form.message}
		</div>
	{/if}

	<form method="POST" class="grid gap-4">
		<input type="hidden" name="returnTo" value={data.returnTo} />
		<label class="grid gap-1.5 text-xs font-semibold text-app-muted">
			Email address
			<span class="relative block">
				<Mail
					size={16}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					name="email"
					type="email"
					autocomplete="email"
					required
					value={form?.email ?? ''}
					placeholder="you@example.org"
					class="h-11 w-full rounded-md border border-app-line bg-app-card pl-10 pr-3 text-sm font-normal text-app-fg outline-none placeholder:text-app-muted focus:border-brand-strong"
				/>
			</span>
		</label>

		<div class="grid gap-1.5 text-xs font-semibold text-app-muted">
			<div class="flex items-center justify-between">
				<label for="password">Password</label>
				<button type="button" class="font-medium text-brand-strong hover:underline"
					>Forgot password?</button
				>
			</div>
			<span class="relative block">
				<LockKeyhole
					size={16}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					id="password"
					name="password"
					type="password"
					autocomplete="current-password"
					required
					placeholder="Enter your password"
					class="h-11 w-full rounded-md border border-app-line bg-app-card pl-10 pr-3 text-sm font-normal text-app-fg outline-none placeholder:text-app-muted focus:border-brand-strong"
				/>
			</span>
		</div>

		<label class="flex w-fit items-center gap-2 text-sm text-app-muted">
			<input name="remember" type="checkbox" class="size-4 accent-[var(--brand-strong)]" />
			Keep me signed in
		</label>

		<button
			type="submit"
			class="mt-1 inline-flex h-11 items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-[#062d29] transition hover:brightness-95"
		>
			Sign in <ArrowRight size={16} />
		</button>
	</form>

	<p class="mt-6 text-center text-sm text-app-muted">
		New to Huron? <a href={signupHref} class="font-semibold text-brand-strong hover:underline"
			>Create an account</a
		>
	</p>
	<p class="mt-6 border-t border-app-line pt-5 text-xs leading-5 text-app-muted">
		Preview mode accepts any non-empty credentials. Production authentication will use your
		configured identity provider.
	</p>
</AuthShell>
