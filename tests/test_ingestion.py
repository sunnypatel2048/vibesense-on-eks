from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.ingestion_service import youtube_fetcher
from src.ingestion_service.app import handle_ingest
from src.ingestion_service.preprocessor import preprocess_text
from src.ingestion_service.youtube_fetcher import fetch_comments
from src.models import MonitoringJobDB


def test_preprocess_text():
    assert preprocess_text("Hello, world! https://example.com") == "hello world"


# --- Fetcher -----------------------------------------------------------------

def thread(comment_id, published_at, text="hi"):
    return {
        "id": comment_id,
        "snippet": {"topLevelComment": {"snippet": {
            "textOriginal": text, "publishedAt": published_at, "likeCount": 1,
        }}},
    }


class FakeYouTube:
    """Mimics client.commentThreads().list(...).execute(), page by page."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def commentThreads(self):
        return self

    def list(self, **params):
        self.requests.append(params)
        return self

    def execute(self):
        index = len(self.requests) - 1
        page = {"items": self.pages[index]}
        if index + 1 < len(self.pages):
            page["nextPageToken"] = f"page-{index + 1}"
        return page


@pytest.fixture
def youtube(monkeypatch):
    def install(pages):
        fake = FakeYouTube(pages)
        monkeypatch.setattr(youtube_fetcher, "_youtube_client", lambda: fake)
        return fake
    return install


def test_fetch_reads_every_page_without_since(youtube):
    fake = youtube([[thread("a", "2026-10-29T12:00:00Z")], [thread("b", "2026-10-29T11:00:00Z")]])
    assert [c["comment_id"] for c in fetch_comments("vid")] == ["a", "b"]
    assert len(fake.requests) == 2


def test_fetch_stops_at_the_first_already_seen_comment(youtube):
    fake = youtube([
        [thread("new", "2026-10-29T12:00:00Z"), thread("old", "2026-10-29T09:00:00Z")],
        [thread("older", "2026-10-28T09:00:00Z")],
    ])
    since = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)
    assert [c["comment_id"] for c in fetch_comments("vid", since)] == ["new"]
    assert len(fake.requests) == 1  # second page never requested


# --- Handler -----------------------------------------------------------------

COMMENTS = [
    {"comment_id": "1", "text": "Great", "published_at": "2026-10-29T12:00:00Z", "metrics": {}},
    {"comment_id": "2", "text": "Meh", "published_at": "2026-10-29T13:30:00Z", "metrics": {}},
]


def ingest(session_factory, job, published, fetched, now=None):
    seen = []

    def fetch(post_id, since):
        seen.append((post_id, since))
        return fetched

    handle_ingest(
        {"job_id": job["job_id"], "post_id": "vid123"},
        session_factory=session_factory,
        fetch=fetch,
        clean=str.lower,
        publish_to=published,
        next_queue="analysis",
        now=now,
    )
    return seen


def last_fetched_at(session_factory, job):
    with session_factory() as db:
        return db.get(MonitoringJobDB, UUID(job["job_id"])).last_fetched_at


def test_new_comments_are_published_and_progress_is_saved(session_factory, job, published):
    seen = ingest(session_factory, job, published, COMMENTS)

    assert seen == [("vid123", None)]
    [(queue, payload)] = published.calls
    assert queue == "analysis"
    assert payload == {
        "job_id": job["job_id"],
        "interval_timestamp": "2026-10-29T13:30:00Z",
        "comments": ["great", "meh"],
    }
    assert last_fetched_at(session_factory, job) == datetime(2026, 10, 29, 13, 30)


def test_second_run_skips_comments_already_seen(session_factory, job, published):
    ingest(session_factory, job, published, COMMENTS)
    second_run = ingest(session_factory, job, published, COMMENTS)

    # The fetcher is told where the first run left off...
    assert second_run == [("vid123", datetime(2026, 10, 29, 13, 30, tzinfo=timezone.utc))]
    assert len(published.calls) == 1  # nothing new the second time


def test_expired_job_is_skipped(session_factory, job, published):
    ingest(session_factory, job, published, COMMENTS, now=datetime.now(timezone.utc) + timedelta(days=2))
    assert published.calls == []


def test_missing_job_is_skipped(session_factory, published):
    ingest(session_factory, {"job_id": "0b8a6f2e-1111-4222-8333-444455556666"}, published, COMMENTS)
    assert published.calls == []
