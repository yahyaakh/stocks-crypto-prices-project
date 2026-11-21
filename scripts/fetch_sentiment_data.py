#!/usr/bin/env python3
"""Download the data the sentiment models need. Standard library only, every file pinned by SHA-256.

    python scripts/fetch_sentiment_data.py lexicon      # -> data/sentiment/lm_words.json  (runtime, ~60 KB)
    python scripts/fetch_sentiment_data.py phrasebank   # -> data/sentiment/FinancialPhraseBank-v1.0/  (evaluation)
    python scripts/fetch_sentiment_data.py tweets       # -> data/sentiment/twitter_fin_news_valid.csv  (evaluation)

Nothing here is committed to git (data/ is ignored):
- Lexicon: the Loughran-McDonald finance word lists (2014 release: 354 positive, 2355 negative words),
  read from the MIT-licensed `pysentiment2==0.1.1` wheel on PyPI. The word lists themselves are
  free for academic use; see https://sraf.nd.edu/loughranmcdonald-master-dictionary/
- Financial PhraseBank v1.0 (Malo et al., 2014), CC BY-NC-SA 3.0, from Hugging Face.
- Twitter Financial News Sentiment, validation split (zeroshot, 2022), MIT, from Hugging Face.
  FinBERT was fine-tuned on PhraseBank, so this is the clean test set for comparing the two models.
"""
import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sentiment"

LEXICON_WHEEL = {
    "url": "https://files.pythonhosted.org/packages/py3/p/pysentiment2/pysentiment2-0.1.1-py3-none-any.whl",
    "sha256": "d0ff7a0b702654baeff6a6bec231e56ba4c4c9bc9ad4730856e8ca69335450c7",
    "member": "pysentiment2/static/LM.csv",
}
PHRASEBANK_ZIP = {
    "url": "https://huggingface.co/datasets/takala/financial_phrasebank/resolve/main/data/FinancialPhraseBank-v1.0.zip",
    "sha256": "0e1a06c4900fdae46091d031068601e3773ba067c7cecb5b0da1dcba5ce989a6",
}

TWEETS_VALID = {
    "url": "https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment/resolve/main/sent_valid.csv",
    "sha256": "31ea8274c98b52212daa68f2fb962811bf1913c1efe51b99765c8e2311806de6",
}


def _download(url: str, sha256: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        sys.exit(f"checksum mismatch for {url}\n  expected {sha256}\n  got      {got}")
    return data


def fetch_lexicon(out: Path) -> None:
    wheel = _download(LEXICON_WHEEL["url"], LEXICON_WHEEL["sha256"])
    with zipfile.ZipFile(io.BytesIO(wheel)) as zf:
        rows = list(csv.DictReader(io.TextIOWrapper(zf.open(LEXICON_WHEEL["member"]), encoding="utf-8")))
    # The Positive/Negative columns hold the year a word was added (0 = not in the list).
    lexicon = {
        "source": "Loughran-McDonald sentiment word lists (2014 release) via pysentiment2==0.1.1",
        "positive": sorted(r["Word"].lower() for r in rows if int(r["Positive"])),
        "negative": sorted(r["Word"].lower() for r in rows if int(r["Negative"])),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lexicon), encoding="utf-8")
    print(f"wrote {out}: {len(lexicon['positive'])} positive, {len(lexicon['negative'])} negative words")


def fetch_phrasebank(out_dir: Path) -> None:
    data = _download(PHRASEBANK_ZIP["url"], PHRASEBANK_ZIP["sha256"])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [m for m in zf.namelist() if m.startswith("FinancialPhraseBank-v1.0/") and not m.endswith("/")]
        zf.extractall(out_dir, members=members)
    print(f"extracted {len(members)} files to {out_dir / 'FinancialPhraseBank-v1.0'}")


def fetch_tweets(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_download(TWEETS_VALID["url"], TWEETS_VALID["sha256"]))
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["lexicon", "phrasebank", "tweets", "all"])
    ap.add_argument("--lexicon-out", type=Path, default=OUT_DIR / "lm_words.json")
    args = ap.parse_args()
    if args.what in ("lexicon", "all"):
        fetch_lexicon(args.lexicon_out)
    if args.what in ("phrasebank", "all"):
        fetch_phrasebank(OUT_DIR)
    if args.what in ("tweets", "all"):
        fetch_tweets(OUT_DIR / "twitter_fin_news_valid.csv")


if __name__ == "__main__":
    main()
