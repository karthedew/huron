# How search works

A Huron search matches a text in the identifier, the title and the description of each collection
in one catalog. Label filters must equal the `labels` in the metadata exactly. By default, a search
finds active and incomplete collections. The service sorts the results by identifier and sends one
page at a time. You find only what your roles let you read. The CLI searches one catalog, and the
web searches one catalog or one organization.

## The path of a search

The service has one search operation: `GET /api/v1/catalogs/{catalog}/search`. The CLI and the web
both use it. The web makes one request for each catalog of an organization.

```text
  huron search             web Search page
  (one catalog)            (one catalog, or one organization)
       |                        |
       |                        | organization: one request per
       |                        | catalog, 4 at a time, 8 s in all
       v                        v
  +-------------------------------------------+
  | API: GET /api/v1/catalogs/{c}/search      |
  |  1. find the catalog (your roles)         |
  |  2. remove "draft" if you cannot see it   |
  |  3. compare text, labels and states       |
  |  4. sort by identifier, return one page   |
  +-------------------------------------------+
                    |
                    v
          PostgreSQL: the collections table
```

Each result is one collection, with the same fields that the API returns for one collection. A
search never returns a namespace, a catalog or a file.

## The search text

The text (`-q` in the CLI, `q` in the API) matches a collection when one of these fields holds it:

- the identifier, for example `heliophysics.solar-wind.run7`.
- the `title` in the metadata.
- the `description` in the metadata.

The field must hold the full text in one piece. The service ignores the difference between upper
case and lower case letters. It does not split the text into words. Thus `solar run7` does not match
`solar-wind.run7`. The text has no wildcards: `%`, `_` and `*` match only themselves.

The identifier starts with the name of the catalog. Thus a text that is part of the catalog name
matches each collection in the catalog. The API accepts a text of at most 200 characters. A longer
text gets the error `REQUEST_INVALID`.

## Label filters

A label filter has the form `key=value` (`-l` in the CLI, `label` in the API). The service also
accepts `key:value`. A filter without `=` or `:`, or with an empty key, gets the error
`REQUEST_INVALID`.

A collection passes a filter when the `labels` object of its metadata holds the key with exactly
that value. The comparison includes case and spaces. A collection must pass all the filters of a
search. Give each key only one time. With two values for one key, the service uses only the last
value. The web finds nothing for such a search.

## States

A collection is in one of three states:

- `draft`: Huron reserved the name, but the collection has no directory yet.
- `active`: the collection has a directory, and its metadata satisfies the schema.
- `incomplete`: the collection has a directory, but its metadata does not satisfy the current
  schema of the catalog.

Without `--state`, a search finds active and incomplete collections. Each `--state` that you give
names one state to include, and the search then finds only those states. For example,
`huron search --state draft` finds only drafts. Another value gets the error `REQUEST_INVALID`.

## Order and pages

The service sorts the results by identifier. It does not rank them by how well they match. It sends
100 results on a page by default. A request can ask for 1 to 500 with `limit`. Each page has a
`next_cursor` when more results follow. The next request sends that value as `cursor`.

A cursor continues a search. It does not preserve a snapshot of the results. Collections can
change between requests. Keep the same text, labels and states when you request the next page.

## Who finds what

