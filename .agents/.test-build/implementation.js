import { tool } from "@opencode-ai/plugin";
import { randomUUID } from "node:crypto";
import { DispatchJournal, claimsConflict, normalizeDispatch } from "./dispatch-state.js";
const model = { providerID: "openai", modelID: "gpt-6-astra" };
const efforts = {
    "markdown-orchestrator": "low", "markdown-implementer": "low", "markdown-reviewer": "low",
    "markdown-implementer-max": "max", "markdown-reviewer-max": "max",
};
function selection(role, profile) {
    const base = role === "verification" ? "markdown-reviewer" : "markdown-implementer";
    return { profile, agent: profile === "maximum" ? `${base}-max` : base,
        model: "openai/gpt-6-astra", reasoningEffort: profile === "maximum" ? "max" : "low" };
}
function field(value, key) {
    return value !== null && typeof value === "object" && !Array.isArray(value) && key in value
        ? Reflect.get(value, key) : undefined;
}
const plugin = async ({ client, directory, worktree }) => {
    const query = { directory };
    const request = () => ({ query, throwOnError: true, signal: AbortSignal.timeout(30000) });
    async function safeRead(read, message) {
        try {
            return await read();
        }
        catch {
            throw new Error(message);
        } // SDK messages and causes can contain private response bodies.
    }
    async function snapshot(id) {
        const messages = await safeRead(() => client.session.messages({
            ...request(), path: { id }, query: { ...query, limit: 100 },
        }), "Unable to read workflow messages; status is indeterminate.");
        const statuses = await safeRead(() => client.session.status(request()), "Unable to read workflow status; status is indeterminate.");
        const last = messages.data.at(-1);
        const latest = last?.info.role === "assistant" ? last : undefined;
        const info = latest?.info;
        const rawStatus = statuses.data[id] ?? { type: "idle" };
        const status = rawStatus.type === "retry"
            ? { type: rawStatus.type, attempt: rawStatus.attempt, next: rawStatus.next } : { type: rawStatus.type };
        const finished = info?.role === "assistant" && info.time.completed !== undefined &&
            (info.error !== undefined || info.finish === "stop");
        const text = latest?.parts.filter((part) => part.type === "text").map((part) => part.text).join("\n");
        const tools = latest?.parts.filter((part) => part.type === "tool").map((part) => ({
            tool: part.tool,
            status: part.state.status,
            time: "time" in part.state ? { start: part.state.time.start, end: "end" in part.state.time ? part.state.time.end : undefined } : undefined,
        }));
        const window = messages.data.slice(-100);
        let progress = null;
        const recentTools = [];
        for (const message of window) {
            if (message.info.role !== "assistant")
                continue;
            const meaningful = message.parts.filter(part => part.type === "text").map(part => part.text).join("\n");
            if (meaningful.trim())
                progress = {
                    messageID: message.info.id, createdAt: message.info.time.created,
                    text: meaningful.slice(0, 4000), truncated: meaningful.length > 4000,
                };
            for (const part of message.parts) {
                if (part.type !== "tool")
                    continue;
                recentTools.push({ messageID: message.info.id, partID: part.id, tool: part.tool,
                    status: part.state.status,
                    start: "time" in part.state ? part.state.time.start : undefined,
                    end: "time" in part.state && "end" in part.state.time ? part.state.time.end : undefined });
            }
        }
        return {
            sessionID: id,
            observedAt: new Date().toISOString(),
            status,
            terminal: status.type === "idle" && Boolean(finished),
            lastMessageAt: info?.time.created,
            completedAt: info?.role === "assistant" ? info.time.completed : undefined,
            error: info?.role === "assistant" ? info.error?.name : undefined,
            model: info?.role === "assistant" ? `${info.providerID}/${info.modelID}` : undefined,
            text,
            tools,
            progress,
            recentTools: recentTools.slice(-20),
            windowMessages: 100,
            observedMessages: window.length,
        };
    }
    async function configuredAgent(role, profile) {
        const configuredSelection = selection(role, profile);
        const { agent, reasoningEffort } = configuredSelection;
        const configured = await safeRead(() => client.app.agents(request()), "Unable to verify workflow agent configuration; no child was launched.");
        const selected = configured.data.find(item => item.name === agent);
        if (selected?.model?.providerID !== model.providerID ||
            selected.model.modelID !== model.modelID || selected.mode !== "subagent" ||
            field(selected, "variant") !== reasoningEffort || field(selected.options, "reasoningEffort") !== reasoningEffort) {
            throw new Error(`Reload OpenCode: ${agent} must match its fixed Astra profile.`);
        }
        const providers = await safeRead(() => client.config.providers(request()), "Unable to verify workflow model availability; no child was launched.");
        const registered = providers.data.providers.find(provider => provider.id === model.providerID)?.models[model.modelID];
        if (!registered) {
            throw new Error("openai/gpt-6-astra is unavailable; no child was launched.");
        }
        const variant = field(field(registered, "variants"), reasoningEffort);
        const disabled = field(variant, "disabled");
        if (field(variant, "reasoningEffort") !== reasoningEffort || (disabled !== undefined && disabled !== false)) {
            throw new Error("Required Astra variant mapping is unavailable; no child was launched.");
        }
        return configuredSelection;
    }
    async function reconcile(records, parentID, proposed) {
        const blocked = () => new Error("Work is active or indeterminate; reconcile children and owned processes before another launch.");
        try {
            const known = new Map(records.filter(record => record.childID).map(record => [record.childID, record]));
            const observed = new Map();
            const observe = (id, parent) => {
                if (observed.has(id) && observed.get(id) !== parent)
                    throw blocked();
                observed.set(id, parent);
            };
            for (const parent of new Set([parentID, ...records.map(record => record.parentID)])) {
                const children = await client.session.children({ ...request(), path: { id: parent } });
                for (const child of children.data) {
                    if (child.parentID !== parent)
                        throw blocked();
                    observe(child.id, parent);
                }
            }
            const listed = await client.session.list(request());
            for (const child of listed.data)
                if (child.parentID) {
                    observe(child.id, child.parentID);
                }
            for (const record of records) {
                if (!record.childID || record.state === "creating")
                    throw blocked();
                const child = await client.session.get({ ...request(), path: { id: record.childID } });
                if (child.data.id !== record.childID || child.data.parentID !== record.parentID)
                    throw blocked();
                observe(record.childID, record.parentID);
            }
            for (const [id, parent] of observed) {
                const record = known.get(id);
                if (record && record.parentID !== parent)
                    throw blocked();
                if ((await snapshot(id)).terminal)
                    continue;
                if (!record || record.state !== "submitted" || claimsConflict(record, proposed))
                    throw blocked();
            }
        }
        catch {
            throw blocked();
        } // Never expose other parents' identities, claims or raw API errors.
    }
    function ownership(records, id, parentID) {
        const record = records.find(record => record.childID === id && record.parentID === parentID);
        return record ? { dispatchID: record.dispatchID, activity: record.activity, claims: record.claims, state: record.state,
            profile: record.version === 2 ? record.profile : "not-recorded",
            configured: record.version === 2 ? selection(record.role, record.profile) : null } : "unknown";
    }
    return {
        config: async (config) => {
            // Retire inherited competing workflows in this project without editing home config.
            delete config.command?.["architectural-review"];
            delete config.command?.["execute_plan"];
        },
        "chat.params": async (input, output) => {
            if (!Object.hasOwn(efforts, input.agent))
                return;
            if (input.model.id !== model.modelID || input.model.providerID !== model.providerID) {
                throw new Error("The markdown workflow requires openai/gpt-6-astra; refusing substitution.");
            }
            output.options.reasoningEffort = efforts[input.agent];
        },
        tool: {
            implementation_start: tool({
                description: "Launch an Astra child with preparatory (Low) or maximum (Max) profile; omission defaults to maximum. Code and legacy-exclusive require maximum. Final complete qualification must explicitly use maximum. Code is exclusive; non-code overlaps only with nonconflicting claims. Poll implementation_status.",
                args: {
                    role: tool.schema.enum(["implementation", "fix", "verification"]),
                    title: tool.schema.string().min(1),
                    prompt: tool.schema.string().min(1).describe("Complete self-contained assignment, including the validation gate and 15-minute progress contract."),
                    activity: tool.schema.enum(["code", "discovery", "planning", "prototype", "review"]).optional(),
                    profile: tool.schema.enum(["preparatory", "maximum"]).optional(),
                    claims: tool.schema.array(tool.schema.object({ resource: tool.schema.string().regex(/^(\*|[a-z][a-z0-9:._-]{0,95})$/), mode: tool.schema.enum(["read", "write"]) }).strict()).min(1).max(32).optional(),
                },
                async execute(args, context) {
                    if (context.agent !== "markdown-orchestrator") {
                        throw new Error("Only markdown-orchestrator may launch workflow children.");
                    }
                    const normalized = normalizeDispatch(args);
                    const journal = await DispatchJournal.at(worktree);
                    const configured = await configuredAgent(normalized.role, normalized.profile);
                    const { agent } = configured;
                    return journal.withAdmission(async (journal) => {
                        const records = await journal.readRecords();
                        await reconcile(records, context.sessionID, normalized);
                        const record = {
                            version: 2, profile: normalized.profile, dispatchID: randomUUID(), worktree: journal.worktree, parentID: context.sessionID,
                            role: normalized.role, activity: normalized.activity, claims: normalized.claims,
                            createdAt: new Date().toISOString(), state: "creating",
                        };
                        records.push(record);
                        await journal.saveRecords(records);
                        try {
                            const session = await client.session.create({ ...request(),
                                body: { parentID: context.sessionID, title: normalized.title } });
                            record.childID = session.data.id;
                            record.state = "dispatching";
                            context.metadata({ title: normalized.title, metadata: { sessionID: record.childID, dispatchID: record.dispatchID, agent, profile: normalized.profile } });
                            await journal.saveRecords(records);
                            await client.session.promptAsync({
                                ...request(), path: { id: record.childID },
                                body: { agent, model, parts: [
                                        { type: "text", text: `HURON_DISPATCH_V2\n${JSON.stringify(record)}\nDeclared claims are cooperative coordination, not permissions. Do not escalate activity or profile, or resume without parent reconciliation. Never put credentials in progress.` },
                                        { type: "text", text: normalized.prompt },
                                    ] },
                            });
                            record.state = "submitted";
                            await journal.saveRecords(records);
                        }
                        catch {
                            return JSON.stringify({ dispatchID: record.dispatchID, sessionID: record.childID,
                                configured, providerAcceptance: "not-proven",
                                state: record.childID ? "dispatch-indeterminate" : "creation-indeterminate",
                                instruction: "Inspect existing children and owned processes; never replay or launch a replacement automatically." });
                        }
                        return JSON.stringify({ sessionID: record.childID, dispatchID: record.dispatchID,
                            activity: record.activity, claims: record.claims, state: "submitted", agent, model,
                            configured, providerAcceptance: "not-proven" });
                    });
                },
            }),
            implementation_status: tool({
                description: "Read status, latest assistant text, tool activity and terminal evidence for a direct child. Omit sessionID to list children after an interrupted launch. Idle alone is not completion or PASS.",
                args: { sessionID: tool.schema.string().optional() },
                async execute(args, context) {
                    const children = await safeRead(() => client.session.children({
                        ...request(), path: { id: context.sessionID },
                    }), "Unable to read workflow children; status is indeterminate.");
                    const journal = await DispatchJournal.at(worktree);
                    const records = await journal.readRecords();
                    if (!args.sessionID)
                        return JSON.stringify(children.data.map(({ id, time }) => ({ sessionID: id, time, ownership: ownership(records, id, context.sessionID) })));
                    if (!children.data.some((child) => child.id === args.sessionID)) {
                        throw new Error("Status is restricted to direct children of the calling session.");
                    }
                    return JSON.stringify({ ...await snapshot(args.sessionID), ownership: ownership(records, args.sessionID, context.sessionID),
                        providerAcceptance: "not-proven" });
                },
            }),
        },
    };
};
export default plugin;
