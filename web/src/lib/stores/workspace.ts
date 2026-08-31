import { browser } from '$app/environment';
import { writable } from 'svelte/store';

const storedOrganization = browser ? localStorage.getItem('huron-organization') : null;

export const selectedOrganization = writable(storedOrganization ?? 'example-org');

if (browser) {
	selectedOrganization.subscribe((slug) => localStorage.setItem('huron-organization', slug));
}
