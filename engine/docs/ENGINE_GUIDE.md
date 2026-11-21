# Implementing the order book: guide and hints

You implement the private section of `include/lob/order_book.hpp` and every method in
`src/order_book.cpp`. The tests are already written; work stage by stage until they pass.

## Build and run (Windows, MSYS2 g++; on Linux drop the generator flags)
```
cmake -S engine -B engine/build -G "MinGW Makefiles" -DCMAKE_CXX_COMPILER=g++ -DCMAKE_MAKE_PROGRAM=mingw32-make
cmake --build engine/build -j 8
engine/build/lob_tests "1 rest"      # one stage; no argument = everything
```

## Step 1: data structures (tests "1 rest")
Answer these before you write code; interviewers will ask the same questions.

1. **Price levels per side.** You need the best price in O(1) and an insert in O(log L).
   Hint: an ordered map keyed by price. Bids and asks sort in *opposite* directions. Which
   comparator makes `begin()` the best bid?
2. **Queue inside a level.** FIFO, but cancel must remove from the *middle* in O(1).
   Hint: which standard container never invalidates iterators to other elements on erase?
3. **OrderId to order.** A hash map from id to a small "locator": enough information to
   find the order's level and its position in the queue without searching.
4. **Per-level totals.** Keep `total qty` and the order count in the level and update them
   on every change, so `volume_at` and `top_levels` never rescan the queue.

Trade-off to be able to discuss: an ordered map costs a pointer chase per level. A flat
array indexed by `(price - min_price) / tick` gives O(1) access and better cache locality,
but it needs a bounded price range. Start with the map; the benchmark tells you whether
the array is worth it.

## Step 2: cancel and reduce (tests "2 cancel")
- After removing an order, if the level is now empty, erase the level. Otherwise
  `best_bid()` would return a price with zero quantity.
- `reduce` changes quantity **in place**. It must not move the order in its queue.

## Step 3: matching (tests "3 match")
Write the loop on paper first:
- While the incoming order has quantity left and the opposite side is not empty, look at the
  best opposite level. Stop if it doesn't cross the limit (a market order has no limit).
- Trade against the *front* of that level's queue: quantity = min(incoming, resting).
  The price is the **maker's** level price.
- Fully filled maker: remove it from the queue **and** from the id map. Empty level: erase it.
- Whatever is left over: rest it (limit order) or drop it (market order).

Pitfalls:
- Erasing a map element invalidates iterators to it. Re-read `begin()` after erasing.
- Clear `fills_` at the start of every add/replace call.
- One template or helper for "sweep a side", shared by add_limit and add_market,
  avoids writing the loop four times.

## Step 4: replace (tests "4 replace")
Validate first; on reject, change nothing. Then cancel and call `add_limit` with the same
id and side. That is exactly why priority is lost, and why it can trade.

## Step 5: the differential test (tests "5 diff")
It runs 200k random operations against `tests/reference_book.hpp`, a slow but obviously
correct model, and stops at the first divergence, printing the step number. Debug by
reproducing just that step.

## Step 6: validate on real Nasdaq data (LOBSTER replay)
Once all tests pass:
```
bash scripts/fetch_lobster.sh          # ~7.3 MB download into data/lobster/ (git-ignored)
engine/build/lobster_replay data/lobster/AAPL_2012-06-21_34200000_57600000_message_10.csv \
                            data/lobster/AAPL_2012-06-21_34200000_57600000_orderbook_10.csv
```
It replays 400,390 messages from one trading day of AAPL and, after every message, compares
your book with LOBSTER's 10-level snapshot (price and size, both sides).

What a correct book should show (checked by running the tool against a throwaway reference
implementation, not your code): **100% match at every depth, 0 crossing adds, 0 rejected
ops, 0 resyncs inside the outermost level.** Anything less points to a bug. Use
`--show-mismatches 3` to print the first divergent books.

Understand these lines before you quote them; they're interview material:
- **unknown-id events**: cancels or executions of ids we never saw added. They are orders
  resting before 09:30, or orders added outside the 10-level window. LOBSTER only records
  events inside the window.
- **dropped / resynced levels**: a level that leaves the window can change unseen, so it's
  dropped. When it comes back, it's resynced from the snapshot. One message changes at most
  one level, so a re-entering level is always the outermost one: levels 1-9 are rebuilt
  from messages alone, and the "top 9" row is the strict test.
- **engine replay M ops/s**: the exact engine operation sequence replayed on a fresh book
  and timed alone (no parsing, no checking). It's a real-workload throughput number, not a
  latency distribution; per-op p50/p99 come from your benchmark harness.
