# Rendering probe

**Synthetic rendering fixture, not a product guide.** All content on this site is
an isolated copied corpus. It does not deliver Huron's MVP.

[ADR title anchor](adr/0001-controller-generation-is-the-verification-epoch.md#controller-generation-is-the-verification-epoch)
and [history authority](history.md#domain-owned-core) must remain reachable offline.
See the [Raw target](../design/raw-first.md#releases-and-pushes) and
[vocabulary](../CONTEXT.md#language). [Reference link][history] also resolves.

![Synthetic local release diagram](diagram.svg)

:::note[Read-only example]
This is a supported note, not a persisted application operation.
:::

:::tip[Keyboard tip]
Use Tab to reach links and Escape to close search.
:::

:::caution[Target, not current]
The full independent-copy release is a target scientific contract.
:::

:::danger[Do not run examples against real data]
This corpus makes no authorization or backend durability claim.
:::

## Duplicate heading

The first occurrence gets the unsuffixed anchor.

## Duplicate heading

The second occurrence gets the -1 suffix. [Second](#duplicate-heading-1).

<a id="explicit-contract"></a>

## Explicit anchor

[Explicit](#explicit-contract), [first H1](#rendering-probe) and a footnote[^stable].

## Literal examples

```python
payload = {"url": "[not a link](missing.md#absent)", "braces": {"a": 1}}
print(payload)
```

~~~text
!!! unsupported "This is literal code, not an aside"
:::unknown[Also literal]
[still not a link](../../roadmap/private-plan.md)
<a href="missing.html">literal HTML</a>
~~~

## Long content

Release_identifier_0123456789_abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789_abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789_abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ

| Identifier | Input checksum | Output checksum | Publication |
| --- | --- | --- | --- |
| release_abcdefghijklmnopqrstuvwxyz_0123456789_abcdefghijklmnopqrstuvwxyz_0123456789 | 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef | fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210 | Independent immutable copy |

```sh
synthetic_example --identifier release_abcdefghijklmnopqrstuvwxyz_0123456789_abcdefghijklmnopqrstuvwxyz_0123456789 --checksum 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef --no-execution
```

[^stable]: A footnote preserves navigation back to its reference.

[history]: history.md#domain-owned-core "Historical receipts"
