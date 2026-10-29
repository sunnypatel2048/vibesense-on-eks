from fastapi import FastAPI
import pika
import json
from transformers import pipeline
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog
from src.models import AnalysisOutput
from src.common.config import AiSettings, get_settings

settings = get_settings(AiSettings)

app = FastAPI(title="AI Service")
logger = structlog.get_logger()

# Load Models
sentiment_pipe = pipeline(
    "sentiment-analysis",
    model="tabularisai/multilingual-sentiment-analysis"
)

# API Endpoint for Sync Testing
@app.post("/analyze/", response_model=List[AnalysisOutput])
async def analyze_text(texts: List[str]):
    """Process text comments for sentiment."""
    return process_comments(texts)

# Queue Consumer (Run in Worker Process)
def run_consumer():
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60),
           retry=retry_if_exception_type(pika.exceptions.AMQPError))
    def consume():
        connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url.get_secret_value()))
        channel = connection.channel()
        channel.queue_declare(queue="analysis_queue", durable=True)
        channel.queue_declare(queue="aggregation_queue", durable=True)

        def callback(ch, method, properties, body):
            try:
                data = json.loads(body)
                comments = data['comments']  # List of texts
                metadata = {k: v for k, v in data.items() if k != 'comments'}
                results = process_comments(comments)
                payload = {**metadata, 'results': [r.model_dump() for r in results]}
                ch.basic_publish(exchange='', routing_key="aggregation_queue", body=json.dumps(payload))
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("Comments processed and published", metadata=metadata)
            except Exception as e:
                logger.error("Processing failed", error=str(e))
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        channel.basic_consume(queue="analysis_queue", on_message_callback=callback)
        logger.info("AI Consumer started")
        channel.start_consuming()

    consume()

def process_comments(texts: List[str]) -> List[AnalysisOutput]:
    """Process comments with AI model."""
    try:
        sent_results = sentiment_pipe(texts, batch_size=64, truncation=True)
        outputs = []
        for sent in sent_results:
            output = AnalysisOutput(
                text="",
                sentiment=sent['label'],
                confidence=sent['score'],
            )
            outputs.append(output)
        return outputs
    except Exception as e:
        logger.error("AI processing failed", error=str(e))
        raise

if __name__ == "__main__":
    # For running the consumer worker: python3 src/ai_service/app.py
    run_consumer()