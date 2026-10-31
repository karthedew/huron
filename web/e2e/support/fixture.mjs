/**
 * The e2e fixture: who signs in, what they belong to, and every organization, catalog,
 * namespace, collection and schema `seed.mjs` creates through the real API. Tests import it
 * for their assertions, so expectations and seed data cannot drift apart.
 */
import { createHash } from 'node:crypto';

/** The web's OIDC client at the fake IdP. */
export const CLIENT_ID = 'huron-web';
export const CLIENT_SECRET = 'e2e-secret';
/** The API's `HURON_COMPANY_AUDIENCE`: ID tokens must carry it in `aud` for the exchange. */
export const API_AUDIENCE = 'huron-cli';
export const PLATFORM_ADMIN_GROUP = 'huron-platform-admins';
export const MOUNT_PREFIX = '/projects/huron';
/** The API's `HURON_INSTANCE_ID`; any fixed UUID. */
export const INSTANCE_ID = '0b9c6f3e-5d2a-4c1b-9e8f-7a6d5c4b3a21';

/** Every fixture user, in the order the fake IdP lists them. */
export const USERNAMES = /** @type {const} */ ([
	'alice',
	'paula',
	'bob',
	'carol',
	'dave',
	'erin',
	'oscar',
	'mallory',
	'noaud',
	'idpfail'
]);

/** @typedef {(typeof USERNAMES)[number]} Username */
/** @typedef {'catalog_admin' | 'contributor' | 'reader'} CatalogRole */
/** @typedef {'active' | 'draft' | 'incomplete'} CollectionState */

/**
 * @typedef {object} FixtureUser
 * @property {Username} username
 * @property {string} name
 * @property {string} email
 * @property {readonly string[]} groups The LDAP groups the fake group directory answers.
 * @property {string} about What the user is for, shown on the fake IdP's sign-in page.
 * @property {'no-api-audience' | 'token-endpoint-unavailable'} [special] A deliberate failure.
 */

/**
 * @param {Username} username
 * @param {string} name
 * @param {readonly string[]} groups
 * @param {string} about
 * @returns {FixtureUser}
 */
function person(username, name, groups, about) {
	return { username, name, email: `${username}@example.org`, groups, about };
}

/** @type {Readonly<Record<Username, FixtureUser>>} */
export const USERS = {
	alice: person(
		'alice',
		'Alice Anderson',
		[PLATFORM_ADMIN_GROUP],
		'Platform admin: sees everything.'
	),
	// A user may hold 10 web sessions; signing in once more ends the oldest. The long walks of
	// e2e/layout.test.ts sign in as paula, whom no other test uses, so that tests signing in as
	// alice meanwhile never end their session.
	paula: person(
		'paula',
		'Paula Park',
		[PLATFORM_ADMIN_GROUP],
		'Platform admin of the layout walks: sees everything.'
	),
	bob: person('bob', 'Bob Baker', ['helio-org-admins'], 'Org admin of helio.'),
	carol: person(
		'carol',
		'Carol Chen',
		['helio-catalog-admins'],
		'Catalog admin of heliophysics and space-weather.'
	),
	dave: person(
		'dave',
		'Dave Diaz',
		['helio-contributors', 'geo-readers'],
		'Contributor in helio, reader of geoscience.'
	),
	erin: person('erin', 'Erin Evans', ['helio-readers'], 'Reader in helio.'),
	oscar: person('oscar', 'Oscar Ortiz', ['helio-readers'], 'Reader in helio; for fault injection.'),
	mallory: person('mallory', 'Mallory Moore', [], 'No groups.'),
	noaud: {
		...person('noaud', 'Nadia Noaud', ['helio-readers'], 'ID token without the API audience.'),
		special: 'no-api-audience'
	},
	idpfail: {
		...person('idpfail', 'Ivan Idpfail', ['helio-readers'], 'The token endpoint fails.'),
		special: 'token-endpoint-unavailable'
	}
};

/** The `sub` claim the fake IdP issues; the API's subject is the username instead. */
export function companySubject(/** @type {Username} */ username) {
	return `sub-${username}`;
}

/**
 * Whether `value` names a fixture user.
 * @param {string} value
 * @returns {value is Username}
 */
