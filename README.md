# Market Watch

A stock and crypto dashboard (Django + React, deployed on Azure Container Apps) and a C++
limit order book that reconstructs a real Nasdaq trading day exactly.

**Live:** https://marketwatch.yahyaakh.dev

The repository has two independent parts:

| Part | What it is | Where |
|---|---|---|
| Order book engine | C++20 price-time priority matching engine, tested against a reference model and replayed against one day of LOBSTER (Nasdaq ITCH) data | [`engine/`](engine/) |
| Dashboard | Market data, analyst views, multi-source news with headline sentiment | [`myproject/`](myproject/), [`ReactFolder/`](ReactFolder/) |

---

## Measured results

Every number in this section comes from a run of the command shown, on the machine shown.
Nothing is estimated.

### Order book: replay of one real trading day

Data: LOBSTER's free sample, AAPL on 2012-06-21, 10 levels, 400,391 messages
(adds, cancels, partial cancels, executions). After **every** message the engine's book is compared
with LOBSTER's 10-level snapshot, price **and** size, both sides.

| | result |
|---|---|
| snapshot match, top 1 / 5 / 9 / 10 levels | **100.000%** of 400,391 rows at every depth |
| crossing adds, rejected operations | 0, 0 |
| engine throughput (390,283 engine ops replayed on a fresh book, timing only the engine) | **12.44–14.22 M ops/s**, 70–80 ns/op mean, single thread (5 runs) |

```bash
bash scripts/fetch_lobster.sh      # downloads the ~7.3 MB sample into data/lobster/ (git-ignored)
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build -j
engine/build/lobster_replay data/lobster/AAPL_2012-06-21_34200000_57600000_message_10.csv \
                            data/lobster/AAPL_2012-06-21_34200000_57600000_orderbook_10.csv
```

Machine: AMD Ryzen 7 7840HS laptop, 15.2 GB RAM, Windows 11, g++ 14.2.0 (MSYS2), `-O3 -DNDEBUG`,
commit `70d2f86`, 2026-11-21. CI repeats the replay on every push and fails the build unless the
top-9 match is 100%.

What these numbers are **not**:
- The throughput is a **mean** over a real order sequence, not a latency distribution. Per-operation
  p50/p99 haven't been measured.
- One laptop, one instrument, one day. The 5 runs differ by ~14%, which is run-to-run noise on a
  laptop (no CPU pinning, default power plan).
- 8.58% of cancels/executions refer to orders the engine never saw: orders resting before 09:30, or added
  outside the 10-level window that LOBSTER records. The tool tracks them and resyncs levels that leave
  and re-enter the window. Levels 1–9 are rebuilt from messages alone, so the top-9 row is the strict test.

### Headline sentiment

Each news headline is labelled bullish / neutral / bearish. Two models, evaluated on a test set
**neither was trained or tuned on** (Twitter Financial News Sentiment, validation split, n = 2,388):

| | accuracy | macro-F1 | bullish recall | bearish recall | time per headline |
|---|---|---|---|---|---|
| always "neutral" (baseline) | 0.656 | 0.264 | 0.000 | 0.000 | – |
| Loughran-McDonald lexicon (default) | 0.601 | 0.460 | 0.171 | 0.501 | 3.9 µs |
| FinBERT (optional) | 0.716 | 0.660 | 0.602 | 0.752 | 18.9 ms |

Command: `python scripts/fetch_sentiment_data.py all && python scripts/eval_sentiment.py --model {lexicon,finbert}`.
Machine: same laptop, Python 3.11.9, FinBERT on CPU (torch 2.15.0+cpu, 8 threads, batch 32). Single
runs; treat the timings as orders of magnitude.

Read these honestly:
- **The lexicon's accuracy is below the always-neutral baseline** (0.601 vs 0.656). It beats the
  baseline only on macro-F1, and finds just 17% of bullish headlines. It is the default because it
  fits the hosted container (0.5 GiB); FinBERT's container used 745 MB.
- **FinBERT's Financial PhraseBank scores (0.972 accuracy) are invalid** as a quality measure: it was
  fine-tuned on that dataset. They are reported crossed out in the full write-up, not used.
- The lexicon's decision rule was fixed before looking at results, and the word list was not edited
  after seeing errors.
- Live accuracy on the app's own headlines is **unmeasured**: no labelled set of them exists.

Full results, confusion matrices and live examples: [`docs/SENTIMENT_EVAL.md`](docs/SENTIMENT_EVAL.md).

### Tests

- Engine: 24/24 test cases, including a differential test that runs 200,000 random operations against
  a slow, obviously correct reference book and stops at the first divergence. CI also runs them under
  AddressSanitizer + UndefinedBehaviorSanitizer.
