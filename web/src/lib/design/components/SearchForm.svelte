<script lang="ts">
	import { CircleAlert, Search as SearchIcon, X } from '@lucide/svelte';
	import {
		MAX_TEXT_LENGTH,
		SEARCH_STATES,
		STATE_NAMES,
		formLabel,
		labelText,
		searchedStates,
		tidySearchForm,
		withoutLabel,
		type Search,
		type SearchErrors
	} from '$lib/search';
	import { REMOVE_CHIP } from '../chips';

	interface Props {
		/** The form's name, e.g. "Catalog search". */
		label: string;
		/** The search page's own address, without a query. */
		action: string;
		search: Search;
		errors: SearchErrors;
		/** Label text that is no filter, back in the field for adding one, to be fixed there. */
		pendingLabel: string;
		/** Whether the user may see drafts here: only then can a search include them. */
		drafts: boolean;
		/** The address of this search page for another search. */
		href: (search: Search) => string;
	}

	let { label, action, search, errors, pendingLabel, drafts, href }: Props = $props();

	const id = $props.id();
	const offered = $derived(SEARCH_STATES.filter((state) => state !== 'draft' || drafts));
	const checked = $derived(searchedStates(search));
	const textDescription = $derived(
		[errors.q === null ? null : `${id}-q-error`, `${id}-help`].filter((part) => part !== null)
	);

	const FIELD =
		'block w-full min-w-0 rounded-md border border-app-line-strong bg-app-bg py-2 text-sm text-app-fg placeholder:text-app-muted aria-invalid:border-app-danger';
	const ERROR = 'mt-1.5 mb-0 flex items-start gap-1.5 text-sm font-semibold text-app-danger';

	/**
	 * With scripts, a search leads to its canonical address, whoever reads the form's data: the
	 * browser or SvelteKit's router. Without them, the browser's own encoding of the form reads as
	 * the same search.
	 */
	function tidy(event: FormDataEvent) {
		tidySearchForm(event.formData, { drafts });
	}
</script>

{#snippet error(message: string, field: string)}
	<p id="{id}-{field}-error" class={ERROR}>
		<CircleAlert size={16} class="mt-0.5 shrink-0" aria-hidden="true" />{message}
	</p>
{/snippet}

<!--
	Drawn afresh for each search, so its fields always hold the search shown: text typed and not
	searched is gone once another search shows, and so is a label once it became a filter.
-->
{#key search}
	<form
		role="search"
		aria-label={label}
		aria-describedby={errors.form === null ? undefined : `${id}-form-error`}
		method="GET"
		{action}
		onformdata={tidy}
		class="@container rounded-card border border-app-line bg-app-card p-4"
	>
		{#if errors.form !== null}
			<div class="mb-4">{@render error(errors.form, 'form')}</div>
		{/if}
		<div>
			<label for="{id}-q" class="text-sm font-semibold">Search text</label>
			<div class="relative mt-1.5">
				<SearchIcon
					size={16}
					class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-app-muted"
					aria-hidden="true"
				/>
				<input
					id="{id}-q"
					name="q"
					type="search"
					value={search.q}
					maxlength={MAX_TEXT_LENGTH}
					spellcheck="false"
					aria-invalid={errors.q === null ? undefined : 'true'}
					aria-describedby={textDescription.join(' ')}
					class={[FIELD, 'pr-3 pl-9']}
				/>
			</div>
			{#if errors.q !== null}{@render error(errors.q, 'q')}{/if}
			<p id="{id}-help" class="mt-1.5 mb-0 text-xs text-app-muted">
				Matches the exact text in identifiers, titles and descriptions. Use labels for exact
				key=value filters. Sorted by identifier.
			</p>
		</div>
		<div class="mt-4 grid gap-4 @2xl:grid-cols-2 @2xl:gap-6">
			<fieldset class="m-0 min-w-0 border-0 p-0">
				<legend class="p-0 text-sm font-semibold">Labels</legend>
				{#if search.labels.length > 0}
					<ul class="m-0 mt-1.5 flex list-none flex-wrap gap-1.5 p-0" aria-label="Label filters">
						{#each search.labels as filter (labelText(filter))}
							{@const kept = formLabel(filter)}
							<li class="max-w-full">
								<input type="hidden" name={kept.name} value={kept.value} />
								<a
									href={href(withoutLabel(search, filter))}
									aria-label="Remove filter {filter.key} = {filter.value}"
									class={REMOVE_CHIP}
									><span class="min-w-0">{filter.key} = {filter.value}</span><X
										size={12}
										class="shrink-0"
										aria-hidden="true"
									/></a
								>
							</li>
						{/each}
					</ul>
				{/if}
				<label for="{id}-label" class="mt-2 block text-xs text-app-muted">Add a label filter</label>
				<input
					id="{id}-label"
					name="label"
					type="text"
					value={pendingLabel}
					placeholder="key=value"
					spellcheck="false"
					aria-invalid={errors.label === null ? undefined : 'true'}
					aria-describedby={errors.label === null ? undefined : `${id}-label-error`}
					class={[FIELD, 'mt-1 px-3']}
				/>
				{#if errors.label !== null}{@render error(errors.label, 'label')}{/if}
			</fieldset>
			<fieldset class="m-0 min-w-0 border-0 p-0">
				<legend class="p-0 text-sm font-semibold">States</legend>
				<div class="mt-1.5 flex flex-wrap gap-x-5 gap-y-2">
					{#each offered as state (state)}
						<label class="inline-flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								name="state"
								value={state}
								checked={checked.includes(state)}
								class="size-4 accent-brand-strong"
							/>{STATE_NAMES[state]}
						</label>
					{/each}
				</div>
			</fieldset>
		</div>
		<div class="mt-4 flex justify-end">
			<!-- The transparent border keeps the button's box where forced colors drop its fill. -->
			<button
				type="submit"
				class="inline-flex h-9 items-center gap-2 rounded-md border border-transparent bg-brand px-4 text-sm font-semibold text-brand-ink transition hover:brightness-95"
				><SearchIcon size={15} aria-hidden="true" />Search</button
			>
		</div>
	</form>
{/key}
