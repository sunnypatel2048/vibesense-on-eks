from src.ai_service.app import handle_analysis, score_comments


def fake_scorer(texts):
    return [{"label": "Positive", "score": 0.9} for _ in texts]


def test_score_comments_maps_model_output():
    results = score_comments(["great video", "love it"], fake_scorer)
    assert [(r.sentiment, r.confidence) for r in results] == [("Positive", 0.9)] * 2


def test_score_comments_skips_the_model_for_no_input():
    def must_not_run(_texts):
        raise AssertionError("model called with no comments")

    assert score_comments([], must_not_run) == []


def test_handler_keeps_metadata_and_publishes_results(published):
    payload = {"job_id": "j1", "interval_timestamp": "2026-10-29T10:00:00Z", "comments": ["nice"]}

    handle_analysis(payload, publish_to=published, next_queue="agg", scorer=fake_scorer)

    [(queue, sent)] = published.calls
    assert queue == "agg"
    assert sent["job_id"] == "j1"
    assert sent["interval_timestamp"] == "2026-10-29T10:00:00Z"
    assert "comments" not in sent
    assert sent["results"] == [{"text": "", "sentiment": "Positive", "confidence": 0.9}]


def test_handler_publishes_nothing_for_an_empty_batch(published):
    handle_analysis({"job_id": "j1", "comments": []}, publish_to=published, next_queue="agg", scorer=fake_scorer)
    assert published.calls == []
