# ADR-0018: At-least-once delivery with idempotent writes

**Status:** Accepted

## Context

SQS standard queues can deliver a message more than once, and a worker can crash between doing work and deleting the message.

## Decision

Interval results have a unique constraint on `(job_id, timestamp)` and are written with `INSERT … ON CONFLICT DO NOTHING`, so a redelivered message can't add a second row. Notification sends the email, then sets `notified_at`; a redelivery of an already-notified interval is skipped. Ingestion publishes before saving its progress, so a crash republishes the same batch, which aggregation then de-duplicates. On SIGTERM, workers stop polling and hand unfinished messages back to SQS.

## Consequences

- No lost work, and no double counting in results.
- Exactly-once email isn't possible: a crash between sending and recording means one duplicate email. The other order would risk a lost email; duplicates were judged the lesser harm.
- The load generator proves it end to end: it counts notified rows and checks `notified == sent` (none lost, none doubled).

## Alternatives considered

SQS FIFO with deduplication (5-minute window, lower throughput, still not exactly-once end to end); distributed transactions (heavy for no practical gain).
