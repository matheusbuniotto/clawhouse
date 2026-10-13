---
name: lakeflow-jobs
description: Inspect, run, create, edit, delete, and cancel Databricks Lakeflow Jobs (SQL, Python, and Agentic jobs) with the jobs_* tools. Use when the user asks about jobs, job runs, scheduling, reruns, failures, or wants to create, edit, or delete a job.
---

# Lakeflow Jobs

Work with Lakeflow Jobs through these tools. Never guess a job id or run id: find it first.

| Tool | Effect | Approval |
| --- | --- | --- |
| `jobs_list(limit)` | Lists jobs (id, name, creator). Max 100, no paging. | no |
| `jobs_get_run(run_id)` | State of one run, plus each task's state. | no |
| `jobs_get_run_output(run_id)` | Execution output, logs, and query results of a run. | no |
| `jobs_run_now(job_id, parameters)` | Starts a run. `parameters` overrides job parameters. | **yes** |
| `jobs_create(name, task_type, ...)` | Creates a SQL, Python, or Agentic job (with optional schedule). | **yes** |
| `jobs_edit(job_id, ...)` | Updates job name, schedule, query, or settings. | **yes** |
| `jobs_delete(job_id)` | Deletes a job from the workspace. | **yes** |
| `jobs_cancel_run(run_id)` | Requests cancellation of an active run. | **yes** |

## Workflow

1. **Find the job.** Call `jobs_list` and match by name. If several jobs match or none do, say so and ask. Do not pick one silently.
2. **Look before you act.** For "why did it fail" or "is it done", call `jobs_get_run` and read the `tasks` states. Use `jobs_get_run_output` to read the task logs and agent analysis.
3. **Say what you are about to do, then call the mutating tool.** The turn pauses until the user approves. State the job, the parameters, and the effect in one sentence so the approval card makes sense.
4. **After approval, report the result.** `jobs_run_now` returns a `run_id`: tell the user it was triggered, not that it finished. Offer to check it with `jobs_get_run`.
5. **If the call is denied or returns `error`,** report that plainly. Do not retry a mutating call on your own.

## Reading Run State & Output

- `life_cycle_state`: `PENDING`/`QUEUED`/`BLOCKED`/`WAITING_FOR_RETRY` (not started), `RUNNING`/`TERMINATING` (in flight), `TERMINATED` (done), `SKIPPED`/`INTERNAL_ERROR` (did not run).
- `result_state` is only set once the run is `TERMINATED`: `SUCCESS`, `FAILED`, `TIMEDOUT`, `CANCELED`.
- `state_message` holds the failure reason. Quote it.
- Call `jobs_get_run_output(run_id)` on completed runs to retrieve output logs, error traces, and SQL/agent outputs.

## Creating a Job

- **Agentic Job (`task_type="agentic"`)**: Executes a query, feeds the result into Databricks Foundation Model (`ai_query`) with the delegated agent persona, and produces the output analysis. Provide `query`, `agent_name` (e.g. `TaxiAnalyst`), and optional `instructions`.
- **SQL Job (`task_type="sql"`)**: Pass SQL in `query` (automatically saved as a workspace file) or workspace file path in `path`. Runs on session SQL warehouse.
- **Python Job (`task_type="python"`)**: `path` is a workspace Python file; `parameters` are command-line arguments.
- **Job Schedules**: Pass `cron_expression` (e.g. `'0 0 12 * * ?'` or `'0 12 * * *'`), optional `timezone_id='UTC'`, and `pause_status='UNPAUSED'` to attach a recurring schedule.

## Editing a Job (`jobs_edit`)

- **Rename**: Pass `name="new_name"`.
- **Update Schedule**: Pass `cron_expression="0 0 18 * * ?"` and optional `pause_status="PAUSED" | "UNPAUSED"`.
- **Pause or Resume**: Pass `pause_status="PAUSED"` or `pause_status="UNPAUSED"`.
- **Update Query**: Pass `query="SELECT ..."` to update the underlying SQL / agentic task file.
- **Custom Settings**: Pass `new_settings={...}` for raw JobSettings dict overrides.

## Deleting a Job (`jobs_delete`)

- Call `jobs_delete(job_id=...)` with the target job ID.
- Requires user approval. Always state which job will be permanently removed before calling.

## Safety

- Deleting a job is irreversible. Confirm the job name and ID before calling `jobs_delete`.
- Re-running a job can write to production tables. When the job name or parameters suggest `prod`, mention it before triggering.
- Cancel only the run the user named. Check its state with `jobs_get_run` first; a `TERMINATED` run cannot be cancelled.
