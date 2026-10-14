<script lang="ts">
	import { enhance } from '$app/forms';
	import { page } from '$app/state';
	import type { SubmitFunction } from '@sveltejs/kit';
	import type { Snippet } from 'svelte';
	import { fromAction } from 'svelte/attachments';
	import type { PolarisActionResult } from '$api/types';

	let {
		action,
		submit,
		children,
		onSuccess,
		danger = false,
		disabled = false
	}: {
		action: string;
		submit: string;
		children?: Snippet;
		onSuccess?: (result: PolarisActionResult) => void | Promise<void>;
		danger?: boolean;
		disabled?: boolean;
	} = $props();
	let pending = $state(false);
	const target = $derived.by(() => {
		const query = new URLSearchParams(page.url.searchParams);
		if (page.data.selectedOrganization) query.set('organization', page.data.selectedOrganization);
		for (const key of [...query.keys()]) if (key.startsWith('/')) query.delete(key);
		query.set(`/${action}`, '');
		return `${page.url.pathname}?${query}`;
	});
	const submitForm: SubmitFunction<PolarisActionResult, PolarisActionResult> = () => {
		pending = true;
		return async ({ update, result }) => {
			try {
				if (result.type === 'success' && result.data && onSuccess) {
					await onSuccess(result.data);
					await update({ invalidateAll: false });
				} else {
					await update();
				}
			} finally {
				pending = false;
			}
		};
	};
	function enhancePolaris(element: HTMLFormElement): ReturnType<typeof enhance> {
		return enhance<PolarisActionResult, PolarisActionResult>(element, submitForm);
	}
</script>

<form method="POST" action={target} {@attach fromAction(enhancePolaris)} aria-busy={pending}>
	<fieldset disabled={pending} class="m-0 grid min-w-0 gap-3 border-0 p-0">
		{@render children?.()}
		<button
			type="submit"
			disabled={disabled || pending}
			class={[
				'w-fit rounded-md border px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50',
				danger
					? 'border-app-danger/40 text-app-danger hover:bg-app-danger/10'
					: 'border-brand-strong bg-brand-soft text-brand-strong hover:brightness-95'
			]}
		>
			{pending ? 'Working…' : submit}
		</button>
	</fieldset>
	{#if pending}<p role="status" class="mt-2 text-xs text-app-muted">Waiting for Polaris…</p>{/if}
</form>
