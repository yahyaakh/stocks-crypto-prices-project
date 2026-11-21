#!/usr/bin/env python3
"""Evaluate a news-tone model and print a markdown report.

    python scripts/fetch_sentiment_data.py all
    python scripts/eval_sentiment.py --model lexicon
    python scripts/eval_sentiment.py --model finbert        # needs requirements-finbert.txt

Reports accuracy AND macro-F1: most sentences are neutral, so "always neutral" already gets
~61-66% accuracy (shown as the baseline row). Rows where the model was trained on that data are
marked CONTAMINATED: those numbers overstate how well it works on unseen text.
"""
import argparse
import csv
import json
import platform
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "myproject"))
DATA = ROOT / "data" / "sentiment"
CLASSES = ("bullish", "neutral", "bearish")
URL = re.compile(r"https?://\S+")


def _phrasebank(filename):
    def load():
        texts, labels = [], []
        mapping = {"positive": "bullish", "neutral": "neutral", "negative": "bearish"}
        for line in (DATA / "FinancialPhraseBank-v1.0" / filename).read_text(encoding="latin-1").splitlines():
            if line.strip():
                text, _, label = line.rpartition("@")  # "<sentence>@<label>"
                texts.append(text.strip())
                labels.append(mapping[label.strip()])
        return texts, labels
    return load


def _tweets():
    # Labels per the dataset's meta file: 0 Bearish, 1 Bullish, 2 Neutral. URLs are stripped
    # (identically for every model) because "https://t.co/..." carries no sentiment.
    mapping = {"0": "bearish", "1": "bullish", "2": "neutral"}
    with open(DATA / "twitter_fin_news_valid.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [URL.sub("", r["text"]).strip() for r in rows], [mapping[r["label"]] for r in rows]


# name -> (loader, description, models trained on it)
DATASETS = {
    "phrasebank-all-agree": (_phrasebank("Sentences_AllAgree.txt"),
                             "Financial PhraseBank, sentences all annotators agree on", {"finbert"}),
    "phrasebank-50-agree": (_phrasebank("Sentences_50Agree.txt"),
                            "Financial PhraseBank, sentences >=50% of annotators agree on", {"finbert"}),
    "tweets-valid": (_tweets, "Twitter Financial News Sentiment, validation split (2022)", set()),
}


def metrics(gold, pred):
    per_class = {}
    for c in CLASSES:
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per_class[c] = {"precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
                        "support": tp + fn}
    return {
        "n": len(gold),
        "accuracy": sum(g == p for g, p in zip(gold, pred)) / len(gold),
        "macro_f1": sum(v["f1"] for v in per_class.values()) / len(CLASSES),
        "per_class": per_class,
        "confusion": {g: {p: sum(1 for a, b in zip(gold, pred) if a == g and b == p) for p in CLASSES} for g in CLASSES},
    }


def build_model(name):
    if name == "lexicon":
        from market.sentiment.lexicon import LexiconModel
        return LexiconModel.from_file(DATA / "lm_words.json"), {}
    from market.sentiment.finbert import REVISION, FinBertModel
    import torch
    return FinBertModel(), {"revision": REVISION, "torch": torch.__version__, "torch_threads": torch.get_num_threads()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["lexicon", "finbert"], default="lexicon")
    ap.add_argument("--datasets", nargs="+", choices=list(DATASETS), default=list(DATASETS))
    ap.add_argument("--json-out", type=Path, help="also write the raw numbers here")
    args = ap.parse_args()

    model, extra = build_model(args.model)
    machine = f"{platform.processor() or platform.machine()} | {platform.platform()} | Python {platform.python_version()}"
    report = {"model": args.model, "machine": machine, **extra, "datasets": {}}

    print(f"# Sentiment evaluation: {args.model}\n")
    print(f"command: `python scripts/eval_sentiment.py --model {args.model}`  \nmachine: {machine}  ")
    for k, v in extra.items():
        print(f"{k}: {v}  ")
    print()
    for name in args.datasets:
        loader, desc, trained_on = DATASETS[name]
        texts, gold = loader()
        t0 = time.perf_counter()
        pred = [s.label for s in model.score_many(texts)]
        secs = time.perf_counter() - t0
        majority = Counter(gold).most_common(1)[0][0]
        m, base = metrics(gold, pred), metrics(gold, [majority] * len(gold))
        contaminated = args.model in trained_on
        report["datasets"][name] = {"model": m, "baseline": base, "baseline_label": majority, "seconds": secs,
                                    "contaminated": contaminated}

        flag = " — **CONTAMINATED: the model was trained on this data**" if contaminated else ""
        print(f"## {desc} (`{name}`, n={m['n']}){flag}\n")
        print("| | accuracy | macro-F1 |\n|---|---|---|")
        print(f"| {args.model} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} |")
        print(f"| always {majority} | {base['accuracy']:.3f} | {base['macro_f1']:.3f} |\n")
        print("| class | precision | recall | F1 | support |\n|---|---|---|---|---|")
        for c, v in m["per_class"].items():
            print(f"| {c} | {v['precision']:.3f} | {v['recall']:.3f} | {v['f1']:.3f} | {v['support']} |")
        print("\n| gold \\ predicted | " + " | ".join(CLASSES) + " |\n|---|" + "---|" * len(CLASSES))
        for g in CLASSES:
            print(f"| {g} | " + " | ".join(str(m["confusion"][g][p]) for p in CLASSES) + " |")
        print(f"\nscored {m['n']} texts in {secs:.3f}s ({secs / m['n'] * 1e6:.1f} µs/text, single run)\n")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
