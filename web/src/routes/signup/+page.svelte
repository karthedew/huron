<script lang="ts">
	import { resolve } from '$app/paths';
	import { ArrowRight } from '@lucide/svelte';
	import AuthShell from '$design/components/AuthShell.svelte';
	import type { ActionData, PageData } from './$types';
	let { data, form }: { data: PageData; form: ActionData } = $props();
	const fieldClass =
		'h-11 w-full rounded-md border border-app-line bg-app-card px-3 text-sm font-normal text-app-fg outline-none focus:border-brand-strong';
</script>

<svelte:head><title>Create account · Huron</title></svelte:head>
<AuthShell
	eyebrow="Catalog access"
	title={data.registrationAllowed
		? 'Create your account'
		: 'Accounts are managed by your administrator'}
	detail="A Huron administrator adds people to individual Polaris catalogs."
>
	{#if form?.message}<div
			role="alert"
			class="mb-5 rounded-md border border-app-danger/35 bg-app-danger/10 px-3.5 py-3 text-sm text-app-danger"
		>
			{form.message}
		</div>{/if}
	{#if data.registrationAllowed}
		<form method="POST" class="grid gap-4">
			<input type="hidden" name="returnTo" value={data.returnTo} />
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Display name<input
					name="displayName"
					autocomplete="name"
					required
					maxlength="120"
					value={form?.displayName ?? ''}
					class={fieldClass}
				/></label
			>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Username<input
					name="username"
					autocomplete="username"
					required
					minlength="3"
					maxlength="64"
					pattern={'[a-zA-Z][a-zA-Z0-9_.-]{2,63}'}
					value={form?.username ?? ''}
					class={fieldClass}
				/><span class="font-normal"
					>Letters, numbers, dots, underscores and hyphens; begin with a letter.</span
				></label
			>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Password<input
					name="password"
					type="password"
					autocomplete="new-password"
					required
					minlength="8"
					maxlength="256"
					class={fieldClass}
				/></label
			>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Confirm password<input
					name="confirmation"
					type="password"
					autocomplete="new-password"
					required
					minlength="8"
					maxlength="256"
					class={fieldClass}
				/></label
			>
			<button
				type="submit"
				class="mt-1 inline-flex h-11 items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-[#062d29] transition hover:brightness-95"
				>Create account <ArrowRight size={16} /></button
			>
		</form>
		<p class="mt-5 text-sm text-app-muted">
			Your new account starts without catalog access. Ask an administrator to add you.
		</p>
	{:else}<p class="text-sm leading-6 text-app-muted">
			Ask your administrator to create your account with a username and password and choose which
			catalogs you can access.
		</p>{/if}
	<p class="mt-6 text-center text-sm">
		<a
			href={resolve(`/login?returnTo=${encodeURIComponent(data.returnTo)}`)}
			class="font-semibold text-brand-strong hover:underline">Back to sign in</a
		>
	</p>
</AuthShell>
