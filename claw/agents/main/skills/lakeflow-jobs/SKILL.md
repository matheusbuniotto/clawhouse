---
name: lakeflow-jobs
description: Inspect, run, create, edit, and cancel Databricks Lakeflow Jobs with the jobs_* tools. Use when the user asks about jobs, job runs, reruns, failures, or wants to create or change a job.
---

# Lakeflow Jobs

Work with Lakeflow Jobs through these tools. Never guess a job id or run id: find it first.

| Tool | Effect | Approval |
| --- | --- | --- |
| `jobs_list(limit)` | Lists jobs (id, name, creator). Max 100, no paging. | no |
| `jobs_get_run(run_id)` | State of one run, plus each task's state. | no |
| `jobs_run_now(job_id, parameters)` | Starts a run. `parameters` overrides job parameters. | **yes** |
| `jobs_create(name, task_type, path, ...)` | Creates a one-task job. | **yes** |
| `jobs_edit(job_id, new_settings)` | Changes top-level job settings. | **yes** |
| `jobs_cancel_run(run_id)` | Requests cancellation of an active run. | **yes** |

## Workflow

1. **Find the job.** Call `jobs_list` and match by name. If several jobs match or none do, say so and ask. Do not pick one silently.
2. **Look before you act.** For "why did it fail" or "is it done", call `jobs_get_run` and read the `tasks` states, not just the run state.
3. **Say what you are about to do, then call the mutating tool.** The turn pauses until the user approves. State the job, the parameters, and the effect in one sentence so the approval card makes sense.
4. **After approval, report the result.** `jobs_run_now` returns a `run_id`: tell the user it was triggered, not that it finished. Offer to check it with `jobs_get_run`.
5. **If the call is denied or returns `error`,** report that plainly. Do not retry a mutating call on your own.

## Reading run state

- `life_cycle_state`: `PENDING`/`QUEUED`/`BLOCKED`/`WAITING_FOR_RETRY` (not started), `RUNNING`/`TERMINATING` (in flight), `TERMINATED` (done), `SKIPPED`/`INTERNAL_ERROR` (did not run).
- `result_state` is only set once the run is `TERMINATED`: `SUCCESS`, `FAILED`, `TIMEDOUT`, `CANCELED`, and so on.
- `state_message` often holds the failure reason. Quote it.
- `duration_ms` is only present when the run has both started and ended.

## Creating a job

- `task_type="python"`: `path` is a workspace Python file; `parameters` are its command-line arguments.
- `task_type="sql"`: `path` is a workspace `.sql` file. It runs on `warehouse_id`, or on the session's SQL warehouse when omitted. If neither exists, the tool returns an error.
- The job gets one task, named after the job. For anything more (several tasks, schedules, clusters), create the job, then use `jobs_edit`, or tell the user it needs the Jobs UI or a bundle.
- Confirm `path` with the user. Check that the file exists with a workspace listing tool when one is available.

## Editing a job

- `new_settings` is a dict of top-level settings to change, for example `{"name": "nightly-v2", "max_concurrent_runs": 2}`. Keys are snake_case and match the Jobs API. A misspelled key is ignored, so read the job back afterwards when it matters.
- Omitted settings stay as they are. Tasks are merged by `task_key`, and this tool cannot remove a task.
- Prefer small edits. Never rewrite a job's tasks to change one setting.

## Safety

- Re-running a job can write to production tables. When the job name or parameters suggest `prod`, mention it in step 3.
- Cancel only the run the user named. Check its state with `jobs_get_run` first; a `TERMINATED` run cannot be cancelled.
