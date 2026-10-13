<script lang="ts">
	import { resolve } from '$app/paths';
	import { ArrowRight, CheckCircle2, LockKeyhole, UserRound } from '@lucide/svelte';
	import AuthShell from '$design/components/AuthShell.svelte';
	import type { ActionData, PageData } from './$types';
	let { data, form }: { data: PageData; form: ActionData } = $props();
	const fieldClass =
		'h-11 w-full rounded-md border border-app-line bg-app-card pl-10 pr-3 text-sm font-normal text-app-fg outline-none placeholder:text-app-muted focus:border-brand-strong';
</script>

<svelte:head><title>Sign in · Huron</title></svelte:head>
<AuthShell
	eyebrow="Welcome back"
	title="Sign in to Huron"
	detail="Use your Huron username and password to access your Polaris catalogs."
>
	{#if data.signedOut || data.passwordChanged}
		<div
			role="status"
			class="mb-5 flex items-start gap-2.5 rounded-md border border-[var(--note-line)] bg-[var(--note-bg)] px-3.5 py-3 text-sm"
		>
			<CheckCircle2 size={17} class="mt-0.5 shrink-0 text-app-success" />
			<span
				>{data.passwordChanged
					? 'Your password has changed. Sign in again.'
					: 'You’ve been signed out successfully.'}</span
			>
		</div>
	{/if}
	{#if form?.message}<div
			role="alert"
			class="mb-5 rounded-md border border-app-danger/35 bg-app-danger/10 px-3.5 py-3 text-sm text-app-danger"
		>
			{form.message}
		</div>{/if}
	<form method="POST" class="grid gap-4">
		<input type="hidden" name="returnTo" value={data.returnTo} />
		<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
			>Username
			<span class="relative block"
				><UserRound
					size={16}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					name="username"
					autocomplete="username"
					required
					maxlength="64"
					value={form?.username ?? ''}
					placeholder="Your username"
					class={fieldClass}
				/>
			</span>
		</label>
		<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
			>Password
			<span class="relative block"
				><LockKeyhole
					size={16}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					name="password"
					type="password"
					autocomplete="current-password"
					required
					maxlength="256"
					placeholder="Enter your password"
					class={fieldClass}
				/>
			</span>
		</label>
		<button
			type="submit"
			class="mt-1 inline-flex h-11 items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-[#062d29] transition hover:brightness-95"
			>Sign in <ArrowRight size={16} /></button
		>
	</form>
	{#if data.registrationAllowed}<p class="mt-6 text-center text-sm text-app-muted">
			New to Huron? <a
				href={resolve(`/signup?returnTo=${encodeURIComponent(data.returnTo)}`)}
				class="font-semibold text-brand-strong hover:underline">Create an account</a
			>
		</p>{/if}
	<p class="mt-6 border-t border-app-line pt-5 text-xs leading-5 text-app-muted">
		Ask your Huron administrator for an account, catalog access or a password reset.
	</p>
</AuthShell>
