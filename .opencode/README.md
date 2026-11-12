# OpenCode local state

The workflow assets moved to [`.agents/`](../.agents/README.md).
[The root configuration](../opencode.json) registers the canonical plugin and commands.
Run setup and checks from `.agents/` as its README describes.

Do not restore the old dispatcher or lifecycle commands here.
OpenCode automatically loads plugins and commands from this directory.
Legacy copies can override the canonical definitions on every restart.

OpenCode may keep its generated dependency files here.
Those files do not replace the dependency setup in `.agents/`.
