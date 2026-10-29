from functools import lru_cache


@lru_cache
def _nlp():
    """Load the spaCy model once, on first use (never at import time)."""
    import spacy

    return spacy.load("en_core_web_sm")


def preprocess_text(text: str) -> str:
    """Lower-case the text and drop stop words, URLs and punctuation."""
    doc = _nlp()(text)
    return " ".join(
        token.text.lower()
        for token in doc
        if not token.is_stop and not token.like_url and not token.is_punct
    )
