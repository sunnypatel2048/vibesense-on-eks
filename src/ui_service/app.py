"""VibeSense web UI: a single form that starts monitoring a YouTube video.

Run with: python -m streamlit run src/ui_service/app.py
"""
import streamlit as st
import structlog

from src.common.config import UiSettings, get_settings
from src.common.db import create_session_factory
from src.common.queue import publish
from src.common.scheduler import get_scheduler
from src.ingestion_service.youtube_fetcher import get_video_title
from src.ui_service.jobs import FormError, available_plans, create_job, humanize, validate_request

logger = structlog.get_logger()

st.set_page_config(page_title="VibeSense", page_icon="📈", layout="centered")


@st.cache_resource
def session_factory():
    """One engine per process, not one per Streamlit rerun."""
    return create_session_factory(get_settings(UiSettings))


settings = get_settings(UiSettings)
plans = available_plans(settings.demo_mode)

st.title("VibeSense")
st.caption("Get an email report on how viewers feel about a YouTube video.")

with st.form("monitor"):
    video_url = st.text_input("YouTube video link", placeholder="https://www.youtube.com/watch?v=…")
    full_name = st.text_input("Your name", max_chars=50)
    email = st.text_input("Email", max_chars=100)
    plan = st.radio(
        "Plan",
        plans,
        format_func=lambda p: p.label,
        captions=[p.description for p in plans],
        horizontal=True,
    )
    submitted = st.form_submit_button("Start monitoring", type="primary", use_container_width=True)

if submitted:
    try:
        request = validate_request(full_name, email, video_url)
    except FormError as error:
        st.error(error.message)
        st.stop()

    with st.spinner("Checking the video…"):
        try:
            title = get_video_title(request.video_id)
        except Exception:
            logger.exception("title_lookup_failed", video_id=request.video_id)
            st.error("Couldn't reach YouTube just now. Please try again in a minute.")
            st.stop()

    if title is None:
        st.error("That video is private or doesn't exist.")
        st.stop()

    with st.spinner("Starting monitoring…"):
        try:
            job = create_job(
                request,
                title=title,
                plan=plan,
                session_factory=session_factory(),
                scheduler=get_scheduler(),
                publish_to=publish,
                ingest_queue=settings.ingest_queue,
            )
        except Exception:
            logger.exception("job_creation_failed")
            st.error("Something went wrong starting monitoring. Please try again.")
            st.stop()

    every = humanize(plan.interval_seconds)
    first = "First report in a few minutes" if job.first_report_now else f"First report in {every}"
    st.success(
        f"**Monitoring “{title}”**  \n"
        f"{first}, then every {every} until "
        f"{job.ends_at:%a, %b %-d at %-I:%M %p} UTC.  \n"
        f"Reports go to {request.email}.",
        icon="✅",
    )
