# Preserved first-run failure

`qualification-01` exited 1 at its first copied-server editable install. Its 190
commands include 189 zero exits and the final nonzero installer result. No timeout
or surviving owned process group was recorded. Both repository preservation
manifests match the original source and index fingerprints.

The private wheelhouse omitted the dynamic PEP 660 build requirement
`editables~=0.3`. Hatchling 1.32.4's installed `get_requires_for_build_editable`
implementation adds it unconditionally. This is a probe-input defect, not evidence
against either namespace layout. No fallback, legacy installer or forced install
was used. The exact failure is retained in
[the installer log](runs/qualification-01/logs/190-editable-current-server-sdk-install-server.log).

Before the correction, driver SHA-256 values were:

| File | SHA-256 |
| --- | --- |
| `probe.py` | `cc9f379c819c0ce0f78dfb715c1252b215fa77c372d5a8c39afb61666b4dc0f9` |
| `runtime_check.py` | `ce3757d9123a73b24070566c0a924c234fd145bbe29f0a49b83b43b4fadc58ed` |
| `closure_check.py` | `3a0d479a59af66c8d9b03e922c029059aa6451ac488b2de0aa616c7ebf11d618` |
| `build-extras.json` | `3ae4864966d742492cc012722abe34f0213c14a01ab8cecf924e1ac3524788c6` |

The failed run retains its complete server and SDK build inputs, 3 wheels, private
environments/cache, dependency hashes, 34 completed observations and 391 SDK
behavior outcomes. Subsequent runs additionally save exact driver copies/hashes.
The correction adds the non-yanked, hash-pinned `editables==0.5` build input and
checks the actual dynamic build requirement. It changes neither SDK behavior nor
namespace assertions. The original run is never reused or cleared.
