"""News-tone models. Both expose `name` and `score_many(texts) -> list[Sentiment]`."""
import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_model():
    """The model named by settings.SENTIMENT_MODEL, falling back to the lexicon if FinBERT's
    dependencies are not installed. Returns None if no model is available at all."""
    if settings.SENTIMENT_MODEL == "finbert":
        try:
            from .finbert import FinBertModel
            return FinBertModel()
        except Exception as exc:  # ImportError without torch, OSError if weights can't load
            logger.warning("finbert unavailable, falling back to lexicon err=%s", exc)
    from .lexicon import default_model
    return default_model()


# What each model is and how well it measured. Numbers come from `python scripts/eval_sentiment.py`
# (full output in docs/SENTIMENT_EVAL.md); update them only from a new run of that script.
MODEL_CARDS = {
    "lexicon-lm": {
        "name": "Word-list model (Loughran-McDonald finance dictionary)",
        "how": "Counts finance-specific positive and negative words in each headline, with simple negation.",
        "measured": "On 2,388 finance-news tweets it was never tuned on: accuracy 0.601, macro-F1 0.460 "
                    "(always answering 'neutral' scores 0.656 / 0.264).",
        "caveat": "Reads words without context: it found only 17% of bullish tweets "
                  "(e.g. 'revenue jumps 75%' has no positive word) and scores 'narrows its loss' as bearish.",
    },
    "finbert": {
        "name": "FinBERT (ProsusAI/finbert, BERT fine-tuned on financial news)",
        "how": "A language model reads each headline in context and picks positive, negative or neutral.",
        "measured": "On 2,388 finance-news tweets it was never trained on: accuracy 0.716, macro-F1 0.660 "
                    "(always answering 'neutral' scores 0.656 / 0.264).",
        "caveat": "Still misses 40% of bullish tweets, and is about 20-30 ms per headline on CPU "
                  "versus ~5 µs for the word list.",
    },
}


def model_card(name: str | None) -> dict | None:
    return MODEL_CARDS.get(name) if name else None
