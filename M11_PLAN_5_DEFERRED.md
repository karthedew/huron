# M11 plan 5: deferred work

Read [M11_PLANS.md](M11_PLANS.md) first. This file is a backlog. Do not execute it with
`/implement-markdown`. Each item names the risk that stays open and the event that makes the item
necessary. The full design of each item is in `IMPLEMENTATION_PLAN_LATEST.md` at the place given.

| Item | Risk that stays open without it | Do it when | Design |
| --- | --- | --- | --- |
| Fenced writer with manual handover | A delayed NFS call from a dead writer can run after a new writer starts. Two writable pods corrupt the journal | A second replica is needed, or the platform cannot guarantee one pod | Section 3.4, P04, P16 |
| Quotas for each catalog and each principal | One user can fill the staged-byte limit for all users | The upload route becomes reachable from the internet, or a user fills the limit | Section 3.2, P10, P21 |
| Rate limits on the upload route | A client with a valid token can flood creation requests | The upload route becomes reachable from the internet | Not in the old design. Use nginx `limit_req` |
| Recovery binding of local state to an instance and a subject | A pending commit is sent again to the endpoint that the configuration names now | A second instance exists (staging), or an endpoint moves | Section 3.5 "Recovery namespace" |
| Approved destinations and credential provenance | A changed API URL receives the saved token | Users connect to more than one instance | Section 3.5, P23, P27b |
| `huron context accept-endpoint` and the new development login | None while one endpoint exists | With the two items above | Section 3.5, P27b |
| Private copy of each staged file | A change that keeps the size and the modification time is found only by the server hash, after the transfer | Users stage files that instruments still write | Section 3.5, P24 |
| Name tombstones after a delete | A new collection can adopt a directory that a delete left | A delete leaves directories in practice | Section 3.4, P20 |
| A metrics endpoint and the workload harness | Operators learn of a blocked request or a full limit from the logs only | Before the user count or the file sizes grow past the first release | P35, section 9 |
| Push of more than 10,000 entries in one command | The user must split a large data set by hand | Users have such data sets | Not designed |
| A grace period before an old object is removed | A reader on another client gets a stale-handle error in the middle of a read | Readers report the error | Not designed |
| Full ONTAP qualification with 50 identities and files of 100 GiB | Limits are estimates, not measurements | Before the limits are raised | P37, section 9 |

## Items that were dropped, not deferred

- The four-prototype phase (P02 to P04). The tests of plans 2 and 3 cover the same questions on
  the real code. The tusd experiment stays as plan 2 task S1.
- The production interlock (P07) and the tests-only legacy composition.
- The staged table name `upload_attempts` and its later rename.
- The rules for agent dispatch, profiles and review counts. `/implement-markdown` has its own.
