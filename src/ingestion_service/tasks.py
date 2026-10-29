from .app import celery_app
from src.models import MonitoringJobDB, CommentData
from src.ingestion_service.youtube_fetcher import fetch_comments
from src.ingestion_service.preprocessor import preprocess_text
from redbeat import RedBeatSchedulerEntry
import pika
import json
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import structlog
from datetime import datetime, timedelta, timezone
from src.common.config import IngestionSettings, get_settings

settings = get_settings(IngestionSettings)

engine = create_engine(settings.db_url.get_secret_value())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
logger = structlog.get_logger()

@celery_app.task(name='src.ingestion_service.tasks.process_job_task')
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60))
def process_job(job_data: dict):
    logger.info("Processing job", job_id=job_data['job_id'])
    try:
        # Get DB session
        db = SessionLocal()

        job = db.query(MonitoringJobDB).filter(MonitoringJobDB.job_id == job_data['job_id']).first()
        if job:
            expiration_time_naive = job.created_at + timedelta(seconds=job.total_duration_seconds)
            expiration_time_aware = expiration_time_naive.replace(tzinfo=timezone.utc)

            if expiration_time_aware <= datetime.now(timezone.utc):
                logger.info("Job expired, skipping ingestion and deleting schedule entry.", job_id=job_data['job_id'])

                # Delete RedBeat schedule entry
                entry_name = f"redbeat:ingest-job-{job.job_id}"
                try:
                    entry = RedBeatSchedulerEntry.from_key(entry_name, app=celery_app)
                    entry.delete()
                    logger.info("Deleted RedBeat schedule entry", job_id=job_data['job_id'], entry_name=entry_name)
                except KeyError:
                    logger.warning("RedBeat schedule entry not found for deletion", job_id=job_data['job_id'], entry_name=entry_name)
                return

            last_fetched_at = job.last_fetched_at if job and job.last_fetched_at else None

            # Fetch all comments
            all_comments = fetch_comments(job_data['post_id'])
            
            # Filter new comments (published_at > last_fetched_at)
            if last_fetched_at:
                new_comments = [c for c in all_comments if datetime.fromisoformat(c['published_at'][:-1] + '+00:00') > last_fetched_at.replace(tzinfo=timezone.utc)]
            else:
                new_comments = all_comments

            if not new_comments:
                logger.info("No new comments", job_id=job_data['job_id'])
                return

            # Preprocess comments
            preprocessed = [preprocess_text(c['text']) for c in new_comments]

            # Metadata for tracibility
            interval_timestamp = max(c['published_at'] for c in new_comments)
            metadata = {
                'job_id': job_data['job_id'],
                'interval_timestamp': interval_timestamp
            }

            # Publish batches to RabbitMQ
            connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url.get_secret_value()))
            channel = connection.channel()
            channel.queue_declare(queue='analysis_queue', durable=True)
            payload = { **metadata, 'comments': preprocessed }
            channel.basic_publish(
                exchange='',
                routing_key='analysis_queue',
                body=json.dumps(payload)
            )
            connection.close()

            new_last_fetched_at = max(datetime.fromisoformat(c['published_at'][:-1] + '+00:00') for c in new_comments) if new_comments else datetime.now(timezone.utc)
            job.last_fetched_at = new_last_fetched_at
            db.commit()
            db.close()

            logger.info("Data ingested and published", job_id=job_data['job_id'])
        else:
            logger.warning("Job not found", job_id=job_data['job_id'])
            entry_name = f"redbeat:ingest-job-{job_data['job_id']}"
            try:
                entry = RedBeatSchedulerEntry.from_key(entry_name, app=celery_app)
                entry.delete()
                logger.info("Deleted RedBeat schedule entry for non-existent job", job_id=job_data['job_id'], entry_name=entry_name)
            except KeyError:
                logger.warning("RedBeat schedule entry not found for deletion", job_id=job_data['job_id'], entry_name=entry_name)
    except Exception as e:
        logger.error("Ingestion failed", job_id=job_data['job_id'], error=str(e))
        raise

@celery_app.task(name='src.ingestion_service.tasks.refresh_dynamic_schedule')
def refresh_dynamic_schedule():
    """Task to add unscheduled jobs to RedBeat dynamically."""
    
    logger.info("Refreshing dynamic schedule")
    db = SessionLocal()
    try:
        jobs = db.query(MonitoringJobDB).filter(MonitoringJobDB.is_scheduled == False).all()
        for job in jobs:
            logger.info("Scheduling job", job_id=job.job_id)
            # Only schedule if job is still active (within total_duration)
            expiration_time_naive = job.created_at + timedelta(seconds=job.total_duration_seconds)
            expiration_time_aware = expiration_time_naive.replace(tzinfo=timezone.utc)
            if expiration_time_aware > datetime.now(timezone.utc):
                interval_seconds = job.intervals_seconds
                # Add to RedBeat (persistent schedule in Redis)
                entry_name = f"ingest-job-{job.job_id}"
                RedBeatSchedulerEntry(
                    name=entry_name,
                    task="src.ingestion_service.tasks.process_job_task",
                    schedule=interval_seconds,
                    args=[{"job_id": str(job.job_id), "post_id": job.post_id}],
                    app=celery_app
                ).save()
                
                job.is_scheduled = True
                db.commit()
                logger.info("Job scheduled", job_id=job.job_id, interval_seconds=interval_seconds)
    finally:
        db.close()

    logger.info("Dynamic schedule refresh complete")