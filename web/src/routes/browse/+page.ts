import { listDatasets, listOrganizations, listProjects } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => {
	const organizations = (await listOrganizations()).items;
	const projects = (
		await Promise.all(organizations.map((organization) => listProjects(organization.slug)))
	).flatMap((page) => page.items);
	const datasets = (
		await Promise.all(projects.map((project) => listDatasets(project.orgSlug, project.slug)))
	).flatMap((page) => page.items);
	return { organizations, projects, datasets };
};
