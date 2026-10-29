from fastapi import FastAPI
from celery import Celery
import structlog
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.ingestion_service.scheduler import configure_celery_beat
from src.common.config import IngestionSettings, get_settings

settings = get_settings(IngestionSettings)


app = FastAPI(title="Data Ingestion Service")
logger = structlog.get_logger()

# Celery setup
celery_app = Celery(
    'ingestion',
    broker=settings.rabbitmq_url.get_secret_value(),
    backend=settings.redis_url.get_secret_value(),
    include=['src.ingestion_service.tasks']
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

configure_celery_beat(celery_app, redis_url=settings.redis_url.get_secret_value())

# Database setup
engine = create_engine(settings.db_url.get_secret_value())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# API Endpoints
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/ingest/{job_id}")
async def ingest_manual(job_id: str):
    """Manual trigger for testing."""
    from .tasks import process_job
    process_job.delay({"job_id": job_id, "post_id": "dQw4w9WgXcQ"}) # Mock post_id
    return {"status": f"Job {job_id} queued for ingestion."}




## how will we handle data ingestion triggers after every intervals?
## need to add data to monitoring jobs table when message gets pickedup.