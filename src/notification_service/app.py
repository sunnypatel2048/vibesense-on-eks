"""Notification worker: emails the user each interval's sentiment report.

Reads: notification queue  {job_id, interval_timestamp, aggregate: Aggregate}

Run with: python -m src.notification_service.app
"""
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial
from typing import Any, Callable
from uuid import UUID

import structlog
from jinja2 import Template
from sqlalchemy.orm import Session

from src.common.config import NotificationSettings, SmtpSettings, get_settings
from src.common.db import create_session_factory
from src.common.worker import run_worker
from src.models import Aggregate, IntervalResultDB, MonitoringJobDB, interval_time

logger = structlog.get_logger()

SessionFactory = Callable[[], Session]
EmailSender = Callable[[MIMEMultipart], None]

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


def sentiment_label(score: float) -> str:
    """Map the 0..2 sentiment scale to a word."""
    if score < 0.67:
        return "Negative"
    if score < 1.33:
        return "Neutral"
    return "Positive"


def confidence_label(confidence: float) -> str:
    if confidence < 0.4:
        return "Uncertain"
    if confidence < 0.66:
        return "Moderate"
    return "High"


def build_email(
    *,
    from_email: str,
    to_email: str,
    user_full_name: str,
    post_title: str,
    aggregate: Aggregate,
    interval_hours: float,
    interval_timestamp: str,
) -> MIMEMultipart:
    html = email_template.render(
        user_full_name=user_full_name,
        post_title=post_title,
        interval_duration=interval_hours,
        interval_timestamp=datetime.fromisoformat(interval_timestamp).strftime(
            "%B %d, %Y at %I:%M %p %Z"
        ),
        interval_sentiment=sentiment_label(aggregate.interval_sentiment),
        interval_confidence=confidence_label(aggregate.interval_confidence),
        overall_sentiment=sentiment_label(aggregate.overall_sentiment),
        overall_confidence=confidence_label(aggregate.overall_confidence),
    )
    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = f"🚀 VibeSense Alert: Fresh Insights for Your Video - {post_title}"
    msg.attach(MIMEText(html, "html"))
    return msg


def smtp_sender(settings: SmtpSettings) -> EmailSender:
    """Return a function that sends one message over SMTP with STARTTLS."""

    def send(msg: MIMEMultipart) -> None:
        with smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass.get_secret_value())
            server.send_message(msg)

    return send


def handle_notification(
    payload: dict[str, Any],
    *,
    session_factory: SessionFactory,
    send: EmailSender,
    from_email: str,
) -> None:
    aggregate = Aggregate(**payload["aggregate"])
    job_id = payload["job_id"]
    log = logger.bind(job_id=job_id)

    with session_factory() as db:
        job = db.get(MonitoringJobDB, UUID(job_id))
        if job is None:
            # Retries can't fix this; after 5 attempts SQS moves it to the DLQ.
            raise ValueError(f"job {job_id} not found")

        interval = (
            db.query(IntervalResultDB)
            .filter_by(job_id=job.job_id, timestamp=interval_time(payload["interval_timestamp"]))
            .one_or_none()
        )
        if interval is None:
            # Aggregation commits the row before publishing, so this is a data problem.
            raise ValueError(f"interval {payload['interval_timestamp']} not found for job {job_id}")
        if interval.notified_at is not None:
            log.info("already_notified")
            return

        msg = build_email(
            from_email=from_email,
            to_email=job.email,
            user_full_name=job.user_full_name,
            post_title=job.post_title,
            aggregate=aggregate,
            interval_hours=job.intervals_seconds / 3600,
            interval_timestamp=payload["interval_timestamp"],
        )

        # Send, then record it. A crash between the two means a duplicate email
        # on retry; the reverse order would mean a lost one. Exactly-once isn't
        # possible, so we choose at-least-once with a tiny duplicate window.
        send(msg)
        interval.notified_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

    log.info("email_sent")


def main() -> None:
    settings = get_settings(NotificationSettings)

    handler = partial(
        handle_notification,
        session_factory=create_session_factory(settings),
        send=smtp_sender(settings),
        from_email=settings.from_email,
    )
    run_worker(settings.notification_queue, handler, port=settings.metrics_port, max_busy_seconds=60)


if __name__ == "__main__":
    main()
