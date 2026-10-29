from datetime import datetime
from functools import lru_cache
from typing import Any

from googleapiclient.discovery import build

from src.common.config import YouTubeSettings, get_settings


@lru_cache
def _youtube_client():
    """Build the API client on first use, not at import time."""
    api_key = get_settings(YouTubeSettings).youtube_api_key.get_secret_value()
    return build("youtube", "v3", developerKey=api_key)


def parse_published_at(value: str) -> datetime:
    """YouTube timestamps look like '2026-10-29T18:04:11Z'."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_comments(video_id: str, since: datetime | None = None) -> list[dict[str, Any]]:
    """Fetch top-level comments, newest first.

    With `since` (timezone-aware), stop at the first comment published at or
    before it: results are newest-first, so everything after it was already
    seen. That keeps API quota use proportional to *new* comments instead of
    all comments on the video.

    Returns dicts: {comment_id, text, published_at (ISO string), metrics}.
    """
    comments: list[dict[str, Any]] = []
    next_page_token = None

    while True:
        response = (
            _youtube_client()
            .commentThreads()
            .list(
                part="snippet",
                videoId=video_id,
                order="time",
                maxResults=100,
                pageToken=next_page_token,
            )
            .execute()
        )

        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            if since is not None and parse_published_at(snippet["publishedAt"]) <= since:
                return comments
            comments.append(
                {
                    "comment_id": item["id"],
                    "text": snippet["textOriginal"],
                    "published_at": snippet["publishedAt"],
                    "metrics": {"like_count": snippet.get("likeCount", 0)},
                }
            )

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            return comments