- Dashboard: 117 pytest tests (`pytest`, 3.1–3.3 s over three runs on the laptop above). Providers are mocked, so they run in
  CI without API keys; they also all pass with every HTTP(S) request forced through a dead proxy.

---

## Order book engine

Single-instrument, single-threaded, price-time priority:

- Price priority across levels, FIFO inside a level; trades print at the resting (maker) price.
- Limit, market, cancel, `reduce` (keeps queue position) and `replace` (loses it, may trade).
- Bids in `std::map<Price, Level, std::greater<>>`, asks in `std::map<Price, Level>`: best price is
  `begin()`, O(1); a new level is O(log L).
- Each level is a `std::list` queue; an `unordered_map<OrderId, Locator>` stores the list iterator, so
  cancel is O(1) average with no search.
- Per-level total quantity is maintained on every change, so depth queries never rescan a queue.
- The fill buffer keeps its capacity between calls, so steady-state matching doesn't allocate.

The obvious next step is a flat price-indexed array instead of `std::map` (better cache locality,
needs a bounded price range), measured with a p50/p99 latency harness before and after.
Design notes and the reasoning behind each choice: [`engine/docs/ENGINE_GUIDE.md`](engine/docs/ENGINE_GUIDE.md).

---

## Dashboard

| Page | URL | Data |
|---|---|---|
| Home: world indices, top 100 crypto, market news with tone summary | `/` | yfinance, CoinGecko, Finnhub + Yahoo |
| Research hub: stock lookup, links to the lists below | `/stocks/` | – |
| Magnificent 7, ETFs | `/mag7/`, `/etfs/` | yfinance |
| Stock overview (React), the one page per stock: price chart, key statistics, analyst consensus, 12-month target range, rating changes with each firm's price-target move, monthly recommendation trend, headline tone, company profile | `/live/stock/MSFT` | yfinance, Finnhub |
| Stock news: up to 60 articles plus the company's own 8-K filings, bullish/neutral/bearish filters, 7-day tone | `/stocknews/?symbol=MSFT` | Finnhub + Yahoo, SEC EDGAR |
| IPO calendar | `/ipo/` | Finnhub |
| Watchlist (React): stocks, ETFs, crypto and indices, prices every 5 s against the previous session's close, list saved in the browser | `/live/` | yfinance |

The header search, `/stock/AAPL` and the retired `/info/` and `/target/` pages all redirect to the overview.
Every symbol box (header, Research, stock news, live watchlist) suggests US-listed stocks and ETFs by
symbol or company name as you type (`/api/symbols/?q=`), from Nasdaq Trader's daily symbol directory
(about 12,900 listings). A symbol that isn't listed, such as a typo or a company name, gets a "did you
mean" list instead of an empty page; indices, currencies, crypto pairs and foreign listings (`^GSPC`,
`EURUSD=X`, `BTC-USD`, `7203.T`) go straight through to Yahoo.

JSON API under `/api/` (indices, crypto, news, and per-symbol overview, ratings, history, news,
recommendation trend). See [`myproject/market/urls.py`](myproject/market/urls.py).

