// Throwaway API question only: no journal, scheduler, plugin import, or live HTTP.
import { tool } from "../../../.agents/node_modules/@opencode-ai/plugin/dist/tool.js";

export const profileSchema = tool.schema.enum(["preparatory", "maximum"]).optional();

/** @param {unknown} input @param {string} activity */
export function select(input, activity) {
  const profile = profileSchema.parse(input) ?? "maximum";
  if (profile === "preparatory" && ["code", "legacy-exclusive"].includes(activity)) {
    throw new Error("Preparatory cannot authorize code or unclassified work");
  }
  return profile;
}

/** @param {"implementation" | "fix" | "verification"} role @param {"preparatory" | "maximum"} profile */
export function agentFor(role, profile) {
  return `markdown-${role === "verification" ? "reviewer" : "implementer"}${profile === "maximum" ? "-max" : ""}`;
}

/** @param {unknown} value @returns {Record<string, unknown>} */
function object(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Capability unavailable");
  return /** @type {Record<string, unknown>} */ (value);
}

/** @param {unknown} agent @param {unknown} model @param {string} name @param {"preparatory" | "maximum"} profile */
export function capability(agent, model, name, profile) {
  const effort = profile === "maximum" ? "max" : "low";
  const a = object(agent);
  const m = object(a.model);
  const variant = object(object(object(model).variants)[effort]);
  if (a.name !== name || a.mode !== "subagent" || a.variant !== effort ||
      m.providerID !== "openai" || m.modelID !== "gpt-6-astra" ||
      object(a.options).reasoningEffort !== effort || variant.reasoningEffort !== effort ||
      (variant.disabled !== undefined && variant.disabled !== false)) throw new Error("Capability unavailable");
  return effort;
}

/** @param {import("../../../.agents/node_modules/@opencode-ai/sdk/dist/index.js").OpencodeClient} client @param {string} agent */
export async function submit(client, agent) {
  /** @type {NonNullable<import("../../../.agents/node_modules/@opencode-ai/sdk/dist/index.js").SessionPromptAsyncData["body"]>} */
  const body = { agent, model: { providerID: "openai", modelID: "gpt-6-astra" },
    parts: [{ type: "text", text: "Synthetic API probe, not a model assignment" }] };
  return client.session.promptAsync({ path: { id: "synthetic-child" },
    query: { directory: "/isolated/probe" }, body, throwOnError: true });
}
