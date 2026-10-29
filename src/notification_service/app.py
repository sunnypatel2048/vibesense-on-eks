from datetime import datetime, timezone
from fastapi import FastAPI
import pika
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template
from src.models import Aggregate, Base, MonitoringJobDB
from src.common.config import NotificationSettings, get_settings

settings = get_settings(NotificationSettings)

app = FastAPI(title="Notification Service")
logger = structlog.get_logger()

# DB Setup
engine = create_engine(settings.db_url.get_secret_value())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# Email Template (Jinja2) - using HTML
email_template = Template("""
<!DOCTYPE html>
<html>
<head>
<style>
  .container { font-family: sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; padding: 20px; border-radius: 8px; }
  .header { font-size: 24px; font-weight: bold; color: #0056b3; margin-bottom: 15px; }
  .section-title { font-size: 18px; font-weight: bold; color: #444; margin-top: 20px; margin-bottom: 10px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
  .highlight-card { background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin-bottom: 15px; }
  .sentiment-positive { color: #28a745; font-weight: bold; }
  .sentiment-neutral { color: #ffc107; font-weight: bold; }
  .sentiment-negative { color: #dc3545; font-weight: bold; }
  .footer { font-size: 12px; color: #777; margin-top: 20px; text-align: center; }
</style>
</head>
<body>
  <div class="container">
    <div class="header">🚀 VibeSense Alert</div>
    <p>Hi {{user_full_name}},</p>
    <p>Exciting update! We've analyzed the latest comments on your video <strong>"{{ post_title }}"</strong> for the past {{ interval_duration }} hours up to {{ interval_timestamp }}. Here's what the buzz is saying:</p>

    <div class="section-title">🌟 Interval Highlights</div>
    <div class="highlight-card">
      <p>Average Sentiment: <span class="sentiment-{{ interval_sentiment | lower }}">{{ interval_sentiment }}</span> (Confidence: {{ interval_confidence }})</p>
    </div>

    <div class="section-title">📈 Overall Trends So Far</div>
     <div class="highlight-card">
      <p>Average Sentiment: <span class="sentiment-{{ overall_sentiment | lower }}">{{ overall_sentiment }}</span> (Confidence: {{ overall_confidence }})</p>
    </div>

    <p>Act on these insights—reply to comments or tweak your content to boost engagement!</p>

    <div class="footer">
      <p>Stay tuned for more,<br>The VibeSense Team</p>
      <p>P.S. Questions? Reply to this email.</p>
    </div>
  </div>
</body>
</html>
""")

# API Endpoint for Manual Testing
@app.post("/notify/{job_id}")
async def notify_manual(job_id: str, aggregate: Aggregate):
    """Manual email trigger for testing."""
    # Note: full_name variable is not passed to send_email in the original implementation
    send_email("Test User", "Test Post Title", aggregate, 1.0, datetime.now(timezone.utc).isoformat(), "test@domain.com")
    return {"status": "Email sent"}

# Queue Consumer (Run in Worker Process)
def run_consumer():
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60),
           retry=retry_if_exception_type(pika.exceptions.AMQPError))
    def consume():
        connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url.get_secret_value()))
        channel = connection.channel()
        channel.queue_declare(queue="notification_queue", durable=True)

        def callback(ch, method, properties, body):
            db = SessionLocal()
            try:
                data = json.loads(body)
                aggregate = Aggregate(**data['aggregate'])
                metadata = {k: v for k, v in data.items() if k != 'aggregate'}

                job = db.query(MonitoringJobDB).filter(MonitoringJobDB.job_id == metadata['job_id']).first()
                if not job:
                    raise ValueError("Job not found in DB")

                user_full_name = job.user_full_name
                email = job.email
                post_title = job.post_title
                interval_duration = job.intervals_seconds / 3600
                interval_timestamp = metadata.get('interval_timestamp')

                send_email(user_full_name, post_title, aggregate, interval_duration, interval_timestamp, email)
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("Email sent", job_id=metadata.get('job_id'))
            except Exception as e:
                logger.error("Notification failed", error=str(e))
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            finally:
                db.close()

        channel.basic_consume(queue="notification_queue", on_message_callback=callback)
        logger.info("Notification Consumer started")
        channel.start_consuming()

    consume()

def send_email(user_full_name: str, post_title: str, aggregate: Aggregate, interval_duration: float, interval_timestamp: str, to_email: str):
    """Send formatted email using HTML."""

    def get_confidence_class(confidence):
        if confidence < 0.4:
            return "Uncertain"
        elif confidence < 0.66:
            return "Moderate"
        else:
            return "High"
    
    def get_sentiment_class(score):
        if score < 0.67:
            return "Negative"
        elif score < 1.33:
            return "Neutral"
        else:
            return "Positive"

    # Render HTML content
    msg_content_html = email_template.render(
        user_full_name=user_full_name,
        post_title=post_title,
        interval_duration=interval_duration,
        interval_timestamp=datetime.fromisoformat(interval_timestamp).strftime("%B %d, %Y at %I:%M %p %Z"),
        interval_sentiment=get_sentiment_class(aggregate.interval_sentiment),
        interval_confidence=get_confidence_class(aggregate.interval_confidence),
        overall_sentiment=get_sentiment_class(aggregate.overall_sentiment),
        overall_confidence=get_confidence_class(aggregate.overall_confidence),
    )
    
    # Create the root message and set the headers
    msg = MIMEMultipart('alternative')
    msg['From'] = settings.from_email
    msg['To'] = to_email
    msg['Subject'] = f"🚀 VibeSense Alert: Fresh Insights for Your Video - {post_title}"

    # Attach HTML version
    msg_html_part = MIMEText(msg_content_html, 'html')
    msg.attach(msg_html_part)

    # Send the email
    with smtplib.SMTP(settings.smtp_server, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass.get_secret_value())
        server.send_message(msg)

if __name__ == "__main__":
    # For running the consumer worker: python src/notification_service/app.py
    run_consumer()