<script lang="ts">
	import { page } from '$app/state';
</script>

<!--
	404-not-403 (design/frontend.html §1): a resource the principal cannot discover is
	rendered as nonexistent. The UI must never disclose that something exists but is
	forbidden — no "request access" affordance, no distinct wording.
-->
<h1>{page.status === 404 ? 'Not found' : 'Something went wrong'}</h1>
<p class="muted">
	{#if page.status === 404}
		No such resource at <code>{page.url.pathname}</code>.
	{:else}
		{page.error?.message ?? 'Unexpected error.'}
	{/if}
</p>
<p><a href="/">Back to search</a></p>