export function isUsername(value) {
	return USERNAMES.some((username) => username === value);
}

/**
 * @typedef {object} FixtureOrganization
 * @property {string} name
 * @property {string} displayName
 * @property {string} description
 * @property {readonly string[]} orgAdmins
 * @property {Username} createdBy
 */

/** @type {readonly FixtureOrganization[]} */
export const ORGANIZATIONS = [
	{
		name: 'helio',
		displayName: 'Heliophysics Division',
		description: 'The Sun, the solar wind and the space environment.',
		orgAdmins: ['helio-org-admins'],
		createdBy: 'alice'
	},
	{
		name: 'geo',
		displayName: 'Earth Science',
		description: 'Earth observation and ocean data.',
		orgAdmins: ['geo-org-admins'],
		createdBy: 'alice'
	},
	{
		name: 'astro',
		displayName: 'Astrophysics',
		description: '',
		orgAdmins: [],
		createdBy: 'alice'
	},
	{
		// Without catalogs: only alice sees it, with the hint to create the first one. The long
		// unbroken path in its description must wrap on narrow screens.
		name: 'planetary',
		displayName: 'Planetary Science',
		description:
			'Planetary missions, before their first catalog: https://archive.example.org/planetary/mars_reconnaissance_orbiter_high_resolution_imaging_science_experiment/',
		orgAdmins: ['planetary-org-admins'],
		createdBy: 'alice'
	}
];

/**
 * @typedef {object} FixtureGrant
 * @property {CatalogRole} role
 * @property {readonly string[]} groups The role's whole set: the API replaces it.
 * @property {Username} grantedBy
 */

/**
 * @typedef {object} FixtureCatalog
 * @property {string} name
 * @property {string} organization
 * @property {string} displayName
 * @property {string} description
 * @property {Username} createdBy
 * @property {readonly FixtureGrant[]} grants
 */

/** @type {(grantors: { admin: Username, members: Username }) => readonly FixtureGrant[]} */
const helioGrants = ({ admin, members }) => [
	{ role: 'catalog_admin', groups: ['helio-catalog-admins'], grantedBy: admin },
	{ role: 'contributor', groups: ['helio-contributors'], grantedBy: members },
	{ role: 'reader', groups: ['helio-readers'], grantedBy: members }
];

/** @type {readonly FixtureCatalog[]} */
export const CATALOGS = [
	{
		name: 'heliophysics',
		organization: 'helio',
		displayName: 'Heliophysics',
		description: 'Solar wind, fields and energetic particles.',
		createdBy: 'bob',
		grants: helioGrants({ admin: 'bob', members: 'carol' })
	},
	{
		name: 'space-weather',
		organization: 'helio',
		displayName: 'Space Weather',
		description: 'Indices and event lists for space weather.',
		createdBy: 'bob',
		grants: helioGrants({ admin: 'bob', members: 'carol' })
	},
	{
		name: 'geoscience',
		organization: 'geo',
		displayName: 'Geoscience',
		description: 'Ocean and land observations.',
		createdBy: 'alice',
		grants: [{ role: 'reader', groups: ['geo-readers'], grantedBy: 'alice' }]
	},
	{
		name: 'exoplanets',
		organization: 'astro',
		displayName: 'Exoplanets',
		// The long unbroken path must wrap on narrow screens.
		description:
			'Planet survey data products from https://archive.example.org/exoplanets/transiting_exoplanet_survey_satellite_full_frame_image_products/',
		createdBy: 'alice',
		grants: []
	}
];

/**
 * @typedef {object} FixtureNamespace
 * @property {string} catalog
 * @property {string} path Dotted, e.g. `solar-wind.ace`; parents come before their children.
 * @property {boolean} collectionsAllowed
 * @property {Username} createdBy
 */

/** @type {(n: number, width: number) => string} */
const padded = (n, width) => String(n).padStart(width, '0');

/**
 * How many stations `space-weather.stations` holds: more than the 50 a level of the explorer
 * loads, so a station beyond them is pinned to the explorer as the current node.
 */
export const STATION_COUNT = 55;

/** @type {ReadonlyArray<readonly [string, boolean]>} */
const STATIONS = Array.from({ length: STATION_COUNT }, (_, index) => [
	`stations.station-${padded(index + 1, 2)}`,
	true
]);

