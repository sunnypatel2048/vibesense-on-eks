# ADR-0002: EventBridge Scheduler for each job's interval schedule

**Status:** Accepted

## Context

Each monitoring job fetches new comments on an interval (every 5 minutes to every 24 hours) until it expires. The original used Celery Beat with RedBeat in Redis: a singleton scheduler plus a database to keep it in.

## Decision

When a job is created, the UI creates one EventBridge Scheduler schedule for it (group `vibesense`) with a rate expression, an end date, and `ActionAfterCompletion: DELETE`. Its target is the ingest queue, through a dedicated scheduler role whose trust policy carries confused-deputy conditions (`aws:SourceAccount`, `aws:SourceArn`). The UI's own role may only pass that one role. The UI also enqueues the first ingest immediately.

## Consequences

- Removes Redis and the Beat singleton; nothing in the cluster has to stay up for schedules to fire.
- Schedules expire and delete themselves, so there is no cleanup code.
- One schedule per job is visible and auditable in the AWS console.
- Locally, `src/local_scheduler` stands in, behind the same interface (`get_scheduler()`).

## Alternatives considered

Celery Beat + RedBeat + Redis (stateful, singleton); a Kubernetes CronJob per job (cluster objects created by the app, outliving deletions, and no built-in end date).
