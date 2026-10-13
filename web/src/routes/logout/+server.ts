import { redirect, type RequestHandler } from '@sveltejs/kit';
import { clearHuronSession } from '$lib/server/auth';

export const POST: RequestHandler = ({ cookies }) => {
	clearHuronSession(cookies);
	redirect(303, '/login?status=signed-out');
};