/**
 * @param {string} catalog
 * @param {Username} createdBy
 * @param {ReadonlyArray<readonly [string, boolean]>} entries Paths with `collectionsAllowed`.
 * @returns {FixtureNamespace[]}
 */
function namespacesOf(catalog, createdBy, entries) {
	return entries.map(([path, collectionsAllowed]) => ({
		catalog,
		path,
		collectionsAllowed,
		createdBy
	}));
}

/** @type {readonly FixtureNamespace[]} */
export const NAMESPACES = [
	...namespacesOf('heliophysics', 'carol', [
		['solar-wind', false],
		['solar-wind.ace', true],
		['solar-wind.wind', true],
		['fields', true],
		['empty', true],
		['deep', false],
		['deep.a', false],
		['deep.a.b', false],
		['deep.a.b.c', true]
	]),
	...namespacesOf('space-weather', 'carol', [['alerts', true], ['stations', false], ...STATIONS]),
	...namespacesOf('geoscience', 'alice', [['ocean', true]]),
	...namespacesOf('exoplanets', 'alice', [['surveys', true]])
];

/**
 * @typedef {object} FixtureFile
 * @property {string} relPath
 * @property {number} size
 */

/**
 * @typedef {object} FixtureCommit
 * @property {string | null} message
 * @property {string} host
 * @property {readonly FixtureFile[]} adds
 * @property {readonly string[]} removes
 */

/**
 * @typedef {object} FixtureCollection
 * @property {string} catalog
 * @property {string} namespace
 * @property {string} name
 * @property {Username} createdBy
 * @property {CollectionState} state The state after seeding: drafts are never activated, and
 *   `incomplete` collections are activated before the schema that makes them incomplete.
 * @property {Record<string, unknown>} metadata
 * @property {Record<string, unknown>} [schemaOverride] Set on the draft, before activation.
 * @property {readonly FixtureCommit[]} commits Applied in order after activation.
 */

const runCount = 60;
/** How many files `fields.run001` records. */
export const RUN001_FILE_COUNT = 120;

/** @type {(index: number) => FixtureCollection} */
function fieldsRun(index) {
	const run = padded(index, 3);
	return {
		catalog: 'heliophysics',
		namespace: 'fields',
		name: `run${run}`,
		createdBy: 'dave',
		state: 'active',
		metadata: {
			title: `Encounter 17 run ${run}`,
			description: `FIELDS burst-mode electric and magnetic field data, encounter 17, run ${run}.`,
			instrument: 'FIELDS',
			campaign: 'Encounter 17',
			labels: { mission: 'psp', encounter: '17' }
		},
		commits:
			index === 1
				? [
						{
							message: null,
							host: 'psp-dtn.example.org',
							adds: Array.from({ length: RUN001_FILE_COUNT }, (_, frame) => ({
								relPath: `frames/frame-${padded(frame + 1, 4)}.dat`,
								size: 1_048_576 + (frame + 1) * 512
							})),
							removes: []
						}
					]
				: []
	};
}

/**
 * A collection whose metadata holds a value of every kind the Overview shows: its own schema
 * override describes dates, addresses, numbers, booleans and an object, and it has fields no
 * schema names. The mirror's `ftp:` address must show as text, never as a link. Its calibration
 * holds numbers too small and too large for plain digits, which must show exactly, and a key no
 * line can break (as tools that write camelCase make them), in an object and in a list's item,
 * which must wrap on a phone.
 * @type {FixtureCollection}
 */
