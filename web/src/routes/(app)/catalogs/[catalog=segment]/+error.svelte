<script lang="ts">
	import ShellError from '$design/components/ShellError.svelte';
</script>

<!--
	A failure below a catalog the user can see (a namespace or collection that does not exist, a
	tab whose read failed) keeps the catalog layout: its breadcrumbs, its explorer and its
	organization, which the shell shows and the error offers to go back to.
-->
<ShellError />
