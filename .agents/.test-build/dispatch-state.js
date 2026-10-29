/// <reference types="node" />
import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, readdir, realpath, rename, unlink } from "node:fs/promises";
import { join } from "node:path";
const roles = ["implementation", "fix", "verification"];
const activities = ["code", "discovery", "planning", "prototype", "review"];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const sessionID = /^[a-zA-Z0-9_-]{1,200}$/;
const invalid = () => new Error("Invalid dispatch state or arguments; admission refused.");
function object(value, keys) {
    if (!value || typeof value !== "object" || Array.isArray(value) ||
        Object.keys(value).some(key => !keys.includes(key)))
        throw invalid();
    return value;
}
function claims(value) {
    if (!Array.isArray(value) || value.length < 1 || value.length > 32)
        throw invalid();
    const seen = new Set();
    return value.map(item => {
        const claim = object(item, ["resource", "mode"]);
        if (typeof claim.resource !== "string" || !/^(\*|[a-z][a-z0-9:._-]{0,95})$/.test(claim.resource) ||
            seen.has(claim.resource) || (claim.mode !== "read" && claim.mode !== "write"))
            throw invalid();
        seen.add(claim.resource);
        return { resource: claim.resource, mode: claim.mode };
    });
}
function classify(role, activity, resources) {
    if (typeof role !== "string" || !roles.includes(role))
        throw invalid();
    if (activity === undefined && resources === undefined) {
        return { role: role, activity: "legacy-exclusive", claims: [{ resource: "*", mode: "write" }] };
    }
    if (typeof activity !== "string" || !activities.includes(activity) ||
        ((activity === "discovery" || activity === "review") !== (role === "verification")))
        throw invalid();
    return { role: role, activity: activity, claims: claims(resources) };
}
function validateProfile(value, activity) {
    if (value !== "preparatory" && value !== "maximum")
        throw invalid();
    if (value === "preparatory" && (activity === "code" || activity === "legacy-exclusive"))
        throw invalid();
    return value;
}
export function normalizeDispatch(value) {
    const args = object(value, ["role", "title", "prompt", "activity", "claims", "profile"]);
    if (typeof args.title !== "string" || !args.title.trim() ||
        typeof args.prompt !== "string" || !args.prompt.trim())
        throw invalid();
    const classification = classify(args.role, args.activity, args.claims);
    const profile = validateProfile(args.profile === undefined ? "maximum" : args.profile, classification.activity);
    return { ...classification, profile, title: args.title.trim(), prompt: args.prompt };
}
export function claimsConflict(left, right) {
    if ([left.activity, right.activity].some(activity => activity === "code" || activity === "legacy-exclusive"))
        return true;
    return left.claims.some(a => right.claims.some(b => (a.resource === b.resource || a.resource === "*" || b.resource === "*") &&
        (a.mode === "write" || b.mode === "write")));
}
function validateRecords(value, worktree) {
    const ledger = object(value, ["version", "worktree", "records"]);
    if (ledger.version !== 1 || ledger.worktree !== worktree || !Array.isArray(ledger.records))
        throw invalid();
    const dispatches = new Set();
    const children = new Set();
    return ledger.records.map(value => {
        const record = object(value, ["version", "dispatchID", "worktree", "parentID", "childID", "role", "activity", "claims", "createdAt", "state", "profile"]);
        if ((record.version !== 1 && record.version !== 2) || record.worktree !== worktree ||
            typeof record.dispatchID !== "string" || !uuid.test(record.dispatchID) || dispatches.has(record.dispatchID) ||
            typeof record.parentID !== "string" || !sessionID.test(record.parentID) ||
            typeof record.createdAt !== "string" || !Number.isFinite(Date.parse(record.createdAt)) ||
            new Date(record.createdAt).toISOString() !== record.createdAt ||
            typeof record.state !== "string" || !["creating", "dispatching", "submitted"].includes(record.state))
            throw invalid();
        if (record.state === "creating") {
            if ("childID" in record)
                throw invalid();
        }
        else {
            if (typeof record.childID !== "string" || !sessionID.test(record.childID) || children.has(record.childID))
                throw invalid();
            children.add(record.childID);
        }
        const normalized = record.activity === "legacy-exclusive"
            ? classify(record.role, undefined, undefined) : classify(record.role, record.activity, record.claims);
        if (JSON.stringify(claims(record.claims)) !== JSON.stringify(normalized.claims))
            throw invalid();
        if (record.version === 1) {
            if ("profile" in record)
                throw invalid();
        }
        else {
            validateProfile(record.profile, normalized.activity);
        }
        dispatches.add(record.dispatchID);
        return { ...record, ...normalized };
    });
}
function isMissing(error) {
    return error.code === "ENOENT";
}
async function checkPath(path, directory, privateMode = true) {
    const stat = await lstat(path);
    if (stat.isSymbolicLink() || (directory ? !stat.isDirectory() : !stat.isFile()) ||
        (process.getuid && stat.uid !== process.getuid()) ||
        (privateMode && (stat.mode & 0o777) !== (directory ? 0o700 : 0o600)) ||
        (!directory && stat.nlink !== 1))
        throw invalid();
}
async function readPrivate(path) {
    await checkPath(path, false);
    const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
        return JSON.parse(await file.readFile("utf8"));
    }
    finally {
        await file.close();
    }
}
async function syncDirectory(path) {
    const handle = await open(path, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try {
        await handle.sync();
    }
    finally {
        await handle.close();
    }
}
/** Local cooperative admission; abandoned state requires human-authorized reconciliation. */
export class DispatchJournal {
    worktree;
    root;
    token;
    constructor(worktree, root) {
        this.worktree = worktree;
        this.root = root;
    }
    static async at(worktree) {
        const canonical = await realpath(worktree);
        const agents = join(canonical, ".agents");
        await checkPath(agents, true, false);
        return new DispatchJournal(canonical, join(agents, ".dispatch-state"));
    }
    async prepare(create) {
        await checkPath(join(this.worktree, ".agents"), true, false);
        if (create) {
            try {
                await mkdir(this.root, { mode: 0o700 });
                await syncDirectory(join(this.worktree, ".agents"));
            }
            catch (error) {
                if (error.code !== "EEXIST")
                    throw error;
            }
        }
        await checkPath(this.root, true);
    }
    async readRecords() {
        try {
            await this.prepare(false);
        }
        catch (error) {
            if (isMissing(error))
                return [];
            throw invalid();
        }
        const entries = await readdir(this.root);
        if (entries.some(name => name !== "ledger.json" && name !== "admission.lock"))
            throw invalid();
        try {
            return validateRecords(await readPrivate(join(this.root, "ledger.json")), this.worktree);
        }
        catch (error) {
            if (isMissing(error))
                return [];
            throw invalid();
        }
    }
    async assertOwner() {
        await this.prepare(false);
        const owner = object(await readPrivate(join(this.root, "admission.lock")), ["version", "token", "startedAt"]);
        if (!this.token || owner.version !== 1 || owner.token !== this.token ||
            typeof owner.startedAt !== "string" || !Number.isFinite(Date.parse(owner.startedAt)) ||
            new Date(owner.startedAt).toISOString() !== owner.startedAt)
            throw invalid();
    }
    async saveRecords(records) {
        await this.assertOwner();
        const ledger = { version: 1, worktree: this.worktree, records };
        validateRecords(ledger, this.worktree);
        // Validate existing artifacts before replacing anything. Never clean another invocation's temp file.
        await this.readRecords();
        const temporary = join(this.root, `ledger-${randomUUID()}.tmp`);
        const file = await open(temporary, "wx", 0o600);
        try {
            await file.writeFile(JSON.stringify(ledger));
            await file.sync();
        }
        finally {
            await file.close();
        }
        await this.assertOwner();
        await rename(temporary, join(this.root, "ledger.json"));
        await syncDirectory(this.root);
    }
    async withAdmission(action) {
        await this.prepare(true);
        const path = join(this.root, "admission.lock");
        let file;
        try {
            file = await open(path, "wx", 0o600);
        }
        catch (error) {
            if (error.code === "EEXIST")
                throw new Error("admission-busy: a launch is already in progress or requires manual reconciliation.");
            throw invalid();
        }
        const token = randomUUID();
        try {
            await file.writeFile(JSON.stringify({ version: 1, token, startedAt: new Date().toISOString() }));
            await file.sync();
        }
        finally {
            await file.close();
        }
        // A failed lock write deliberately leaves an unowned lock, never a claim of safe recovery.
        this.token = token;
        try {
            await syncDirectory(this.root);
            await this.readRecords();
            return await action(this);
        }
        finally {
            try {
                await this.assertOwner();
                await unlink(path);
                await syncDirectory(this.root);
            }
            finally {
                this.token = undefined;
            }
        }
    }
}
