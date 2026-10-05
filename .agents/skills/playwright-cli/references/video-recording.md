# Record visual evidence

Adapted from Playwright 1.62.1; see [provenance](../PROVENANCE.md).
Open an owned session first, then from `web/`:

```sh
npx --no-install playwright cli -s=huron-qa-slice video-start .playwright-cli/qa-flow.webm
npx --no-install playwright cli -s=huron-qa-slice video-chapter "Keyboard flow" --description="Focus and activation" --duration=2000
npx --no-install playwright cli -s=huron-qa-slice press Tab
npx --no-install playwright cli -s=huron-qa-slice video-stop
```

Record the whole relevant flow with a descriptive filename. Video captures
appearance over time; traces add DOM/network evidence and screenshots capture a
specific viewport/theme. Record actual viewport/theme alongside the video. Keep
artifacts ignored and avoid exposing sensitive content. Recording adds overhead;
do not infer performance measurements from an instrumented demo alone.