const SWE_2023 = {
	catalog: 'heliophysics',
	namespace: 'solar-wind.wind',
	name: 'swe-2023',
	createdBy: 'dave',
	state: 'active',
	metadata: {
		title: 'Wind SWE ion moments, 2023',
		description: 'Proton and alpha moments from the Wind Solar Wind Experiment, 92-second cadence.',
		keywords: ['solar wind', 'ions', 'moments'],
		contacts: [{ name: 'SWE instrument team', email: 'swe-team@example.org' }],
		instrument: 'SWE',
		campaign: 'Wind extended mission',
		start_time: '2023-01-01T00:00:00Z',
		end_time: '2023-12-31T23:59:59Z',
		release_date: '2024-03-15',
		landing_page: 'https://data.example.org/wind/swe/2023/',
		mirror: 'ftp://ftp.example.org/pub/wind/swe/2023/',
		cadence_seconds: 92,
		fill_value: -9999.5,
		calibrated: true,
		energy_bands_ev: [150, 300, 600, 1200],
		processing: { level: 'L2', software: 'swe-moments 4.2', reprocessed: false },
		archive_note: 'Reprocessed after the 2024 calibration.\nSee the release notes.',
		calibration: {
			proton_mass_kg: 1.67262192e-27,
			cdf_fill_value: -1e31,
			faradayCupEffectiveAreaCalibrationCoefficientsRevisionForSensorUnitB: 'rev-7',
			history: [{ faradayCupEffectiveAreaCalibrationCoefficientsRevisionForSensorUnitB: 'rev-6' }]
		},
		labels: { mission: 'wind', instrument: 'swe', level: 'l2' }
	},
	schemaOverride: {
		type: 'object',
		title: 'Wind SWE additions',
		properties: {
			release_date: { type: 'string', format: 'date', title: 'Release date' },
			landing_page: { type: 'string', format: 'uri', title: 'Landing page' },
			mirror: { type: 'string', format: 'uri', title: 'Mirror' },
			cadence_seconds: { type: 'integer', title: 'Cadence (s)', minimum: 1 },
			fill_value: { type: 'number', title: 'Fill value' },
			calibrated: { type: 'boolean', title: 'Calibrated' },
			energy_bands_ev: { type: 'array', title: 'Energy bands (eV)', items: { type: 'number' } },
			processing: {
				type: 'object',
				title: 'Processing',
				required: ['level'],
				properties: {
					level: { type: 'string', title: 'Level' },
					software: { type: 'string', title: 'Software' },
					reprocessed: { type: 'boolean', title: 'Reprocessed' }
				}
			}
		},
		required: ['release_date']
	},
	commits: []
};

