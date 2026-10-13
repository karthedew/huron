/** Browser-safe Huron identity; all credentials remain on the server. */
export interface HuronUser {
	id: string;
	username: string;
	displayName: string;
	isAdmin: boolean;
	disabled: boolean;
	polarisPrincipal: string;
	polarisPrincipalRole: string;
	createdAt: string;
}
