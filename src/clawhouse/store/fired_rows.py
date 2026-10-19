"""Fired-job rows for the Lakebase and memory stores."""

import asyncio
from collections.abc import Iterable

import asyncpg

from clawhouse.store import fired_schema as _fired_sql
from clawhouse.store import mappers as _map
from clawhouse.store.shapes import FiredDelivery, FiredJob, FiredKind


class FiredLakebase:
    _pool: asyncpg.Pool

    async def insert_fired_job(self, job: FiredJob) -> FiredJob:
        row = await self._pool.fetchrow(
            _fired_sql._INSERT_FIRED_JOB,
            _map._uuid(job.id),
            _map._uuid(job.session_id),
            job.owner_id,
            job.kind,
            job.name,
            job.slack_webhook_url,
            job.agent_name,
            job.instructions,
            job.databricks_job_id,
            _map._uuid(job.schedule_id) if job.schedule_id else None,
        )
        if row is None:
            raise RuntimeError("failed to insert fired job")
        return _fired_job_from_row(row)

    async def fired_job_by_databricks_id(self, job_id: int) -> FiredJob | None:
        row = await self._pool.fetchrow(_fired_sql._SELECT_FIRED_BY_JOB, job_id)
        return _fired_job_from_row(row) if row is not None else None

    async def fired_job_by_schedule(self, schedule_id: str) -> FiredJob | None:
        sid = _map._uuid(schedule_id)
        row = await self._pool.fetchrow(_fired_sql._SELECT_FIRED_BY_SCHEDULE, sid)
        return _fired_job_from_row(row) if row is not None else None

    async def try_insert_delivery(self, delivery: FiredDelivery) -> bool:
        if delivery.databricks_job_id is not None:
            row = await self._pool.fetchrow(
                _fired_sql._INSERT_DELIVERY_RUN,
                _map._uuid(delivery.id),
                _map._uuid(delivery.fired_job_id),
                delivery.databricks_job_id,
                delivery.run_id,
                delivery.event_type,
                delivery.sheet_status,
            )
            return row is not None
        row = await self._pool.fetchrow(
            _fired_sql._INSERT_DELIVERY_SLOT,
            _map._uuid(delivery.id),
            _map._uuid(delivery.fired_job_id),
            _map._uuid(delivery.schedule_id) if delivery.schedule_id else None,
            delivery.next_run_at,
            delivery.sheet_status,
        )
        return row is not None

    async def delete_delivery_run(self, job_id: int, run_id: int, event_type: str) -> None:
        await self._pool.execute(_fired_sql._DELETE_DELIVERY_RUN, job_id, run_id, event_type)

    async def delivery_for_run(
        self, job_id: int, run_id: int, event_type: str
    ) -> FiredDelivery | None:
        row = await self._pool.fetchrow(_fired_sql._SELECT_DELIVERY_RUN, job_id, run_id, event_type)
        if row is None:
            return None
        return FiredDelivery(
            id=str(row["id"]),
            fired_job_id=str(row["fired_job_id"]),
            databricks_job_id=row["databricks_job_id"],
            run_id=row["run_id"],
            event_type=row["event_type"],
            schedule_id=str(row["schedule_id"]) if row["schedule_id"] else None,
            next_run_at=row["next_run_at"],
            sheet_status=row["sheet_status"],
        )


class FiredMemory:
    _lock: asyncio.Lock
    _fired_jobs: dict[str, FiredJob]
    _deliveries: dict[str, FiredDelivery]

    async def close(self) -> None:
        return None

    async def insert_fired_job(self, job: FiredJob) -> FiredJob:
        async with self._lock:
            self._fired_jobs[job.id] = job
            return job

    async def fired_job_by_databricks_id(self, job_id: int) -> FiredJob | None:
        async with self._lock:
            for job in self._fired_jobs.values():
                if job.databricks_job_id == job_id:
                    return job
            return None

    async def fired_job_by_schedule(self, schedule_id: str) -> FiredJob | None:
        async with self._lock:
            for job in self._fired_jobs.values():
                if job.schedule_id == schedule_id:
                    return job
            return None

    async def try_insert_delivery(self, delivery: FiredDelivery) -> bool:
        async with self._lock:
            if _delivery_conflict(self._deliveries.values(), delivery):
                return False
            self._deliveries[delivery.id] = delivery
            return True

    async def delete_delivery_run(self, job_id: int, run_id: int, event_type: str) -> None:
        async with self._lock:
            doomed = [
                key
                for key, row in self._deliveries.items()
                if row.databricks_job_id == job_id
                and row.run_id == run_id
                and row.event_type == event_type
            ]
            for key in doomed:
                del self._deliveries[key]

    async def delivery_for_run(
        self, job_id: int, run_id: int, event_type: str
    ) -> FiredDelivery | None:
        async with self._lock:
            for row in self._deliveries.values():
                if (
                    row.databricks_job_id == job_id
                    and row.run_id == run_id
                    and row.event_type == event_type
                ):
                    return row
            return None


def _fired_job_from_row(row: asyncpg.Record) -> FiredJob:
    raw = row["kind"]
    kind: FiredKind = raw if raw in ("sql", "sql_agent", "agent") else "sql"
    return FiredJob(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        owner_id=row["owner_id"],
        kind=kind,
        name=row["name"],
        slack_webhook_url=row["slack_webhook_url"],
        instructions=row["instructions"],
        agent_name=row["agent_name"],
        databricks_job_id=row["databricks_job_id"],
        schedule_id=str(row["schedule_id"]) if row["schedule_id"] else None,
    )


def _delivery_conflict(rows: Iterable[object], delivery: FiredDelivery) -> bool:
    for row in rows:
        if not isinstance(row, FiredDelivery):
            continue
        same_run = (
            delivery.databricks_job_id is not None
            and row.databricks_job_id == delivery.databricks_job_id
            and row.run_id == delivery.run_id
            and row.event_type == delivery.event_type
        )
        same_slot = (
            delivery.schedule_id is not None
            and delivery.next_run_at is not None
            and row.schedule_id == delivery.schedule_id
            and row.next_run_at == delivery.next_run_at
        )
        if same_run or same_slot:
            return True
    return False
