# Chat activity

## Problem

The production chat paints every tool call as its own row. In the screenshot from this request, one Unity Catalog walk is seven stacked rows: `uc_list_catalogs`, `uc_list_schemas` twice, `load_capability`, `uc_list_tables`, `uc_describe_table`, and `ask_user`. Each row shows raw arguments. The person in the chat pays for that: the question the model asked is a JSON blob (`question`, `options` Hourly / Daily / Weekly / Just create the agent / skip the schedule, `default` Daily, `multi` false) with no buttons, so the turn stays paused. An approval card, when it appears, is the same raw-arguments block, and clicking Approve or Deny does not continue the visible turn. The source gives no count beyond that screenshot.

When this ships, a run of tool calls reads as one collapsed group, a question is buttons the person can press, and an approval continues the same turn on screen.

## Flow

This copies the grouping and pause cards the legacy transcript already renders. It does not add a second pause protocol.

1. A turn's SSE frames enter the chat route (exists). Consecutive `tool_call` and `tool_result` frames fold into one collapsed group. A `question` frame and an `approval_required` frame render as cards after that group.
2. An option click, Approve, or Deny posts to the question and approval routes (exists) with `Accept: text/event-stream`.
3. out: the resumed frames append on the same chat route (exists).

## Impact

| Front | What changes |
| --- | --- |
| domain | nothing — `tool_call`, `ask_user`, and approval keep their current names and stored rows |
| stored data | nothing to migrate |

## Relations

None - no stored-data shape change

## Surface

None - nothing consumed outside. The chat starts sending `Accept: text/event-stream` on the existing answer and approve routes; their statuses stay 200, 404, 409, and 422.

## Landing

None - the grouping rule and the question and approval cards already ship in the legacy transcript. This copies them into the production chat. Nothing here is a new contract or a persisted shape.

## Criteria

### S1: One collapsed group for a run of tool calls (P1)

A burst of tool calls reads as one closed group until the transcript leaves tool activity.

**Acceptance Criteria**

1. WHEN two `tool_call` frames arrive with no user message, assistant text, notice, question card, or approval card between them THEN the chat SHALL render both inside one group.
2. The group SHALL start collapsed.
3. WHEN a group holds N tool rows THEN its summary SHALL read `Expand tool calls` and `N calls`, and N = 1 SHALL read `1 call`.
4. WHEN the user expands the group THEN the summary SHALL read `Hide tool calls`.
5. WHEN a user message, assistant text, notice, question card, or approval card is appended after a group THEN the next `tool_call` SHALL start a second group.
6. WHILE a row in the group has state `running` the summary SHALL include `Running {name}...` with that row's tool name.
7. WHEN the matching `tool_result` arrives THEN that row SHALL leave state `running` and the summary SHALL omit `Running`.
8. IF the turn emits event `error` THEN every row still in state `running` SHALL change to state `error`.

**Independent test:** Render two consecutive tool calls and assert one collapsed group labeled `2 calls`; insert an assistant line and assert the next call starts a second group.

### S2: An `ask_user` pause is a question the person can answer (P1)

The question in the screenshot is buttons, and the answer continues the turn.

**Acceptance Criteria**

9. The chat SHALL NOT render a tool row whose name is `ask_user`.
10. WHEN a `question` frame arrives THEN the chat SHALL show one card whose text is the frame's `question` and one button per entry in `options`.
11. The question card SHALL NOT include the arguments JSON string.
12. WHEN `multi` is false and the user clicks `Daily` THEN the chat SHALL POST `/api/questions/{question_id}/answer` with header `Accept: text/event-stream` and body `{"selected":["Daily"]}`, and SHALL append the resumed turn's frames to the transcript.
13. WHEN `multi` is true and no option is toggled THEN the `Send` button SHALL be disabled.
14. WHEN `multi` is true and the user toggles `Weekly` then `Hourly` and clicks `Send` THEN the chat SHALL POST body `{"selected":["Weekly","Hourly"]}`.
15. WHERE an option label equals the frame's `default` the button SHALL include the text `default`.
16. IF the answer response status is not 200 THEN the chat SHALL re-enable the option buttons and SHALL show `Could not send the answer.`
17. IF the answer request throws THEN the chat SHALL re-enable the option buttons and SHALL show `Network error while sending the answer.`
18. WHILE a question card is unanswered the composer SHALL be disabled and its placeholder SHALL be `Waiting for your answer.`
19. WHEN the session loads and GET `/api/sessions/{id}/questions` returns a pending question THEN the chat SHALL show one unanswered card for that `id`.
20. WHEN a stored `ask_user` result is `The user chose: Daily` THEN the reloaded card SHALL disable every button and mark `Daily`.
21. WHEN a stored `ask_user` result contains `picked the default option "Daily"` THEN the reloaded card SHALL disable every button and mark `Daily`.

