# ADR-0001: SQS queues with dead-letter queues instead of RabbitMQ and Celery

**Status:** Accepted

## Context

The original VibeSense passed work between services through RabbitMQ and Celery, with Celery Beat, RedBeat and Redis for scheduling. All of it ran as stateful processes that had to be deployed, patched, backed up and scaled.

## Decision

Every hop between workers is an SQS standard queue (`ingest`, `analysis`, `aggregation`, `notification`), each with its own dead-letter queue (`maxReceiveCount` 5, 14-day retention) and a CloudWatch alarm on the DLQ that emails through SNS. Workers long-poll, delete a message only after handling it, and on failure push its visibility out on a backoff (10, 30, 90, 270 s). `src/common/queue.py` checks the 1 MiB message limit before sending.

## Consequences

- No brokers to run: SQS is pay-per-request and close to free at this volume.
- Redelivery, DLQs and redrive are built in; KEDA reads queue depth natively (ADR-0010).
- Standard queues give at-least-once delivery and no ordering, so every consumer must be idempotent (ADR-0018).
- Local development uses ElasticMQ, an SQS-compatible stand-in, through the same code path.

## Alternatives considered

RabbitMQ in the cluster (a stateful workload to operate); Amazon MQ (an always-on broker billed by the hour); SQS FIFO queues (ordering isn't needed, and FIFO throughput limits and deduplication windows add constraints for no benefit).
