# Chat activity checks

Profile: light
Plan: `.specs/features/chat-activity/plan.md`

31 checks in 3 slices · 0 one-way doors · 0 open, of which 0 block

## Checks

### S1 - grouped tool calls · 3 files · 32 KB · ~8k

**C1** - Two tool_call frames with nothing between them render inside one group (AC 1)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "two tool calls share one group"`

**C2** - A tool group starts collapsed (AC 2)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a tool group starts collapsed"`

**C3** - The group summary reads Expand tool calls and N calls, and one row reads 1 call (AC 3)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "group summary reads Expand tool calls and the call count"`

**C4** - Expanding the group changes the summary to Hide tool calls (AC 4)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "expanding a tool group reads Hide tool calls"`

**C5** - A user message, assistant text, notice, question card, or approval card after a group makes the next tool_call a second group (AC 5)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a break between tool calls starts a second group"`

**C6** - While a row is running the summary includes Running query... (AC 6)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a running tool group reads Running"`

**C7** - The matching tool_result leaves state running and the summary omits Running (AC 7)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a tool result leaves the running state"`

**C8** - An error frame changes a running row to state error (AC 8)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "an error frame sets the running tool to error"`

### S2 - question cards · 3 files · 40 KB · ~10k

**C9** - The chat does not render a tool row named ask_user (AC 9)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "ask_user is not a tool row"`

**C10** - A question frame shows the question text and one button per option (AC 10)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a question frame shows the question and one button per option"`

**C11** - The question card does not include the arguments JSON string (AC 11)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a question card does not show the arguments JSON"`

**C12** - Clicking Daily posts Accept text/event-stream and body selected Daily, then appends the resumed token (AC 12)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "clicking Daily posts the answer and appends the resumed token"`

**C13** - Send stays disabled when multi is true and no option is toggled (AC 13)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "Send stays disabled until a multi option is toggled"`

**C14** - Toggling Weekly then Hourly and clicking Send posts selected Weekly, Hourly (AC 14)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "Send posts Weekly then Hourly"`

**C15** - The option equal to default includes the text default (AC 15)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "the default option button includes default"`

**C16** - An answer response that is not 200 re-enables the option buttons and shows Could not send the answer. (AC 16)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a non-200 answer shows Could not send the answer"`

**C17** - A thrown answer request re-enables the option buttons and shows Network error while sending the answer. (AC 17)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a thrown answer shows Network error while sending the answer"`

**C18** - An unanswered question disables the composer and sets its placeholder to Waiting for your answer. (AC 18)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "an unanswered question disables the composer"`

**C19** - Loading a session with one pending question shows one unanswered card for that id (AC 19)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a pending question loads as one card"`

**C20** - A stored result The user chose: Daily reloads with every button disabled and Daily marked (AC 20)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a stored choice marks Daily"`

**C21** - A stored result containing picked the default option "Daily" reloads with every button disabled and Daily marked (AC 21)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a stored default marks Daily"`

### S3 - inline approvals · 3 files · 48 KB · ~12k

**C22** - An approval_required frame shows one card after the tool group, not inside it, with the tool name, Approve, and Deny (AC 22)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "an approval card sits after the tool group"`

**C23** - Approval arguments sit behind a disclosure labeled Arguments that starts closed (AC 23)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "approval arguments start behind a closed Arguments disclosure"`

**C24** - An unresolved approval summary includes Approval required for jobs_create, and the composer is disabled with placeholder Waiting for approval. (AC 24)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "an unresolved approval blocks the composer"`

**C25** - Approve posts Accept text/event-stream, appends the resumed token, and the card reads Approved jobs_create with both buttons removed (AC 25)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "Approve posts an event stream and reads Approved"`

**C26** - Deny posts Accept text/event-stream and the card reads Denied jobs_create with both buttons removed (AC 26)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "Deny posts an event stream and reads Denied"`

**C27** - An approve response that is not 200 keeps both buttons and shows Failed to approve tool call. (AC 27)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a non-200 approve shows Failed to approve tool call"`

**C28** - A deny response that is not 200 keeps both buttons and shows Failed to deny tool call. (AC 28)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a non-200 deny shows Failed to deny tool call"`

**C29** - A thrown approve request shows Network error while approving tool call. and keeps both buttons (AC 29)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a thrown approve shows Network error while approving tool call"`

**C30** - A thrown deny request shows Network error while denying tool call. and keeps both buttons (AC 30)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a thrown deny shows Network error while denying tool call"`

**C31** - Loading a session shows one unresolved card when GET /api/approvals lists a pending approval for this session (AC 31)
Proof: `cd frontend-reimagined && bun run test -- src/test/chat-activity.test.tsx -t "a pending approval for this session loads as one card"`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| group break (5) | user message C5 · assistant text C5 · notice C5 · question card C5 · approval card C5 | - |
| call count label (2) | `2 calls` C3 · `1 call` C3 | - |
| stored ask_user result (2) | `The user chose: Daily` C20 · `picked the default option "Daily"` C21 | - |
| approval decision (2) | Approve C25 · Deny C26 | - |
| approval failure (4) | approve non-200 C27 · deny non-200 C28 · approve throw C29 · deny throw C30 | - |
| question failure (2) | answer non-200 C16 · answer throw C17 | - |
| composer block (2) | `Waiting for your answer.` C18 · `Waiting for approval.` C24 | - |

- The plan names 200, 404, 409, and 422 as the existing answer and approve routes. The chat branches on 200 (C12, C25) versus any other status (C16 uses 409, C27 uses 409). It does not dispatch per code.
- No other check claims more than the single case its proof exercises

## Swept

- validation: C10, C16 - options render from the frame, and any non-200 answer, including the route's 422, shows `Could not send the answer.`
- failure modes: C8, C16, C17, C27, C28, C29, C30
- idempotency: n/a - the chat sends one POST per click and does not retry; a repeat of an answered question is the existing 409 from the answer route
- authorization: existing - the app session already gates the chat; this feature adds no caller
- concurrency: C5, C18, C24 - a non-tool item starts a new group, and the composer stays disabled while a question or approval is unresolved
- data lifecycle: n/a - no new stored rows; a reload reads the existing transcript and pending endpoints (C19, C20, C31)
- dependency failure: C17, C29, C30
- state transitions: C7, C8, C25, C26
- observability: n/a - no logging requirement in this slice

## Handoff

- S1–S3 share the production chat. `frontend-reimagined/src/routes/index.tsx` is 13517 bytes and `frontend-reimagined/src/lib/api.ts` is 13716 bytes; the new view and the test add about 28 KB. 55 KB / 4 ≈ 14k, under the 150k budget — one builder
