<script lang="ts">
	import { ArrowRight, LockKeyhole, Mail, UserRound } from '@lucide/svelte';
	import AuthShell from '$design/components/AuthShell.svelte';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	const loginHref = $derived(`/login?returnTo=${encodeURIComponent(data.returnTo)}`);
	const fieldClass =
		'h-11 w-full rounded-md border border-app-line bg-app-card pl-10 pr-3 text-sm font-normal text-app-fg outline-none placeholder:text-app-muted focus:border-brand-strong';
</script>

<svelte:head>
	<title>Create account · Huron</title>
	<meta name="description" content="Create a Huron lakehouse workspace account." />
</svelte:head>

<AuthShell
	eyebrow="Get started"
	title="Create your account"
	detail="Set up your Huron identity. An organization administrator can grant workspace access next."
>
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
			Display name
			<span class="relative block">
				<UserRound
					size={16}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					name="displayName"
					autocomplete="name"
					required
					value={form?.displayName ?? ''}
					placeholder="Karl Schmidt"
					class={fieldClass}
				/>
			</span>
		</label>

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
					class={fieldClass}
				/>
			</span>
		</label>

		<div class="grid gap-4 sm:grid-cols-2">
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted">
				Password
				<span class="relative block">
					<LockKeyhole
						size={16}
						class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
					/>
					<input
						name="password"
						type="password"
						autocomplete="new-password"
						required
						minlength="8"
						placeholder="8+ characters"
						class={fieldClass}
					/>
				</span>
			</label>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted">
				Confirm password
				<span class="relative block">
					<LockKeyhole
						size={16}
						class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
					/>
					<input
						name="confirmation"
						type="password"
						autocomplete="new-password"
						required
						minlength="8"
						placeholder="Repeat password"
						class={fieldClass}
					/>
				</span>
			</label>
		</div>

		<label class="flex items-start gap-2.5 text-sm leading-5 text-app-muted">
			<input
				name="terms"
				type="checkbox"
				required
				class="mt-0.5 size-4 shrink-0 accent-[var(--brand-strong)]"
			/>
			<span>I agree to the acceptable-use policy and my organization’s data-handling rules.</span>
		</label>

		<button
			type="submit"
			class="mt-1 inline-flex h-11 items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-[#062d29] transition hover:brightness-95"
		>
			Create account <ArrowRight size={16} />
		</button>
	</form>

	<p class="mt-6 text-center text-sm text-app-muted">
		Already have an account? <a
			href={loginHref}
			class="font-semibold text-brand-strong hover:underline">Sign in</a
		>
	</p>
	<p class="mt-6 border-t border-app-line pt-5 text-xs leading-5 text-app-muted">
		Preview signup creates a local browser session. Production accounts and organization membership
		will be provisioned through the authentication service.
	</p>
</AuthShell>
