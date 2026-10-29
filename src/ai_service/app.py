"""AI worker: scores the sentiment of each comment and passes the results on.

Reads:  analysis queue     {job_id, interval_timestamp, comments: [str, ...]}
Writes: aggregation queue  {job_id, interval_timestamp, results: [AnalysisOutput, ...]}

Run with: python -m src.ai_service.app
"""
from functools import lru_cache, partial
from typing import Any, Callable, Sequence

import structlog

from src.common.config import AiSettings, get_settings
from src.common.queue import publish
from src.common.worker import run_worker
from src.models import AnalysisOutput

logger = structlog.get_logger()

MODEL_NAME = "tabularisai/multilingual-sentiment-analysis"

# A scorer takes texts and returns one {"label": str, "score": float} per text.
Scorer = Callable[[list[str]], list[dict[str, Any]]]
Publisher = Callable[[str, dict[str, Any]], Any]


@lru_cache
def _sentiment_pipeline():
    """Load the model once, on first use (never at import time)."""
    from transformers import pipeline  # heavy import; only the worker needs it

    return pipeline("sentiment-analysis", model=MODEL_NAME)


def model_scorer(texts: list[str]) -> list[dict[str, Any]]:
    return _sentiment_pipeline()(texts, batch_size=64, truncation=True)


def score_comments(texts: Sequence[str], scorer: Scorer = model_scorer) -> list[AnalysisOutput]:
    if not texts:
        return []
    return [
        AnalysisOutput(text="", sentiment=result["label"], confidence=result["score"])
        for result in scorer(list(texts))
    ]


def handle_analysis(
    payload: dict[str, Any],
    *,
    publish_to: Publisher,
    next_queue: str,
    scorer: Scorer = model_scorer,
) -> None:
    metadata = {k: v for k, v in payload.items() if k != "comments"}
    log = logger.bind(job_id=metadata.get("job_id"))

    results = score_comments(payload["comments"], scorer)
    if not results:
        log.warning("no_comments_to_score")
        return

    publish_to(next_queue, {**metadata, "results": [r.model_dump() for r in results]})
    log.info("comments_scored", count=len(results))


def main() -> None:
    settings = get_settings(AiSettings)
    _sentiment_pipeline()  # load the model before taking any messages
    handler = partial(handle_analysis, publish_to=publish, next_queue=settings.aggregation_queue)
    # One message at a time: inference is slow, and holding a batch would
    # starve other AI pods once KEDA scales them out.
    run_worker(
        settings.analysis_queue,
        handler,
        port=settings.metrics_port,
        max_busy_seconds=300,  # matches the analysis queue's visibility timeout
        batch_size=1,
    )


if __name__ == "__main__":
    main()
