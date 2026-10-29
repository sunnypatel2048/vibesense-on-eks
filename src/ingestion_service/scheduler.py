from celery import Celery
from redbeat.schedulers import RedBeatScheduler

def configure_celery_beat(app: Celery, redis_url: str):
    """Configure Celery Beat with RedBeat for dynamic scheduling."""
    
    app.conf.beat_scheduler = RedBeatScheduler
    app.conf.redbeat_redis_url = redis_url
    app.conf.beat_max_loop_interval = 60

    app.conf.beat_schedule = {
        "refresh-schedule": {
            "task": "src.ingestion_service.tasks.refresh_dynamic_schedule",
            "schedule": 60,
            "args": ()
        }
    }