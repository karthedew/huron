import { type Plugin, tool } from "@opencode-ai/plugin";

const model = { providerID: "openai", modelID: "gpt-6-astra" };
const agents = ["markdown-orchestrator", "markdown-implementer", "markdown-reviewer"];

const plugin: Plugin = async ({ client, directory }) => {
  const launching = new Set<string>();
  const query = { directory };

  async function snapshot(id: string) {
    const messages = await client.session.messages({
      path: { id }, query, throwOnError: true,
    });
    const statuses = await client.session.status({ query, throwOnError: true });
    const last = messages.data.at(-1);
    const latest = last?.info.role === "assistant" ? last : undefined;
    const info = latest?.info;
    const status = statuses.data[id] ?? { type: "idle" };
    const finished = info?.role === "assistant" && info.time.completed !== undefined &&
      (info.error !== undefined || info.finish === "stop");
    const text = latest?.parts.filter((part) => part.type === "text").map((part) => part.text).join("\n");
    const tools = latest?.parts.filter((part) => part.type === "tool").map((part) => ({
      tool: part.tool,
      status: part.state.status,
      title: "title" in part.state ? part.state.title : undefined,
      time: "time" in part.state ? part.state.time : undefined,
    }));
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
    };
  }

  return {
    "chat.params": async (input, output) => {
      if (!agents.includes(input.agent)) return;
      if (input.model.id !== model.modelID || input.model.providerID !== model.providerID) {
        throw new Error("The markdown workflow requires openai/gpt-6-astra; refusing substitution.");
      }
      output.options.reasoningEffort = "low";
    },
    tool: {
      implementation_start: tool({
        description: "Launch one Astra Low implementation/fix/review child asynchronously. Returns its session ID immediately; poll implementation_status. Refuses overlapping or indeterminate children.",
        args: {
          role: tool.schema.enum(["implementation", "fix", "verification"]),
          title: tool.schema.string().min(1),
          prompt: tool.schema.string().min(1).describe("Complete self-contained assignment, including the validation gate and 15-minute progress contract."),
        },
        async execute(args, context) {
          if (context.agent !== "markdown-orchestrator") {
            throw new Error("Only markdown-orchestrator may launch workflow children.");
          }
          if (launching.has(context.sessionID)) throw new Error("A launch is already in progress.");
          launching.add(context.sessionID);
          try {
            const children = await client.session.children({
              path: { id: context.sessionID }, query, throwOnError: true,
            });
            for (const child of children.data) {
              if (!(await snapshot(child.id)).terminal) {
                throw new Error(`Child ${child.id} is active or indeterminate; inspect it before another launch.`);
              }
            }
            const agent = args.role === "verification" ? "markdown-reviewer" : "markdown-implementer";
            const configured = await client.app.agents({ query, throwOnError: true });
            const selected = configured.data.find((item) => item.name === agent);
            if (selected?.model?.providerID !== model.providerID ||
                selected.model.modelID !== model.modelID || selected.options.reasoningEffort !== "low") {
              throw new Error(`Reload OpenCode: ${agent} must be configured for Astra Low.`);
            }
            const providers = await client.config.providers({ query, throwOnError: true });
            if (!providers.data.providers.some((provider) =>
              provider.id === model.providerID && provider.models[model.modelID])) {
              throw new Error("openai/gpt-6-astra is unavailable; no child was launched.");
            }
            const session = await client.session.create({
              query, body: { parentID: context.sessionID, title: args.title }, throwOnError: true,
            });
            const id = session.data.id;
            // Publish the ID before dispatch: an ambiguous HTTP failure must not cause a duplicate writer.
            context.metadata({ title: args.title, metadata: { sessionID: id, agent } });
            try {
              await client.session.promptAsync({
                path: { id }, query, throwOnError: true,
                body: { agent, model, parts: [{ type: "text", text: args.prompt }] },
              });
            } catch {
              return JSON.stringify({ sessionID: id, state: "dispatch-indeterminate", instruction: "Poll this session; do not launch a replacement." });
            }
            return JSON.stringify({ sessionID: id, state: "submitted", agent, model, reasoningEffort: "low" });
          } finally {
            launching.delete(context.sessionID);
          }
        },
      }),
      implementation_status: tool({
        description: "Read status, latest assistant text, tool activity and terminal evidence for a direct child. Omit sessionID to list children after an interrupted launch. Idle alone is not completion or PASS.",
        args: { sessionID: tool.schema.string().optional() },
        async execute(args, context) {
          const children = await client.session.children({
            path: { id: context.sessionID }, query, throwOnError: true,
          });
          if (!args.sessionID) {
            return JSON.stringify(children.data.map(({ id, title, time }) => ({ sessionID: id, title, time })));
          }
          if (!children.data.some((child) => child.id === args.sessionID)) {
            throw new Error("Status is restricted to direct children of the calling session.");
          }
          return JSON.stringify(await snapshot(args.sessionID));
        },
      }),
    },
  };
};

export default plugin;