**Independent test:** Stream a `question` frame with options Hourly and Daily, click Daily, and assert the POST body and that a following `token` frame appears in the transcript.

### S3: An inline approval continues the visible turn (P1)

Approve and Deny resume the same chat instead of leaving it on the card.

**Acceptance Criteria**

22. WHEN an `approval_required` frame arrives THEN the chat SHALL show one card after the tool group, not inside it, with the tool name, an `Approve` button, and a `Deny` button.
23. The approval card SHALL keep `arguments` behind a disclosure labeled `Arguments` that starts closed.
24. WHILE that card is unresolved the group summary SHALL include `Approval required for {name}`, the composer SHALL be disabled, and its placeholder SHALL be `Waiting for approval.`
25. WHEN the user clicks `Approve` THEN the chat SHALL POST `/api/approvals/{approval_id}/approve` with header `Accept: text/event-stream`, SHALL append the resumed frames, and the card SHALL read `Approved {name}` with both buttons removed.
26. WHEN the user clicks `Deny` THEN the chat SHALL POST `/api/approvals/{approval_id}/deny` with header `Accept: text/event-stream`, and the card SHALL read `Denied {name}` with both buttons removed.
27. IF the approve response status is not 200 THEN the chat SHALL keep both buttons and SHALL show `Failed to approve tool call.`
28. IF the deny response status is not 200 THEN the chat SHALL keep both buttons and SHALL show `Failed to deny tool call.`
29. IF the approve request throws THEN the chat SHALL show `Network error while approving tool call.` and SHALL keep both buttons.
30. IF the deny request throws THEN the chat SHALL show `Network error while denying tool call.` and SHALL keep both buttons.
31. WHEN the session loads and GET `/api/approvals` lists a pending approval whose `session_id` equals this session THEN the chat SHALL show one unresolved card for that `id`.

**Independent test:** Emit `approval_required` for `jobs_create`, click Approve, and assert the POST sends `Accept: text/event-stream` and a following `token` frame is appended.

## Out of scope

| Excluded | Why |
| --- | --- |
| Progress checklist cards for the `progress` SSE event | The backend already emits them. This request is the tool list and the stuck question and approval. |
| The `/approvals` page | It already lists pending tools and resolves them as JSON. The stuck turn is the chat. |
| The legacy `frontend/` transcript | It already groups calls and renders the cards. The production screen is `frontend-reimagined`. |
| A second confirm before Deny | Deny stays one click, as it is today. |
| A change to the question or approval HTTP contracts | The chat consumes the routes that already resume a turn. |

## Assumptions

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| none left | none left | every default above is a numbered criterion | n |

**Open questions:** none - all resolved or logged above.

## Observable

| Surface | Decision | Landing |
| --- | --- | --- |
| screen chat | empty state | existing - `What should we claw at today?` when the transcript has no items |
| screen chat | loading | AC 6, and the existing `thinking…` line while a turn has no live assistant text |
| screen chat | error state | AC 8, AC 16, AC 17, AC 27, AC 28, AC 29, AC 30 |
| screen chat | unauthorised | n/a - this feature adds no auth gate; the app session already gates the chat |
| screen chat | density and ordering | AC 1, AC 3, AC 5, AC 22 |
| screen chat | destructive action confirms | existing - Deny is one click, same as the current approval card |
| screen `/approvals` | empty, loading, error, unauthorised, density, destructive confirm | n/a - that screen is unchanged |
| collection tool calls | grouping criterion | AC 1 |
| collection tool calls | naming | AC 3 |
| collection tool calls | ordering | AC 5 - arrival order inside the group; a non-tool item starts the next group |
| collection tool calls | duplicates | n/a - two calls with the same name stay two rows; the group does not merge by name |
| collection tool calls | exception that does not fit | AC 9 - `ask_user` is not a member of the group |
| API answer and approve | error shape and codes | existing - 200, 404, 409, 422 on the current routes; the chat treats any non-200 as AC 16, AC 27, or AC 28 |
| API answer and approve | versioning, rate limits, who may call | n/a - no new route and no new caller |

## Sources

- Screenshot on this request — seven stacked tool rows, with `ask_user` shown as a JSON arguments string and no option buttons.
- Legacy transcript — `frontend/transcript.ts` groups consecutive tool calls; `frontend/cards.ts` and `frontend/chat.ts` render the question card and resume the turn with `Accept: text/event-stream`.
