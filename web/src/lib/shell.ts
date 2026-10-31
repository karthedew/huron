import { createContext } from 'svelte';
import type { ShellOrganization } from './organizations';

/**
 * The organization the shell (`(app)/+layout.svelte`) shows as current, for the pages inside it.
 * An error page has no data of its own, so this is how it learns where the user was.
 */
export const [shellOrganization, setShellOrganization] =
	createContext<() => ShellOrganization | null>();
