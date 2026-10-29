from urllib.parse import urlparse, parse_qs

def parse_youtube_video_id(url: str) -> str:
    """
    Parses the video ID from a YouTube URL.
    Example: "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -> "dQw4w9WgXcQ"
    Raises ValueError for invalid URLs.
    """
    try:
        parsed_url = urlparse(url)
        if parsed_url.hostname not in ['www.youtube.com', 'youtube.com', 'youtu.be']:
            raise ValueError("Invalid YouTube domain")
        
        if parsed_url.path == '/watch':
            query = parse_qs(parsed_url.query)
            if 'v' not in query:
                raise ValueError("No video ID found in query parameters")
            return query['v'][0]
        
        elif parsed_url.hostname == 'youtu.be':
            video_id = parsed_url.path.lstrip('/')
            if not video_id:
                raise ValueError("No video ID found in short URL")
            return video_id
        
        else:
            raise ValueError("Unsupported YouTube URL format")
    
    except Exception as e:
        raise ValueError(f"Invalid YouTube URL: {e}")