Search uses the same roles as the rest of Huron. The roles belong to LDAP groups. See
[Who has access](../user-guide.md#who-has-access). These rules apply:

- You can search a catalog when you hold a role in it, in its organization or on the platform.
  Otherwise the service answers `NOT_FOUND`, the same answer as for a catalog that does not exist.
- Each role in the catalog finds all its active and incomplete collections.
- Only Contributors, Catalog Admins, Org Admins and Platform Admins find drafts. When a Reader
  asks for drafts, the service removes `draft` from the search without an error. Thus
  `--state draft` finds nothing for a Reader.

## Search from the CLI

`huron search` searches the current catalog. To search another catalog, put `--catalog <name>`
before the command. Without a current catalog, the command stops with exit code 2.

```bash
huron search -q parker                 # text
huron search -l site=a -l mission=ace  # two label filters
huron search -q run --state draft      # drafts only
huron --catalog geoscience search -q core
```

The CLI reads all the pages. By default, it prints all the results in one table. The columns are
`COLLECTION`, `STATE`, `VERSION`, `FILES` and `TITLE`. Without `-q`, `-l` or `--state`, the command
shows all the active and incomplete collections of the catalog.

Two other commands list collections:

- `huron get collections`, without a namespace, uses the same search with all three states and no
  filters. It lists each collection of the catalog that you can see. With a namespace, it lists the
  collections directly in that namespace.
- `huron tree` does not search. It reads each namespace of the catalog and shows its collections
  as leaves, with their states.

The options are in the CLI reference for [huron search](/docs/reference/cli/search/),
[huron get collections](/docs/reference/cli/get/#huron-get-collections) and
[huron tree](/docs/reference/cli/tree/).

## Search in the web

The web has one Search page. The search box at the top of each page opens it with your text. On
the Search page, you select an organization, and then a catalog or all the catalogs of that
organization. The form has a text field, label filters and the states. The form offers drafts
only when you may see drafts in the catalog, or in one catalog of the organization.

When you do not select an organization, the page uses one of these, in this order:

1. The organization of the catalog in the address.
2. The last organization that you used in this browser, when you can still see it.
3. The first organization that you can see.

A search of one catalog shows 25 results on a page, with a link to the next page. It also shows the
`huron search` command for the same search. A label on a result can be a link that adds
that label as a filter.

The web checks these limits before it searches:

| Input | Maximum |
| --- | --- |
| Search text | 200 characters |
| Label filters | 10 |
| Each label key and value | 100 characters each |

The web removes spaces at the start and end of the search text. It keeps spaces in label keys and
values. An invalid filter shows an error instead of sending the search to the API.

The web adds an exact match at the top of the first page. This occurs when the text is the
identifier of a collection, with or without the catalog name. The collection must also pass the
label and state filters. When a search finds nothing, the page offers to remove each filter. For a
text of more than one word, it also offers to search for one word of the text.

## Organization search in the web

The API has no search across catalogs. Thus the web sends the same search to each catalog of the
organization and shows the results catalog by catalog. These limits apply:

| Limit | Value |
| --- | --- |
| Catalogs that the search includes | the first 50 that you can see, by name |
| Results from each catalog | the first 5 |
| Requests at the same time | 4 |
| Time for all the catalogs together | 8 seconds |

Each catalog with results shows a link to the search of that catalog only. That search shows all
its results. When the organization has more than 50 catalogs, the page says so. An organization
search with no text, no label filters and the default states sends nothing.

The web makes these changes for each catalog:

- It asks for drafts only in the catalogs where you may see them.
- It does not search a catalog when the search asks only for drafts and you may not see drafts
  there. The page names these catalogs.
- It shows an exact match only when the text is a full identifier, with the catalog name.

At 8 seconds, the web stops the requests that did not finish. The page shows the results that
arrived in time. It names each catalog that did not answer in time, with a link to the search of
that catalog. A catalog that failed shows "Couldn't search this catalog." The other catalogs still
show their results.

## What search does not do

- It does not search the contents of files, or the names and paths of files. Use
  `huron get files <collection>` for the list of the files of one collection.
- It does not compare the text with other metadata fields, for example `keywords`, `instrument` or
  `campaign`. Only labels filter by metadata values.
- It does not find namespaces or catalogs. To list them, use `huron get namespaces` and
  `huron get catalogs`.
- It does not search across organizations. The CLI and the API search one catalog. The web
  searches one catalog or one organization.
- It does not match words one by one, and it has no wildcards, no fuzzy match and no ranking.

## Related pages

- [Finding things](../user-guide.md#finding-things) in the user guide.
- [In a browser](../user-guide.md#in-a-browser) in the user guide.
- [Who has access](../user-guide.md#who-has-access) in the user guide.
- [huron search](/docs/reference/cli/search/) in the CLI reference.
- [API error codes](../api-errors.md).
- [Labels and search](metadata-and-schemas.md#labels-and-search) in Metadata and schemas.
- [What you can see](access-and-roles.md#what-you-can-see) in Access and roles.
