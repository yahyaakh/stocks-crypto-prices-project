# Headline sentiment: evaluation

Two models label each headline **bullish / neutral / bearish**:

| Model | What it is | Used by |
|---|---|---|
| `lexicon` | Loughran-McDonald finance word lists (2014 release: 354 positive, 2,355 negative words), simple negation as in Loughran & McDonald (2011) | default image |
| `finbert` | [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert) at pinned revision `0bc2ac10`, BERT fine-tuned on Financial PhraseBank | `docker build --build-arg SENTIMENT_MODEL=finbert` |

## Results

Command: `python scripts/fetch_sentiment_data.py all && python scripts/eval_sentiment.py --model {lexicon,finbert}`
Machine: AMD Ryzen 7 7840HS laptop, Windows 11, Python 3.11.9; FinBERT on CPU with torch 2.15.0+cpu, 8 threads, batch 32.
Every number below is from that run; full output (per-class scores and confusion matrices) is further down.

**Clean test set** (neither model was trained or tuned on it): Twitter Financial News Sentiment, validation split, n = 2,388.

| | accuracy | macro-F1 | bullish recall | bearish recall | time per headline |
|---|---|---|---|---|---|
| always "neutral" | 0.656 | 0.264 | 0.000 | 0.000 | – |
| lexicon | 0.601 | 0.460 | 0.171 | 0.501 | 3.9 µs |
| **FinBERT** | **0.716** | **0.660** | **0.602** | **0.752** | 18.9 ms |

**Financial PhraseBank** (Malo et al., 2014):

| | all-agree, n = 2,264: accuracy / macro-F1 | ≥50%-agree, n = 4,846: accuracy / macro-F1 |
|---|---|---|
| always "neutral" | 0.614 / 0.254 | 0.594 / 0.248 |
| lexicon | 0.648 / 0.483 | 0.624 / 0.504 |
| FinBERT | ~~0.972 / 0.963~~ contaminated | ~~0.889 / 0.882~~ contaminated |

## How to read this honestly

- **Accuracy alone misleads.** 61–66% of sentences are neutral, so "always neutral" beats the lexicon's accuracy
  on the tweets (0.656 vs 0.601). Macro-F1 averages the three classes equally and exposes that.
