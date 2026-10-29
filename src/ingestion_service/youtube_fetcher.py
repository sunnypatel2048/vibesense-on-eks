from googleapiclient.discovery import build
from functools import lru_cache
from typing import List, Dict
from datetime import datetime
from src.common.config import YouTubeSettings, get_settings

@lru_cache
def _youtube_client():
    """Build the API client on first use, not at import time."""
    api_key = get_settings(YouTubeSettings).youtube_api_key.get_secret_value()
    return build("youtube", "v3", developerKey=api_key)

def fetch_comments(video_id: str) -> List[Dict]:
    """
    Fetches comments for a video ID with pagination.
    Returns a list of dicts: {'comment_id': str, 'text': str, 'published_at': datetime, 'metrics': dict}
    """
    comments = []
    next_page_token = None

    while True:
        response = _youtube_client().commentThreads().list(
            part="snippet",
            videoId=video_id,
            order="time",
            maxResults=100,
            pageToken=next_page_token
        ).execute()

        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            published_at_str = snippet["publishedAt"]
            published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            comments.append({
                "comment_id": item["id"],
                "text": snippet["textOriginal"],
                "published_at": snippet["publishedAt"],
                "metrics": {
                    "like_count": snippet.get("likeCount", 0)
                }
            })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return comments