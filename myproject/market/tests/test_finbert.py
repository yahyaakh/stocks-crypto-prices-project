"""FinBERT wrapper logic with a fake model (no 438 MB download). Skipped when torch isn't installed,
which is the default: FinBERT is an optional extra (requirements-finbert.txt)."""
import types

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from market.sentiment import finbert  # noqa: E402


class FakeTokenizer:
    def __call__(self, batch, **kw):
        # One "token" per text whose value encodes which logits the fake model returns.
        return {"input_ids": torch.tensor([[len(t)] for t in batch])}


class FakeModel:
    # Deliberately NOT FinBERT's real order, to prove labels are read from config, not assumed.
    config = types.SimpleNamespace(id2label={0: "neutral", 1: "Negative", 2: "POSITIVE"})

    def eval(self):
        return self

    def __call__(self, input_ids):
        # length 1 -> strongly positive, length 2 -> strongly negative, otherwise neutral
        rows = []
        for (n,) in input_ids.tolist():
            rows.append([0.0, 0.0, 9.0] if n == 1 else [0.0, 9.0, 0.0] if n == 2 else [9.0, 0.0, 0.0])
        return types.SimpleNamespace(logits=torch.tensor(rows))


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(finbert.AutoTokenizer, "from_pretrained", lambda *a, **k: FakeTokenizer())
    monkeypatch.setattr(finbert.AutoModelForSequenceClassification, "from_pretrained", lambda *a, **k: FakeModel())
    return finbert.FinBertModel()


def test_labels_follow_model_config(model):
    out = model.score_many(["a", "bb", "ccc"])
    assert [s.label for s in out] == ["bullish", "bearish", "neutral"]
    assert out[0].score > 0.99 and out[1].score < -0.99 and abs(out[2].score) < 0.01
    assert {s.model for s in out} == {"finbert"}


def test_batches_cover_every_text(model, monkeypatch):
    monkeypatch.setattr(finbert, "BATCH_SIZE", 2)
    assert len(model.score_many(["a"] * 5)) == 5


def test_revision_is_pinned():
    assert len(finbert.REVISION) == 40  # a full commit hash, never a branch name like "main"
