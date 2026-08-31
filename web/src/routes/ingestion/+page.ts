import { listDatasets, listProjects } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent }) => {
	const { organizations } = await parent();
	const projects = (
		await Promise.all(organizations.map((organization) => listProjects(organization.slug)))
	).flatMap((page) => page.items);
	const datasets = (
		await Promise.all(projects.map((project) => listDatasets(project.orgSlug, project.slug)))
	).flatMap((page) => page.items);

	return { projects, datasets };
};