How it works:
- **News** from Finnhub and Yahoo is merged into one list, de-duplicated by normalised headline
  (keeping the direct publisher link over Finnhub's redirect) and sorted newest first. A stock's list
  covers 30 days, widened to 90 for quiet stocks with fewer than 20 articles; the tone summary always
  covers the last 7 days so it means the same thing for every stock.
- **SEC filings:** a company's Form 8-K filings (earnings releases, executive changes, deals) from SEC
  EDGAR appear in its news labelled "SEC 8-K". They are the company's own disclosures, so they are not
  scored for tone and don't count in the tone summary.
- **One source per number:** the overview, price targets and rating changes come from yfinance. The
  monthly recommendation trend comes from Finnhub, falling back to Yahoo. Finnhub and Yahoo use different
  broker panels and report different analyst counts, so the page labels the source.
- **Caching:** server-side per-view cache, browser `max-age=60`.
- **Concurrency fix:** yfinance keeps SQLite caches in one shared directory, which made concurrent
  gunicorn workers fail with `database is locked`; each worker process now gets its own cache directory.
- **Safety:** third-party feed text is HTML-escaped and links are checked for `http(s)` before rendering.

Known issue: under the hosted container's 0.25 CPU, the `database is locked` error still appeared once in
6 fresh-container test runs (one ticker missing from one page load). It didn't reproduce on demand, so it
isn't fixed yet.

Stack: Django 5.2, gunicorn, WhiteNoise, pandas, yfinance, finnhub-python; React 19 with React Router
and Tremor/Recharts, built by Vite into Django's static files; Pico CSS for the server-rendered pages.

---

## Running it

### Docker (production image)

```bash
cp .env.example .env               # add FINNHUB_API_KEY (free tier) and a SECRET_KEY
docker build -t marketwatch .
docker run --env-file .env -p 8000:8000 marketwatch
# open http://localhost:8000
```

FinBERT instead of the lexicon (image grows from 569 MB to 2.91 GB):

```bash
docker build --build-arg SENTIMENT_MODEL=finbert -t marketwatch:finbert .
```

### Local development

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python scripts/fetch_sentiment_data.py lexicon          # word list into data/sentiment/
cd myproject && DEBUG=True python manage.py runserver   # PowerShell: $env:DEBUG="True"; python manage.py runserver
```

`.env` is only read by Docker (`--env-file`, compose). Outside Docker, export the variables yourself;
with `DEBUG=True` and no `SECRET_KEY` a local-only key is used, without `DEBUG=True` startup fails on purpose.

Or `docker compose up` (runserver with the source mounted for live reload).

React (only needed when changing `ReactFolder/`; the built bundle is committed):

```bash
cd ReactFolder && npm ci && npm run build    # writes into myproject/static/
```

### Tests

```bash
pytest                                                   # dashboard
cmake -S engine -B engine/build-asan -DCMAKE_BUILD_TYPE=Debug -DLOB_SANITIZE=ON
cmake --build engine/build-asan -j && ctest --test-dir engine/build-asan --output-on-failure   # engine
```

The sanitizer build needs Linux or macOS (MinGW has no AddressSanitizer). On Windows, build without
`-DLOB_SANITIZE=ON` using the MinGW generator flags in [`engine/docs/ENGINE_GUIDE.md`](engine/docs/ENGINE_GUIDE.md).

### Configuration

All configuration comes from environment variables; see [`.env.example`](.env.example).

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret, required when `DEBUG=False` |
| `DEBUG`, `ALLOWED_HOSTS`, `LOG_LEVEL` | Usual Django settings |
| `FINNHUB_API_KEY` | News, IPO calendar, recommendation trends (free tier). Without it those parts are empty |
| `SEC_USER_AGENT` | Your name and contact email (`Jane Doe jane@example.com`), required by SEC's fair-access policy. Without it 8-K filings are left out of company news |
| `GOATCOUNTER_CODE` | Optional. The site code from `https://<code>.goatcounter.com` turns on visitor counts: no cookies, no personal data, described on `/privacy/`. Empty = off |
| `SENTIMENT_MODEL` | `lexicon` (default) or `finbert` |
| `CACHE_WARMUP` | `1` pre-fills the cache after startup |

### Deployment

The hosted app runs the production image on Azure Container Apps (0.25 vCPU, 0.5 GiB, one replica kept running).
It used to scale to zero; Azure's system log showed a wake-up taking ~25 s (6.7 s image pull, 11.5 s
container creation, then app start), so one replica now stays up and is billed at the idle rate when quiet.
`robots.txt` keeps crawlers off the per-symbol pages and the API.

Visitor counts (optional) come from GoatCounter, which uses no cookies and stores no IP addresses. Besides page
views it counts a few actions by name only (search suggestion picked, watchlist add, news article or SEC filing
opened), never the symbol or text. `/privacy/` describes this.

Gunicorn preloads the app (`myproject/gunicorn.conf.py`): imports happen once in the master instead of
in each worker. With the same limits locally, time to the first `/healthz` 200 went from 8.9–11.1 s to
4.5–4.8 s (3 runs each, 2026-11-24). A `post_fork` hook gives each worker its own yfinance cache directory.
Before deploying, the image was run locally with the same limits (`--cpus 0.25 --memory 512m`):
12 pages and API endpoints all returned 200 and memory peaked at 221 MiB (one pass, 2026-11-21).

---

## Repository layout

```
engine/            C++ order book: include/, src/, tests/, tools/lobster_replay.cpp, docs/
myproject/         Django project
  market/          app: views, urls, news.py, sentiment/, stocks/, providers/, templates/, tests/
  static/          built React bundle
ReactFolder/       React source (stock overview, watchlist)
scripts/           data downloads (SHA-256 pinned) and the sentiment evaluation
docs/              SENTIMENT_EVAL.md
.github/workflows/ CI: engine tests + sanitizers + LOBSTER replay, pytest, container health check
```

## Data and credits

- LOBSTER sample data, https://lobsterdata.com (based on Nasdaq TotalView-ITCH). Downloaded by script, not redistributed.
- Loughran-McDonald Master Dictionary (via the `pysentiment2` package's 2014 word lists).
- Financial PhraseBank (Malo et al., 2014); Twitter Financial News Sentiment (zeroshot, MIT).
- FinBERT: ProsusAI/finbert.
- Market data from Yahoo Finance (via yfinance), Finnhub and CoinGecko; filings from SEC EDGAR; the
  symbol list from Nasdaq Trader's symbol directory. The 8-K and symbol-directory ideas came from
  [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT).
  For personal and educational use; nothing here is investment advice.
