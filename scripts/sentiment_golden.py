"""Record, or check, the AI model's output on a fixed set of comments.

Guards ML dependency upgrades (torch, transformers, the model revision): an
upgrade only ships if every label matches the recorded "golden" output and every
score is within TOLERANCE. Run it inside the ai image, with no network, so it
tests exactly what will be deployed:

  # record (before an upgrade)
  docker run --rm --network none \
    -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/tests/fixtures:/app/tests/fixtures" \
    vibesense-ai:dev python -m scripts.sentiment_golden --write

  # check (after rebuilding with the upgrade)
  ... same command with --check
"""
import argparse
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

from src.ai_service.app import MODEL_NAME, score_comments

GOLDEN = Path("tests/fixtures/sentiment_golden.json")
TOLERANCE = 0.02

SAMPLES = [
    # English: clear sentiment
    "This is the best video I've watched all year, thank you!",
    "Absolutely terrible. I want those ten minutes of my life back.",
    "The video is 12 minutes long and was uploaded on Tuesday.",
    "Pretty good overall, though the audio was a bit quiet.",
    "I don't hate it, but I wouldn't watch it again.",
    "Wow, another 'tutorial' that skips every important step. Great job.",
    # What ingestion actually sends: spaCy-cleaned, lower-cased, no stop words
    "love channel great content",
    "worst explanation confusing waste time",
    # Other languages (the model is multilingual)
    "¡Me encanta este canal, sigue así!",
    "Je n'ai rien compris, c'était vraiment nul.",
    "Das Video ist okay, nichts Besonderes.",
    "यह वीडियो बहुत अच्छा है, धन्यवाद!",
    "この動画は本当に素晴らしいです。",
    "Questo video è noioso e troppo lungo.",
    # Edge cases
    "😍😍😍",
    "👎",
    "ok",
    "First!",
    "Check out my channel http://example.com for more",
    " ".join(["This part was great but the ending ruined everything."] * 60),  # truncation
]


def environment() -> dict:
    hub = Path(os.environ.get("HF_HOME", "~/.cache/huggingface")).expanduser() / "hub"
    ref = hub / f"models--{MODEL_NAME.replace('/', '--')}" / "refs" / "main"
    return {
        "model": MODEL_NAME,
        "model_revision": ref.read_text().strip() if ref.exists() else os.environ.get("MODEL_REVISION", "unknown"),
        "torch": version("torch"),
        "transformers": version("transformers"),
    }


def score() -> list[dict]:
    return [
        {"text": text[:80], "label": r.sentiment, "score": round(r.confidence, 4)}
        for text, r in zip(SAMPLES, score_comments(SAMPLES))
    ]


def write() -> int:
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps({"recorded_with": environment(), "results": score()}, indent=2, ensure_ascii=False) + "\n")
    print(f"Recorded {len(SAMPLES)} results to {GOLDEN} with {environment()}")
    return 0


def check() -> int:
    golden = json.loads(GOLDEN.read_text())
    expected, actual = golden["results"], score()
    print(f"Golden recorded with: {golden['recorded_with']}")
    print(f"Checking with:        {environment()}\n")

    failures = 0
    for want, got in zip(expected, actual, strict=True):
        label_ok = want["label"] == got["label"]
        delta = abs(want["score"] - got["score"])
        ok = label_ok and delta <= TOLERANCE
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {want['label']:>13} -> {got['label']:<13} "
              f"Δscore {delta:.4f}  {want['text'][:50]}")

    print(f"\n{len(expected) - failures}/{len(expected)} match (labels equal, scores within {TOLERANCE})")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="record the golden file")
    mode.add_argument("--check", action="store_true", help="compare against the golden file")
    args = parser.parse_args()
    sys.exit(write() if args.write else check())
