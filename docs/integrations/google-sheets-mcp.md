# Google Sheets Writes

Chat can create a spreadsheet in the signed-in user's Google Drive and overwrite one rectangle of a sheet this app created. Each write pauses for an inline in-chat approval. The app uses the forwarded user token against Databricks AI Gateway (`system.ai.google_drive`). There is no service-principal fallback. A missing token writes nothing. The app requests the `mcp.external` user API scope. Each write is one JSON-RPC session over the Databricks HTTP stack, with no retry.

| Service | URL |
| --- | --- |
| Google Drive | `https://<workspace>/ai-gateway/mcp-services/system.ai.google_drive` |

## Probe (2026-10-13, workspace `dbc-562d9321-2592`)

`system.ai.google_drive` is connected for the CLI user. The write tools that exist are `google_file_create` (`file_type=spreadsheet` creates an empty sheet; `content` is only for Docs) and `google_sheet_update_values` (`file_id`, `range_a1`, `values`). There is no rename-tab tool. A throwaway spreadsheet `clawhouse-probe-delete-me` (`1YxrwAgxC3Oid-YjU58IH0nq9QLXjTGhPK0GbxqnpZH4`) came back as:

```json
{"id": "...", "mimeType": "application/vnd.google-apps.spreadsheet", "webViewLink": "https://docs.google.com/spreadsheets/d/.../edit?usp=drivesdk"}
```

The first tab on a localized Portuguese account is `Página1`, not `Sheet1`. Create therefore reads `metadata.sheet_tabs[0].title` on the file it just created (`google_file_read`) and writes there. The model-facing create tool does not accept a tab name. Update requires the tab the create result returned.

`google_sheet_update_values` treats strings starting with `=` as formulas. A cell `=1+1` was stored as the number 2. A cell `'=1+1` was stored as the text `=1+1` (the apostrophe is the text marker and is not shown). Negative numbers are sent as JSON numbers. An unknown spreadsheet id returned `is_error` with a 404 and no write.

Authorization failures `-32042` and `-32006` both ask the user to authorize the connector in Catalog Explorer. HTTP 401 and 403 are reported as a status code only without exposing the response body.

## Behaviour

- Create and update are the only Drive tools the agent can call. The internal tab read is not a model tool.
- Update's A1 range is computed from the start cell and the shape of `rows`. A model-supplied end range is rejected.
- Limits: 500 rows, 26 columns, 1,000 characters per text cell, one rectangular block.
- Formula safety: Cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` are prefixed with `'`. Negative numbers are numbers and left untouched.
- Success returns only `https://docs.google.com/spreadsheets/d/<id>` built from the validated id. Other URLs in the connector reply are dropped.
- Timeout and unrecognised replies tell the user to check Drive. The agent instructions forbid a retry. Create is not idempotent.
- Scheduled turns have no forwarded user token, so these tools write nothing there.
