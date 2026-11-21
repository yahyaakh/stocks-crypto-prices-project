"""Headline sentiment with the Loughran-McDonald (LM) finance word lists.

Rule (fixed in advance, not tuned on any evaluation set):
    score = (#positive - #negative) / (#positive + #negative)      None if no sentiment words
    label = bullish if #pos > #neg, bearish if #neg > #pos, else neutral

Negation follows Loughran & McDonald (2011): a positive word with one of
{no, not, none, neither, never, nobody} in the three preceding words counts as negative.
LM did not negate negative words, so neither do we.

Known weakness (useful to say out loud): the lists were built for 10-K filings, so words are
counted without context. "Company narrows its loss" scores bearish because "loss" is negative.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

NEGATIONS = frozenset({"no", "not", "none", "neither", "never", "nobody"})
NEGATION_WINDOW = 3
_TOKEN = re.compile(r"[a-z]+")

BULLISH, BEARISH, NEUTRAL = "bullish", "bearish", "neutral"


@dataclass(frozen=True)
class Sentiment:
    label: str                 # bullish / neutral / bearish
    score: float | None        # -1 (bearish) .. +1 (bullish); None = no signal
    model: str
    positive: int | None = None  # lexicon only: matched word counts
    negative: int | None = None

    def as_dict(self) -> dict:
        return {"label": self.label, "score": self.score, "model": self.model}


class LexiconModel:
    name = "lexicon-lm"

    def __init__(self, positive: set[str], negative: set[str]):
        self.positive = frozenset(positive)
        self.negative = frozenset(negative)

    @classmethod
    def from_file(cls, path: Path) -> "LexiconModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(set(data["positive"]), set(data["negative"]))

    def score(self, text: str | None) -> Sentiment:
        tokens = _TOKEN.findall((text or "").lower())
        pos = neg = 0
        for i, tok in enumerate(tokens):
            if tok in self.positive:
                if NEGATIONS.intersection(tokens[max(0, i - NEGATION_WINDOW):i]):
                    neg += 1
                else:
                    pos += 1
            elif tok in self.negative:
                neg += 1
        total = pos + neg
        label = BULLISH if pos > neg else BEARISH if neg > pos else NEUTRAL
        return Sentiment(label, round((pos - neg) / total, 3) if total else None, self.name, pos, neg)

    def score_many(self, texts: list[str]) -> list[Sentiment]:
        return [self.score(t) for t in texts]


@lru_cache(maxsize=1)
def default_model() -> LexiconModel | None:
    """The lexicon from settings.SENTIMENT_LEXICON_PATH, or None if it hasn't been fetched.
    Missing data degrades to "no sentiment" rather than breaking the news pages."""
    path = Path(settings.SENTIMENT_LEXICON_PATH)
    if not path.exists():
        logger.warning("sentiment lexicon missing path=%s (run scripts/fetch_sentiment_data.py lexicon)", path)
        return None
    return LexiconModel.from_file(path)