/** @type {readonly FixtureCollection[]} */
export const COLLECTIONS = [
	{
		catalog: 'heliophysics',
		namespace: 'solar-wind.ace',
		name: 'mag-l2-2024',
		createdBy: 'dave',
		state: 'active',
		metadata: {
			title: 'ACE MAG level 2, 2024',
			description:
				'Interplanetary magnetic field vectors from the ACE magnetometer, 16-second averages.',
			keywords: ['magnetic field', 'solar wind', 'L1'],
			contacts: [
				{ name: 'ACE MAG team', email: 'ace-mag@example.org' },
				{ name: 'Science data center' }
			],
			instrument: 'MAG',
			start_time: '2024-01-01T00:00:00Z',
			end_time: '2024-12-31T23:59:59Z',
			labels: { mission: 'ace', instrument: 'mag', level: 'l2' }
		},
		commits: [
			{
				message: 'Initial upload',
				host: 'dtn01.example.org',
				adds: [
					{ relPath: 'data/ace_mag_l2_2024-01.cdf', size: 48_234_496 },
					{ relPath: 'data/ace_mag_l2_2024-02.cdf', size: 45_088_768 },
					{ relPath: 'README.txt', size: 2_048 }
				],
				removes: []
			},
			{
				message: 'Replace the README with release notes',
				host: 'dtn02.example.org',
				adds: [{ relPath: 'RELEASE_NOTES.md', size: 3_172 }],
				removes: ['README.txt']
			}
		]
	},
	{
		catalog: 'heliophysics',
		namespace: 'solar-wind.ace',
		name: 'swepam-2024',
		createdBy: 'dave',
		state: 'active',
		metadata: {
			title: 'ACE SWEPAM 2024',
			description: 'Solar wind proton density, speed and temperature from ACE SWEPAM.',
			instrument: 'SWEPAM',
			labels: { mission: 'ace', instrument: 'swepam' }
		},
		commits: []
	},
	{
		catalog: 'heliophysics',
		namespace: 'solar-wind.ace',
		name: 'mag-l1-draft',
		createdBy: 'dave',
		state: 'draft',
		metadata: { title: 'ACE MAG level 1 (draft)' },
		commits: []
	},
	{
		catalog: 'heliophysics',
		namespace: 'solar-wind.wind',
		name: 'mfi-2023',
		createdBy: 'dave',
		state: 'active',
		metadata: {
			title: 'Wind MFI 2023',
			description: 'Magnetic field investigation data from the Wind spacecraft, 2023.',
			instrument: 'MFI',
			labels: { mission: 'wind' }
		},
		commits: []
	},
	SWE_2023,
	...Array.from({ length: runCount }, (_, index) => fieldsRun(index + 1)),
	{
		catalog: 'heliophysics',
		namespace: 'deep.a.b.c',
		name: 'leaf',
		createdBy: 'dave',
		state: 'active',
		metadata: {
			title: 'Deeply nested leaf',
			description: 'A collection four namespaces deep.'
		},
		commits: []
	},
	{
		catalog: 'space-weather',
		namespace: 'alerts',
		name: 'kp-index-2024',
		createdBy: 'dave',
		state: 'active',
		metadata: {
			title: 'Kp index 2024',
			description: 'Three-hourly planetary geomagnetic activity index, 2024.',
			mission: 'ground-magnetometers'
		},
		commits: []
	},
	{
		catalog: 'space-weather',
		namespace: 'alerts',
		name: 'flare-list-2024',
		createdBy: 'dave',
		state: 'incomplete',
		metadata: {
			title: 'Flare list 2024',
			description: 'Solar X-ray flare events detected in 2024.'
		},
		commits: []
	},
	{
		// Its override types mission as a number, which huron-base allows; the space-weather
		// schema, assigned later, types it as text, so the override no longer fits.
		catalog: 'space-weather',
		namespace: 'alerts',
		name: 'storm-count-2024',
		createdBy: 'dave',
		state: 'incomplete',
		metadata: {
			title: 'Storm count 2024',
			description: 'Monthly count of geomagnetic storms in 2024, by observing network.',
			mission: 7
		},
		schemaOverride: {
			type: 'object',
			title: 'Storm count additions',
			properties: { mission: { type: 'integer', title: 'Network number' } }
		},
		commits: []
	},
	{
		catalog: 'geoscience',
		namespace: 'ocean',
		name: 'sst-2024',
		createdBy: 'alice',
		state: 'active',
		metadata: {
			title: 'Sea surface temperature 2024',
			description: 'Daily global sea surface temperature analysis, 2024.',
			labels: { mission: 'mur' }
		},
		commits: []
	},
	{
		catalog: 'exoplanets',
		namespace: 'surveys',
		name: 'tess-sectors',
		createdBy: 'alice',
		state: 'active',
		metadata: {
			title: 'TESS sectors',
			description: 'Sector pointings and cadences of the TESS survey.'
		},
		commits: []
	}
];

/**
 * @typedef {object} FixtureSchema
 * @property {string} organization
 * @property {string} name
 * @property {string} extends The platform schema it extends, by name (its latest version).
 * @property {Record<string, unknown>} document
 * @property {Username} publishedBy
 * @property {readonly string[]} assignedTo Catalogs that use it.
 * @property {Username} assignedBy
 */

/** @type {readonly FixtureSchema[]} */
export const SCHEMAS = [
	{
		organization: 'helio',
		name: 'space-weather',
		extends: 'huron-base',
		document: {
			type: 'object',
			title: 'Space weather metadata',
			description: 'The base fields plus the mission or network that produced the data.',
			properties: { mission: { type: 'string', title: 'Mission', minLength: 1 } },
			required: ['mission']
		},
		publishedBy: 'bob',
		assignedTo: ['space-weather'],
		assignedBy: 'carol'
	}
];

/** `catalog.namespace.path`. */
export function namespaceIdentifier(/** @type {FixtureNamespace} */ namespace) {
	return `${namespace.catalog}.${namespace.path}`;
}

/** `catalog.namespace.path.name`. */
export function collectionIdentifier(/** @type {FixtureCollection} */ collection) {
	return `${collection.catalog}.${collection.namespace}.${collection.name}`;
}

/** The collection with this full identifier; throws for an unknown one. */
export function collection(/** @type {string} */ identifier) {
	const found = COLLECTIONS.find((candidate) => collectionIdentifier(candidate) === identifier);
	if (found === undefined) throw new Error(`no fixture collection ${identifier}`);
	return found;
}

