import pytest

from src.utils import parse_youtube_video_id


def test_parse_valid_youtube_video_id():
    assert parse_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == "dQw4w9WgXcQ"

def test_parse_invalid_youtube_video_id():
    with pytest.raises(ValueError):
        parse_youtube_video_id("https://www.notyoutube.com/watch?v=dQw4w9WgXcQ")
    with pytest.raises(ValueError):
        parse_youtube_video_id("https://www.youtube.com/watch?v=")
    with pytest.raises(ValueError):
        parse_youtube_video_id("https://youtu.be/")
    with pytest.raises(ValueError):
        parse_youtube_video_id("invalid_url")