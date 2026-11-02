# Markdown implementation workflow

OpenCode's `/implement-markdown PLAN.md` wrapper reads the shared workflow in
`../.claude/commands/implement-markdown.md`. The shared command requires Astra with
Medium reasoning for every role. OpenCode uses the three dedicated
`markdown-*` agents in `../opencode.json`, all on `openai/gpt-6-astra` with medium
reasoning effort. Other agents and commands are not changed.

## Setup

Run `npm ci --ignore-scripts` from `.opencode/`, then quit and restart OpenCode.
The local plugin is loaded at startup. The OpenAI provider must already have
access to `gpt-6-astra`; this project does not install credentials or substitute
another model. Inspect configuration with `opencode debug agent markdown-orchestrator`
and the corresponding implementer/reviewer names.

## Polling

- `implementation_start(role, title, prompt)` creates one child of the current
  orchestrator and submits the complete assignment asynchronously. Roles are
  `implementation`, `fix`, and `verification`. Record its `sessionID` immediately.
- `implementation_status(sessionID)` returns observed session state, recent
  assistant text, tool names/status/timestamps, and terminal-response evidence.
  It does not return reasoning parts or raw tool inputs/outputs. Assistant text
  and tool titles are still project-sensitive and should not contain credentials.
- Omit `sessionID` to discover children after an interrupted launch. Polling is
  restricted to the caller's direct children. The SDK uses the current server
  client and workspace, not a guessed localhost port or a second server.
- Poll at least once per minute with bounded waits, and relay a brief update to
  the user at least every 15 minutes. Polling tools are not an autonomous timer:
  the orchestrator must keep polling rather than finish its turn or block on Task.
- `idle` alone is not completion. Missing response evidence and ambiguous dispatch
  remain indeterminate and prevent another launch, including after plugin reload.
  Errors and final responses are not automatic PASS verdicts. The orchestrator
  must inspect results and any surviving processes before replacement after errors.
- Verification agents cannot use the edit tool or launch nested tasks. Shell
  checks retain existing permissions; this is not an OS-level read-only sandbox.

The plugin does not abort, delete, or restart sessions, weaken permissions, or
change validation gates. If a child is indeterminate, inspect it in OpenCode and
resolve its state explicitly; do not delete it to evade serial execution.

## Validation

From `.opencode/`:

```sh
npm run check
npm test
```

Tests use the real SDK against a simulated HTTP boundary; they make no model calls.
They prove dispatch payloads, progress visibility, model enforcement, serial
exclusion, dispatch-error recovery, and parent isolation. A live model run is a
separate smoke test and consumes provider quota.

References: [configuration schema](https://opencode.ai/config.json),
[plugins](https://opencode.ai/docs/plugins/), and
[asynchronous prompts and session status](https://opencode.ai/docs/server/).