/**
 * The title the web shows for the collection with this full identifier: its metadata's title,
 * else the identifier.
 * @param {string} identifier
 * @returns {string}
 */
export function titleOf(identifier) {
	const { title } = collection(identifier).metadata;
	return typeof title === 'string' ? title : identifier;
}

/** The files a collection records once all its commits are applied, in commit order. */
export function recordedFiles(/** @type {FixtureCollection} */ collection) {
	/** @type {Map<string, FixtureFile>} */
	const files = new Map();
	for (const commit of collection.commits) {
		for (const removed of commit.removes) files.delete(removed);
		for (const added of commit.adds) files.set(added.relPath, added);
	}
	return [...files.values()];
}

/** The SHA-256 the seed records for a file: derived from its place, so it is stable per run. */
export function fileSha256(/** @type {string} */ identifier, /** @type {string} */ relPath) {
	return createHash('sha256').update(`${identifier}/${relPath}`).digest('hex');
}

/**
 * @typedef {object} FixtureSearch
 * @property {string} [q] Text the identifier, title or description holds, in any case.
 * @property {Readonly<Record<string, string>>} [labels] Labels each collection must hold exactly.
 * @property {readonly CollectionState[]} [states] By default active and incomplete.
 */

/**
 * The full identifiers a catalog search finds, as the API sorts them (by identifier): what the
 * API's search answers someone who may see every state asked for. The fixture's text is ASCII,
 * so lower case compares as the API's `casefold` does.
 * @param {string} catalog
 * @param {FixtureSearch} search
 * @returns {string[]}
 */
export function searchMatches(catalog, { q = '', labels = {}, states = ['active', 'incomplete'] }) {
	const text = q.toLowerCase();
	return COLLECTIONS.filter(
		(candidate) =>
			candidate.catalog === catalog &&
			states.includes(candidate.state) &&
			Object.entries(labels).every(([key, value]) => labelOf(candidate, key) === value) &&
			[
				collectionIdentifier(candidate),
				textOf(candidate.metadata.title),
				textOf(candidate.metadata.description)
			].some((field) => field.toLowerCase().includes(text))
	)
		.map(collectionIdentifier)
		.sort();
}

/**
 * The value of one of a collection's labels, if it has that label.
 * @param {FixtureCollection} collection
 * @param {string} key
 * @returns {unknown}
 */
function labelOf(collection, key) {
	const { labels } = collection.metadata;
	if (typeof labels !== 'object' || labels === null) return undefined;
	return Object.entries(labels).find(([name]) => name === key)?.[1];
}

/** @param {unknown} value */
function textOf(value) {
	return typeof value === 'string' ? value : '';
}

/** The organizations a user may see, by name in the API's order (sorted by name). */
export function visibleOrganizations(/** @type {Username} */ username) {
	const { groups } = USERS[username];
	if (groups.includes(PLATFORM_ADMIN_GROUP)) return ORGANIZATIONS.map(({ name }) => name).sort();
	const names = new Set(
		ORGANIZATIONS.filter(({ orgAdmins }) => orgAdmins.some((group) => groups.includes(group))).map(
			({ name }) => name
		)
	);
	for (const catalog of visibleCatalogs(username)) {
		const organization = CATALOGS.find(({ name }) => name === catalog)?.organization;
		if (organization !== undefined) names.add(organization);
	}
	return [...names].sort();
}

/** The catalogs a user may see, by name in the API's order (sorted by name). */
export function visibleCatalogs(/** @type {Username} */ username) {
	const { groups } = USERS[username];
	if (groups.includes(PLATFORM_ADMIN_GROUP)) return CATALOGS.map(({ name }) => name).sort();
	const managed = ORGANIZATIONS.filter(({ orgAdmins }) =>
		orgAdmins.some((group) => groups.includes(group))
	).map(({ name }) => name);
	return CATALOGS.filter(
		(catalog) =>
			managed.includes(catalog.organization) ||
			catalog.grants.some((grant) => grant.groups.some((group) => groups.includes(group)))
	)
		.map(({ name }) => name)
		.sort();
}
