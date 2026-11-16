"""Load generator for the autoscaling demo (make load, make drill).

Creates synthetic monitoring jobs, with addresses at example.com, which the
notification worker logs instead of emailing (SUPPRESS_EMAIL_DOMAINS). Then it
sends messages straight to the analysis queue, each carrying a batch of fake
comments. That skips YouTube and ingestion and loads exactly the stage KEDA
scales from zero: the AI worker. Every message has its own interval timestamp,
so each one also flows through aggregation and notification.

  python -m src.load_test --jobs 20 --messages 200   # in the cluster: make load
  python -m src.load_test --cleanup                   # delete the synthetic jobs

After sending, it waits until every message has been scored, aggregated and
notified, by counting this run's interval rows that have `notified_at` set.
The unique (job_id, timestamp) constraint means a redelivered message can't
add a second row, so "notified == sent" proves nothing was lost or doubled.

Message size: SQS accepts up to 1 MiB per message (src/common/queue.py checks
before sending). 50 short comments are about 3 KB. A real video's batch could
exceed the limit; the answers are chunking the batch into several messages, or
the claim-check pattern: put the payload in S3 and send only its key.
"""
from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from src.common.config import LoadTestSettings, get_settings
from src.common.db import create_session_factory
from src.common.queue import publish
from src.models import IntervalResultDB, MonitoringJobDB

POST_ID = "load-test"  # marks synthetic jobs, for --cleanup
EMAIL_DOMAIN = "example.com"  # reserved for examples (RFC 2606); suppressed by notification

PHRASES = [
    "love this channel great content",
    "worst explanation confusing waste time",
    "pretty good overall audio bit quiet",
    "best video watched all year thank you",
    "not sure agree point made minute five",
    "absolutely terrible want time back",
    "clear concise helpful thanks",
    "¡me encanta este canal, sigue así!",
    "c'est vraiment nul, je n'ai rien compris",
    "sehr hilfreich, danke für die erklärung",
]


def create_jobs(db: Session, count: int) -> list[UUID]:
    """Insert `count` jobs and return their IDs. No schedules: nothing else runs for them."""
    ids = []
    for i in range(count):
        job_id = uuid4()
        db.add(
            MonitoringJobDB(
                job_id=job_id,
                post_id=POST_ID,
                post_title=f"Load test video {i + 1}",
                user_full_name="Load Test",
                email=f"load+{i + 1}@{EMAIL_DOMAIN}",
                intervals_seconds=300,
                total_duration_seconds=1800,
                is_scheduled=False,
            )
        )
        ids.append(job_id)
    db.commit()
    return ids


def build_messages(
    job_ids: list[UUID], total: int, comments_per_message: int, rng: random.Random, start: datetime
) -> list[dict[str, Any]]:
    """`total` analysis messages spread round-robin over the jobs, each with a
    timestamp unique within its job (one interval row per message)."""
    messages = []
    for n in range(total):
        job_id = job_ids[n % len(job_ids)]
        timestamp = start + timedelta(seconds=n)
        messages.append(
            {
                "job_id": str(job_id),
                "interval_timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "comments": [rng.choice(PHRASES) for _ in range(comments_per_message)],
            }
        )
    return messages


def send_all(queue: str, messages: list[dict[str, Any]], threads: int = 16) -> float:
    """Publish every message, `threads` at a time. Returns the seconds taken."""
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        # enqueued_at at the moment of sending: the start of the SLO's end-to-end latency.
        list(pool.map(lambda m: publish(queue, {**m, "enqueued_at": datetime.now(UTC).isoformat()}), messages))
    return time.monotonic() - began


def cleanup(db: Session) -> tuple[int, int]:
    """Delete synthetic jobs and their interval rows. Returns (jobs, intervals) deleted."""
    job_ids = [row.job_id for row in db.query(MonitoringJobDB.job_id).filter_by(post_id=POST_ID)]
    if not job_ids:
        return 0, 0
    in_jobs = IntervalResultDB.job_id.in_(job_ids)
    intervals = db.query(IntervalResultDB).filter(in_jobs).delete(synchronize_session=False)
    jobs = db.query(MonitoringJobDB).filter(MonitoringJobDB.job_id.in_(job_ids)).delete(synchronize_session=False)
    db.commit()
    return jobs, intervals


def count_notified(db: Session, job_ids: list[UUID]) -> int:
    """Intervals of these jobs that went all the way through the pipeline."""
    return (
        db.query(IntervalResultDB)
        .filter(IntervalResultDB.job_id.in_(job_ids), IntervalResultDB.notified_at.isnot(None))
        .count()
    )


def wait_until_notified(session_factory, job_ids: list[UUID], expected: int, timeout: float) -> tuple[int, float]:
    """Poll until `expected` intervals are notified or `timeout` passes. Returns (count, seconds)."""
    began = time.monotonic()
    last_print = 0.0
    done = 0
    while (elapsed := time.monotonic() - began) < timeout:
        with session_factory() as db:  # a fresh session each time: no cached rows
            done = count_notified(db, job_ids)
        if done >= expected:
            break
        if elapsed - last_print >= 15:
            print(f"{datetime.now(UTC):%H:%M:%S} UTC  {done}/{expected} fully processed", flush=True)
            last_print = elapsed
        time.sleep(5)
    return done, time.monotonic() - began


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--jobs", type=int, default=20, help="synthetic jobs to create")
    parser.add_argument("--messages", type=int, default=200, help="analysis messages to send")
    parser.add_argument("--comments", type=int, default=50, help="comments per message")
    parser.add_argument("--seed", type=int, default=7, help="random seed for the fake comments")
    parser.add_argument("--cleanup", action="store_true", help="delete earlier synthetic jobs and exit")
    parser.add_argument("--timeout", type=int, default=900, help="seconds to wait for every message to finish")
    args = parser.parse_args(argv)

    settings = get_settings(LoadTestSettings)
    session_factory = create_session_factory(settings)

    if args.cleanup:
        with session_factory() as db:
            jobs, intervals = cleanup(db)
        print(f"Deleted {jobs} synthetic jobs and {intervals} interval rows.")
        return

    with session_factory() as db:
        job_ids = create_jobs(db, args.jobs)
    start = datetime.now(UTC).replace(microsecond=0)
    messages = build_messages(job_ids, args.messages, args.comments, random.Random(args.seed), start)

    print(f"{datetime.now(UTC):%H:%M:%S} UTC  created {len(job_ids)} jobs; sending {len(messages)} messages "
          f"({args.comments} comments each) to {settings.analysis_queue}")
    began = time.monotonic()
    seconds = send_all(settings.analysis_queue, messages)
    print(f"{datetime.now(UTC):%H:%M:%S} UTC  sent {len(messages)} messages in {seconds:.1f}s; "
          "waiting for all of them to be scored, aggregated and notified", flush=True)

    done, _ = wait_until_notified(session_factory, job_ids, len(messages), args.timeout)
    total = time.monotonic() - began
    if done < len(messages):
        print(f"RESULT  FAILED: {done}/{len(messages)} processed after {total:.0f}s. Check the DLQs and worker logs.")
        raise SystemExit(1)
    print(f"RESULT  {done}/{len(messages)} messages fully processed in {total:.0f}s "
          "(first message sent → last interval notified). None lost, none doubled.")


if __name__ == "__main__":
    main()