- **FinBERT's PhraseBank numbers are invalid as a quality measure.** Its model card says it was fine-tuned on
  Financial PhraseBank, and its train/test split isn't published, so unseen sentences can't be separated out.
  0.972 mostly measures memory. The tweets set (published 2022, not in FinBERT's listed training data)
  is the fair comparison. Assumption: the model card's training-data statement is complete.
- **No tuning on test data.** The lexicon rule (more positive than negative words → bullish) was fixed before
  looking at any results, and the word list wasn't edited after seeing errors. Doing that would inflate the scores.
- **Single runs, one machine.** Timings are one pass each, not a benchmark with repeats: treat them as order of
  magnitude (microseconds vs tens of milliseconds), not precise figures.
- **Domain shift.** Both test sets are short news sentences or tweets. The app scores live headlines, which are
  similar but not identical; no labelled set of the app's own headlines exists, so live accuracy is unmeasured.

## Live headlines (PONY, 2026-11-20), both models

| headline | lexicon | FinBERT |
|---|---|---|
| Pony.ai Q3 revenue jumps 75% as robotaxi business expands, adjusted loss beats estimates | bearish | bullish (+0.84) |
| Pony AI Q3 Adj. EPS $(0.11) Beats $(0.18) Estimate, Sales $44.574M Beat $39.119M Estimate | bearish | bullish (+0.17) |
| Oracle Stock Is Now Down Almost 70% From its Peak | neutral | bearish (−0.97) |
| Company narrows its loss *(hand-written check)* | bearish | neutral (+0.05) |

The lexicon counts "loss" and misses "jumps"/"beats"; FinBERT reads them in context but still calls a narrowing loss neutral.

---

## Full output: lexicon

command: `python scripts/eval_sentiment.py --model lexicon`  
machine: AMD64 Family 25 Model 116 Stepping 1, AuthenticAMD | Windows-10-10.0.26300-SP0 | Python 3.11.9  

### Financial PhraseBank, sentences all annotators agree on (`phrasebank-all-agree`, n=2264)

| | accuracy | macro-F1 |
|---|---|---|
| lexicon | 0.648 | 0.483 |
| always neutral | 0.614 | 0.254 |

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| bullish | 0.637 | 0.163 | 0.260 | 570 |
| neutral | 0.686 | 0.901 | 0.779 | 1391 |
| bearish | 0.418 | 0.403 | 0.410 | 303 |

| gold \ predicted | bullish | neutral | bearish |
|---|---|---|---|
| bullish | 93 | 400 | 77 |
| neutral | 45 | 1253 | 93 |
| bearish | 8 | 173 | 122 |

scored 2264 texts in 0.011s (5.0 µs/text, single run)

### Financial PhraseBank, sentences >=50% of annotators agree on (`phrasebank-50-agree`, n=4846)

| | accuracy | macro-F1 |
|---|---|---|
| lexicon | 0.624 | 0.504 |
| always neutral | 0.594 | 0.248 |

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| bullish | 0.604 | 0.250 | 0.354 | 1363 |
| neutral | 0.663 | 0.842 | 0.742 | 2879 |
| bearish | 0.410 | 0.424 | 0.417 | 604 |

| gold \ predicted | bullish | neutral | bearish |
|---|---|---|---|
| bullish | 341 | 897 | 125 |
| neutral | 210 | 2425 | 244 |
| bearish | 14 | 334 | 256 |

scored 4846 texts in 0.027s (5.6 µs/text, single run)

### Twitter Financial News Sentiment, validation split (2022) (`tweets-valid`, n=2388)

| | accuracy | macro-F1 |
|---|---|---|
| lexicon | 0.601 | 0.460 |
| always neutral | 0.656 | 0.264 |

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| bullish | 0.370 | 0.171 | 0.233 | 475 |
| neutral | 0.698 | 0.754 | 0.725 | 1566 |
| bearish | 0.365 | 0.501 | 0.422 | 347 |

| gold \ predicted | bullish | neutral | bearish |
|---|---|---|---|
| bullish | 81 | 348 | 46 |
| neutral | 128 | 1181 | 257 |
| bearish | 10 | 163 | 174 |

scored 2388 texts in 0.009s (3.9 µs/text, single run)


## Full output: FinBERT

command: `python scripts/eval_sentiment.py --model finbert`  
machine: AMD64 Family 25 Model 116 Stepping 1, AuthenticAMD | Windows-10-10.0.26300-SP0 | Python 3.11.9  
revision: 0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031  
torch: 2.15.0+cpu  
torch_threads: 8  

### Financial PhraseBank, sentences all annotators agree on (`phrasebank-all-agree`, n=2264) — **CONTAMINATED: the model was trained on this data**

| | accuracy | macro-F1 |
|---|---|---|
| finbert | 0.972 | 0.963 |
| always neutral | 0.614 | 0.254 |

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| bullish | 0.947 | 0.977 | 0.962 | 570 |
| neutral | 0.999 | 0.967 | 0.982 | 1391 |
| bearish | 0.906 | 0.983 | 0.943 | 303 |

| gold \ predicted | bullish | neutral | bearish |
|---|---|---|---|
| bullish | 557 | 1 | 12 |
| neutral | 27 | 1345 | 19 |
| bearish | 4 | 1 | 298 |

scored 2264 texts in 68.885s (30426.3 µs/text, single run)

### Financial PhraseBank, sentences >=50% of annotators agree on (`phrasebank-50-agree`, n=4846) — **CONTAMINATED: the model was trained on this data**

| | accuracy | macro-F1 |
|---|---|---|
| finbert | 0.889 | 0.882 |
| always neutral | 0.594 | 0.248 |

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| bullish | 0.809 | 0.921 | 0.861 | 1363 |
| neutral | 0.962 | 0.857 | 0.906 | 2879 |
| bearish | 0.802 | 0.970 | 0.878 | 604 |

| gold \ predicted | bullish | neutral | bearish |
|---|---|---|---|
| bullish | 1255 | 86 | 22 |
| neutral | 289 | 2467 | 123 |
| bearish | 7 | 11 | 586 |

scored 4846 texts in 148.383s (30619.8 µs/text, single run)

### Twitter Financial News Sentiment, validation split (2022) (`tweets-valid`, n=2388)

| | accuracy | macro-F1 |
|---|---|---|
| finbert | 0.716 | 0.660 |
| always neutral | 0.656 | 0.264 |

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| bullish | 0.592 | 0.602 | 0.597 | 475 |
| neutral | 0.849 | 0.742 | 0.792 | 1566 |
| bearish | 0.486 | 0.752 | 0.590 | 347 |

| gold \ predicted | bullish | neutral | bearish |
|---|---|---|---|
| bullish | 286 | 132 | 57 |
| neutral | 185 | 1162 | 219 |
| bearish | 12 | 74 | 261 |

scored 2388 texts in 45.244s (18946.2 µs/text, single run)

