---
title: Getting started
description: The first steps with the huron CLI, each linking to where the guides explain it.
---

The `huron` CLI catalogs, organizes and pushes data on the share. The web shows the same catalog,
read-only. These steps follow the [user guide](/docs/guides/user-guide/), which explains each step.
Its [glossary](/docs/guides/user-guide/#glossary) defines the Huron terms. To learn the model of
Huron first, read [How Huron works](/docs/concepts/how-huron-works/).

1. **Log in.** Set the address of your service in the CLI configuration, then log in:
   [Logging in](/docs/guides/user-guide/#logging-in), and the reference of
   [`huron config`](/docs/reference/cli/config/) and [`huron login`](/docs/reference/cli/login/).
2. **Find your way.** Select the current organization and catalog, and look around:
   [Finding your way](/docs/guides/user-guide/#finding-your-way), with
   [`huron org`](/docs/reference/cli/org/), [`huron catalog`](/docs/reference/cli/catalog/) and
   [`huron tree`](/docs/reference/cli/tree/).
3. **Select a collection** or create one:
   [Creating a collection](/docs/guides/user-guide/#creating-a-collection) and
   [`huron checkout`](/docs/reference/cli/checkout/).
4. **Add files and push them:**
   [Staging and pushing files](/docs/guides/user-guide/#staging-and-pushing-files), with
   [`huron add`](/docs/reference/cli/add/), [`huron status`](/docs/reference/cli/status/) and
   [`huron push`](/docs/reference/cli/push/). [How raw ingest works](/docs/concepts/raw-ingest/)
   explains each step of a push.
5. **Edit metadata:** [Editing metadata](/docs/guides/user-guide/#editing-metadata).
   [Metadata and schemas](/docs/concepts/metadata-and-schemas/) explains the schemas.

When a command fails, its `error:` line names a code. [API error codes](/docs/guides/api-errors/)
explains each code. The user guide lists the [exit codes](/docs/guides/user-guide/#exit-codes).

Running the service? Start with [Administration](/docs/administration/prerequisites/).
