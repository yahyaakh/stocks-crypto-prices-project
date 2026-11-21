"""Headline sentiment with FinBERT (ProsusAI/finbert): BERT further trained on financial text and
fine-tuned on Financial PhraseBank. Optional: needs `pip install -r requirements-finbert.txt`.

    label = the most likely of positive / negative / neutral  (mapped to bullish / bearish / neutral)
    score = P(positive) - P(negative), in [-1, 1]

The model revision is pinned: the Hugging Face repo can change under the same name, and a silent
weight update would make earlier evaluation numbers meaningless.
"""
from __future__ import annotations

import logging
import time

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from .lexicon import BEARISH, BULLISH, NEUTRAL, Sentiment

logger = logging.getLogger(__name__)

MODEL_ID = "ProsusAI/finbert"
REVISION = "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
MAX_TOKENS = 64      # headlines are short; truncating caps the worst-case latency
BATCH_SIZE = 32
_TO_OURS = {"positive": BULLISH, "negative": BEARISH, "neutral": NEUTRAL}


class FinBertModel:
    name = "finbert"

    def __init__(self, model_id: str = MODEL_ID, revision: str = REVISION):
        t0 = time.perf_counter()
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_id, revision=revision, use_safetensors=True).eval()
        # Read the label order from the model config instead of assuming it.
        id2label = {i: lab.lower() for i, lab in self.model.config.id2label.items()}
        self._labels = [_TO_OURS[id2label[i]] for i in range(len(id2label))]
        self._pos = self._labels.index(BULLISH)
        self._neg = self._labels.index(BEARISH)
        logger.info("finbert loaded revision=%s ms=%.0f", revision[:8], (time.perf_counter() - t0) * 1e3)

    @torch.inference_mode()
    def score_many(self, texts: list[str]) -> list[Sentiment]:
        out: list[Sentiment] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = [t or "" for t in texts[i:i + BATCH_SIZE]]
            enc = self.tokenizer(batch, padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
            probs = torch.softmax(self.model(**enc).logits, dim=-1)
            for p in probs.tolist():
                best = max(range(len(p)), key=p.__getitem__)
                out.append(Sentiment(self._labels[best], round(p[self._pos] - p[self._neg], 3), self.name))
        return out

    def score(self, text: str) -> Sentiment:
        return self.score_many([text])[0]
