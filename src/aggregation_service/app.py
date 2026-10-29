from fastapi import FastAPI
import pika
import json
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog
import pandas as pd
import scipy.stats
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from src.models import Aggregate, IntervalResultDB, AnalysisOutput
from src.models import Base
from src.common.config import AggregationSettings, get_settings

settings = get_settings(AggregationSettings)

app = FastAPI(title="Analytics Aggregation Service")
logger = structlog.get_logger()

# DB Setup
engine = create_engine(settings.db_url.get_secret_value())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# API Endpoint for testing
@app.get("/summary/{job_id}", response_model=Aggregate)
async def get_summary(job_id: str):
    """Retrieve aggregate summary for a job."""
    db = SessionLocal()
    try:
        results = db.query(IntervalResultDB).filter(IntervalResultDB.job_id == job_id).all()
        if not results:
            raise ValueError("No results found for the job")
        df = pd.DataFrame([r.model_dump() for r in results])
        overall_sentiment = df['avg_sentiment'].mean()
        ci = scipy.stats.norm.interval(0.95, loc=overall_sentiment, scale=df['avg_sentiment'].std()/len(df)**0.5)
        summary = " ".join(df['summary'].tolist())
        return Aggregate(
            interval_sentiment=results[-1].avg_sentiment if results else 0.0,
            overall_sentiment=overall_sentiment,
            ci=ci,
            summary=summary)
    finally:
        db.close()

# Queue Consumer (Run in Worker Process)
def run_consumer():
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60),
           retry=retry_if_exception_type(pika.exceptions.AMQPError))
    def consume():
        connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url.get_secret_value()))
        channel = connection.channel()
        channel.queue_declare(queue="aggregation_queue", durable=True)
        channel.queue_declare(queue="notification_queue", durable=True)

        def callback(ch, method, properties, body):
            db = SessionLocal()
            try:
                data = json.loads(body)
                results = [AnalysisOutput(**r) for r in data['results']]
                metadata = {k: v for k, v in data.items() if k != 'results'}

                # Aggregate Interval
                df = pd.DataFrame([r.model_dump() for r in results])
                mapping = {
                    'Very Negative': 0,
                    'Negative': 0,
                    'Neutral': 1,
                    'Positive': 2,
                    'Very Positive': 2
                }
                df['sentiment_numeric'] = df['sentiment'].map(mapping)
                avg_sentiment = avg_sentiment = (df['sentiment_numeric'] * df['confidence']).sum() / df['confidence'].sum() # Weighted average
                avg_confidence = df['confidence'].mean()

                # Store in DB
                interval_result = IntervalResultDB(
                    job_id=metadata['job_id'],
                    timestamp=datetime.fromisoformat(metadata['interval_timestamp']),
                    avg_sentiment=avg_sentiment,
                    avg_confidence=avg_confidence,
                )
                db.add(interval_result)
                db.commit()
                
                sentiment = db.query(IntervalResultDB).filter(IntervalResultDB.job_id == metadata['job_id']).all()
                overall_sentiment = sum([s.avg_sentiment for s in sentiment]) / len(sentiment)
                overall_confidence = sum([s.avg_confidence for s in sentiment]) / len(sentiment)

                # Publish to Notification
                payload = {**metadata, 'aggregate': Aggregate(
                    interval_sentiment=avg_sentiment,
                    interval_confidence=avg_confidence,
                    overall_sentiment=overall_sentiment,
                    overall_confidence=overall_confidence
                ).model_dump()}
                ch.basic_publish(exchange='', routing_key="notification_queue", body=json.dumps(payload))
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("Aggregated and published", metadata=metadata)
            except Exception as e:
                logger.error("Aggregation failed", error=str(e))
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            finally:
                db.close()

        channel.basic_consume(queue="aggregation_queue", on_message_callback=callback)
        logger.info("Aggregation Consumer started")
        channel.start_consuming()

    consume()

if __name__ == "__main__":
    # For running the consumer worker: python src/aggregation_service/app.py
    run_consumer()