// Replays a LOBSTER message file through lob::OrderBook and checks the reconstructed book
// against LOBSTER's own order-book snapshot after EVERY message.
//
// Usage: lobster_replay <message.csv> <orderbook.csv> [--levels 10] [--show-mismatches 5]
//
// What this validates: the book-maintenance path (add / partial cancel / delete / execution of
// resting orders) on real Nasdaq order flow. LOBSTER reports an execution as a reduction of the
// resting order; the aggressor never appears as an order. So the matching loop only runs if an
// add would cross (counted as an anomaly). Matching itself is validated by the differential test
// in tests/test_order_book.cpp.
//
// The observation window (the important subtlety):
//   A 10-level LOBSTER file contains ONLY events inside the 10-level window. An order deeper in
//   the book can be added or cancelled with no message at all. So:
//   1. Orders resting before 09:30:00 have no add message: we seed them from the first snapshot
//      as anonymous ("unattributed") liquidity per price.
//   2. A level that falls outside the window is no longer observable: we DROP it.
//   3. A level that re-enters the window from outside is RESYNCED from the snapshot (counted).
//   Levels that stay inside the window are rebuilt from messages alone; the snapshot is only
//   used to check them. This is the usual "snapshot + incremental updates" recovery a real
//   market-data handler does for data it could not observe.
#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "lob/order_book.hpp"

using namespace lob;

namespace {

constexpr Price kDummyAsk = 9'999'999'999;  // LOBSTER placeholder for an empty level
constexpr Price kDummyBid = -9'999'999'999;

struct Msg {
    double time;
    int type;  // 1 add, 2 partial cancel, 3 delete, 4 visible execution, 5 hidden execution, 7 halt
    OrderId id;
    Qty size;
    Price price;
    Side side;  // side of the resting / submitted limit order
};

std::string read_file(const char* path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error(std::string("cannot open ") + path);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

// Minimal CSV cursor over an in-memory file. std::from_chars: no locale, no allocation.
struct Cursor {
    const char* p;
    const char* end;
    bool done() const { return p >= end; }
    template <class T>
    T next() {
        T v{};
        auto [q, ec] = std::from_chars(p, end, v);
        if (ec != std::errc()) throw std::runtime_error("parse error near: " + std::string(p, std::min<std::ptrdiff_t>(30, end - p)));
        p = q;
        if (p < end && *p == ',') ++p;
        return v;
    }
    void end_line() {
        while (p < end && (*p == '\r' || *p == '\n' || *p == ',')) ++p;
    }
};

std::vector<Msg> parse_messages(const std::string& text) {
    std::vector<Msg> out;
    out.reserve(text.size() / 40);
    Cursor c{text.data(), text.data() + text.size()};
    while (!c.done()) {
        Msg m{};
        m.time = c.next<double>();
        m.type = c.next<int>();
        m.id = c.next<OrderId>();
        m.size = c.next<Qty>();
        m.price = c.next<Price>();
        m.side = c.next<int>() == 1 ? Side::Buy : Side::Sell;
        c.end_line();
        out.push_back(m);
    }
    return out;
}

// One snapshot row: ask px, ask sz, bid px, bid sz, repeated per level. Dummy levels dropped.
struct Snapshot {
    std::vector<Level> asks, bids;
    const std::vector<Level>& side(Side s) const { return s == Side::Buy ? bids : asks; }
};

void parse_snapshot(Cursor& c, int levels, Snapshot& s) {
    s.asks.clear();
    s.bids.clear();
    for (int i = 0; i < levels; ++i) {
        Price ap = c.next<Price>(); Qty as = c.next<Qty>();
        Price bp = c.next<Price>(); Qty bs = c.next<Qty>();
        if (ap != kDummyAsk && as > 0) s.asks.push_back({ap, as, 0});
        if (bp != kDummyBid && bs > 0) s.bids.push_back({bp, bs, 0});
    }
    c.end_line();
}

bool worse(Side s, Price a, Price b) { return s == Side::Buy ? a < b : a > b; }  // a further from the touch than b

// Engine operations, recorded in pass 1 and replayed in pass 2 to time the engine alone.
struct Op {
    enum Kind : std::uint8_t { Add, Reduce, Cancel } kind;
    Side side;
    OrderId id;
    Price price;
    Qty qty;
};

struct Counters {
    long long adds = 0, reduces = 0, deletes = 0, execs = 0, hidden = 0, halts = 0;
    long long unknown_id_events = 0;  // cancel/exec of an id we never saw added (or had dropped)
    long long underflow_events = 0;   // ...and the unattributed liquidity could not cover it
    long long crossing_adds = 0;      // an add traded inside our engine (should be 0)
    long long rejected_ops = 0;       // engine rejected something LOBSTER says happened
    long long dropped_levels = 0;     // levels that left the observable window
    long long resynced_levels = 0;    // levels re-entering the window, set from the snapshot
    long long resync_inner_entries = 0;  // re-entering levels found inside the outermost level
};

// The reconstructed book: engine (orders with known ids) + unattributed liquidity per price.
class Replayer {
public:
    Replayer(int levels, std::vector<Op>& log) : levels_(std::size_t(levels)), log_(log) {}

    void seed(const Snapshot& first, const Msg& m0) {
        for (Side s : {Side::Buy, Side::Sell})
            for (auto& l : first.side(s)) un_[idx(s)][l.price] += l.qty;
        // The first snapshot already includes message 0; undo it to get the opening book.
        if (m0.type == 1) take_unattributed(m0.side, m0.price, m0.size);
        else if (m0.type >= 2 && m0.type <= 4) un_[idx(m0.side)][m0.price] += m0.size;
        for (Side s : {Side::Buy, Side::Sell}) prev_edge_[idx(s)] = edge(first, s);
    }

    void apply(const Msg& m) {
        switch (m.type) {
            case 1: {
                ++c.adds;
                log_.push_back({Op::Add, m.side, m.id, m.price, m.size});
                auto r = ob.add_limit(m.id, m.side, m.price, m.size);
                if (!r.ok()) ++c.rejected_ops;
                if (r.filled > 0) ++c.crossing_adds;
                if (r.resting > 0) ids_at_[idx(m.side)][m.price].push_back(m.id);
                break;
            }
            case 2: case 3: case 4: {
                m.type == 2 ? ++c.reduces : m.type == 3 ? ++c.deletes : ++c.execs;
                if (ob.contains(m.id)) {
                    bool ok;
                    if (m.type == 3) { log_.push_back({Op::Cancel, m.side, m.id, 0, 0}); ok = ob.cancel(m.id); }
                    else { log_.push_back({Op::Reduce, m.side, m.id, 0, m.size}); ok = ob.reduce(m.id, m.size); }
                    if (!ok) ++c.rejected_ops;
                } else {
                    ++c.unknown_id_events;
                    if (take_unattributed(m.side, m.price, m.size) > 0) ++c.underflow_events;
                }
                break;
            }
            case 5: ++c.hidden; break;  // hidden liquidity is not part of the visible book
            case 7: ++c.halts; break;
            default: throw std::runtime_error("unknown LOBSTER message type " + std::to_string(m.type));
        }
    }

    // Window maintenance after a message, before comparing against its snapshot.
    void sync_window(const Snapshot& snap) {
        for (Side s : {Side::Buy, Side::Sell}) {
            const auto& lob = snap.side(s);
            // Levels beyond the PREVIOUS edge were unobservable until now: resync them.
            if (auto prev = prev_edge_[idx(s)]) {
                for (std::size_t pos = 0; pos < lob.size(); ++pos) {
                    const Level& l = lob[pos];
                    if (!worse(s, l.price, *prev)) continue;
                    if (pos + 1 < levels_) ++c.resync_inner_entries;  // re-entry NOT at the outermost level
                    Qty engine = ob.volume_at(s, l.price);
                    Qty want = std::max<Qty>(0, l.qty - engine);
                    auto& un = un_[idx(s)];
                    Qty have = un.count(l.price) ? un[l.price] : 0;
                    if (have != want || engine > l.qty) {
                        ++c.resynced_levels;
                        if (want > 0) un[l.price] = want; else un.erase(l.price);
                    }
                }
            }
            // Levels beyond the CURRENT edge are no longer observable: drop them.
            auto cur = edge(snap, s);
            if (cur) drop_beyond(s, *cur);
            prev_edge_[idx(s)] = cur;
        }
    }

    // Our top-n view: engine levels + unattributed levels merged by price, best first.
    void top(Side s, std::vector<Level>& out) {
        ob.top_levels(s, levels_, buf_);
        out.clear();
        const auto& un = un_[idx(s)];
        auto e = buf_.begin();
        auto x = (s == Side::Buy) ? un.end() : un.begin();  // un_ is ascending by price
        auto x_end = (s == Side::Buy) ? un.begin() : un.end();
        auto x_valid = [&] { return x != x_end; };
        auto x_get = [&]() -> const std::pair<const Price, Qty>& { return s == Side::Buy ? *std::prev(x) : *x; };
        auto x_adv = [&] { if (s == Side::Buy) --x; else ++x; };
        while (out.size() < levels_ && (e != buf_.end() || x_valid())) {
            if (!x_valid() || (e != buf_.end() && !worse(s, e->price, x_get().first) && e->price != x_get().first)) {
                out.push_back({e->price, e->qty, 0}); ++e;
            } else if (e == buf_.end() || worse(s, e->price, x_get().first)) {
                out.push_back({x_get().first, x_get().second, 0}); x_adv();
            } else {
                out.push_back({e->price, e->qty + x_get().second, 0}); ++e; x_adv();
            }
        }
    }

    OrderBook ob;
    Counters c;

private:
    static int idx(Side s) { return s == Side::Buy ? 0 : 1; }

    // The visible window's outermost price, if LOBSTER shows a full set of levels on that side.
    std::optional<Price> edge(const Snapshot& snap, Side s) const {
        const auto& lob = snap.side(s);
        if (lob.size() < levels_) return std::nullopt;  // whole side visible
        return lob.back().price;
    }

    Qty take_unattributed(Side s, Price p, Qty q) {
        auto& un = un_[idx(s)];
        auto it = un.find(p);
        if (it == un.end()) return q;
        Qty got = std::min(q, it->second);
        it->second -= got;
        if (it->second == 0) un.erase(it);
        return q - got;
    }

    void drop_beyond(Side s, Price edge_px) {
        auto& un = un_[idx(s)];
        for (auto it = un.begin(); it != un.end();)
            it = worse(s, it->first, edge_px) ? (++c.dropped_levels, un.erase(it)) : std::next(it);
        auto& ids = ids_at_[idx(s)];
        for (auto it = ids.begin(); it != ids.end();) {
            if (!worse(s, it->first, edge_px)) { ++it; continue; }
            bool any = false;
            for (OrderId id : it->second)
                if (ob.contains(id)) { log_.push_back({Op::Cancel, s, id, 0, 0}); ob.cancel(id); any = true; }
            c.dropped_levels += any;
            it = ids.erase(it);
        }
    }

    std::size_t levels_;
    std::vector<Op>& log_;
    std::map<Price, Qty> un_[2];                          // unattributed qty per price, per side
    std::map<Price, std::vector<OrderId>> ids_at_[2];     // engine ids per price (lazily pruned)
    std::optional<Price> prev_edge_[2];
    std::vector<Level> buf_;
};

bool same_levels(const std::vector<Level>& a, const std::vector<Level>& b, std::size_t k) {
    if (a.size() < k || b.size() < k) return false;
    for (std::size_t i = 0; i < k; ++i)
        if (a[i].price != b[i].price || a[i].qty != b[i].qty) return false;
    return true;
}

double pct(long long a, long long b) { return b ? 100.0 * double(a) / double(b) : 0.0; }

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: %s <message.csv> <orderbook.csv> [--levels N] [--show-mismatches N]\n", argv[0]);
        return 2;
    }
    int levels = 10, show = 5;
    for (int i = 3; i + 1 < argc; i += 2) {
        if (!std::strcmp(argv[i], "--levels")) levels = std::atoi(argv[i + 1]);
        else if (!std::strcmp(argv[i], "--show-mismatches")) show = std::atoi(argv[i + 1]);
    }

    try {
        const auto msgs = parse_messages(read_file(argv[1]));
        const std::string book_text = read_file(argv[2]);
        if (msgs.empty()) throw std::runtime_error("no messages");

        // ---------- pass 1: reconstruct and verify against every snapshot ----------
        std::vector<Op> log;
        log.reserve(msgs.size() + msgs.size() / 4);
        Replayer rp(levels, log);
        Cursor bc{book_text.data(), book_text.data() + book_text.size()};
        Snapshot snap;
        std::vector<Level> ours_b, ours_a;

        // levels-1: everything except the outermost level, which is the only one a resync can touch
        // (verified by the resync_inner_entries counter, reported below).
        const std::size_t ks[] = {1, 5, std::size_t(levels - 1), std::size_t(levels)};
        constexpr int K = 4;
        long long match[K] = {}, compared[K] = {};
        int shown = 0;

        for (std::size_t i = 0; i < msgs.size(); ++i) {
            if (bc.done()) throw std::runtime_error("order book file has fewer rows than message file");
            parse_snapshot(bc, levels, snap);
            if (i == 0) rp.seed(snap, msgs[0]);
            rp.apply(msgs[i]);
            rp.sync_window(snap);
            rp.top(Side::Buy, ours_b);
            rp.top(Side::Sell, ours_a);

            for (int k = 0; k < K; ++k) {
                // Score depth k only where LOBSTER itself shows k occupied levels on both sides.
                if (snap.bids.size() < ks[k] || snap.asks.size() < ks[k]) continue;
                ++compared[k];
                match[k] += same_levels(ours_b, snap.bids, ks[k]) && same_levels(ours_a, snap.asks, ks[k]);
            }
            bool full_ok = same_levels(ours_b, snap.bids, snap.bids.size()) && same_levels(ours_a, snap.asks, snap.asks.size());
            if (!full_ok && shown < show) {
                ++shown;
                const Msg& m = msgs[i];
                std::printf("depth mismatch after msg %zu (t=%.6f type=%d id=%llu size=%lld px=%lld %s)\n", i, m.time, m.type,
                            (unsigned long long)m.id, (long long)m.size, (long long)m.price, m.side == Side::Buy ? "buy" : "sell");
                for (std::size_t j = 0; j < std::size_t(levels); ++j) {
                    auto v = [](const std::vector<Level>& lv, std::size_t j2, bool qty) -> long long {
                        return j2 < lv.size() ? (long long)(qty ? lv[j2].qty : lv[j2].price) : 0LL;
                    };
                    std::printf("   bid ours %9lld x %5lld | lobster %9lld x %5lld     ask ours %9lld x %5lld | lobster %9lld x %5lld\n",
                                v(ours_b, j, false), v(ours_b, j, true), v(snap.bids, j, false), v(snap.bids, j, true),
                                v(ours_a, j, false), v(ours_a, j, true), v(snap.asks, j, false), v(snap.asks, j, true));
                }
            }
        }

        // ---------- pass 2: time the engine alone on the exact same operation sequence ----------
        OrderBook ob2;
        auto t0 = std::chrono::steady_clock::now();
        for (const Op& op : log) {
            switch (op.kind) {
                case Op::Add: ob2.add_limit(op.id, op.side, op.price, op.qty); break;
                case Op::Reduce: ob2.reduce(op.id, op.qty); break;
                case Op::Cancel: ob2.cancel(op.id); break;
            }
        }
        auto t1 = std::chrono::steady_clock::now();
        double secs = std::chrono::duration<double>(t1 - t0).count();
        if (ob2.order_count() != rp.ob.order_count()) throw std::runtime_error("pass 2 diverged from pass 1");

        // ---------- report ----------
        const Counters& c = rp.c;
        std::printf("\nLOBSTER replay: %s\n", argv[1]);
        std::printf("messages            %zu (add %lld, partial cancel %lld, delete %lld, exec %lld, hidden exec %lld, halt %lld)\n",
                    msgs.size(), c.adds, c.reduces, c.deletes, c.execs, c.hidden, c.halts);
        std::printf("unknown-id events   %lld (%.2f%% of cancels/execs); not covered by unattributed liquidity: %lld\n",
                    c.unknown_id_events, pct(c.unknown_id_events, c.reduces + c.deletes + c.execs), c.underflow_events);
        std::printf("window maintenance  dropped %lld levels, resynced %lld levels from snapshots (%lld not at the outermost level)\n",
                    c.dropped_levels, c.resynced_levels, c.resync_inner_entries);
        std::printf("engine anomalies    crossing adds %lld, rejected ops %lld\n", c.crossing_adds, c.rejected_ops);
        std::printf("snapshot match      (price AND size, both sides; rows where LOBSTER shows >= k levels)\n");
        for (int k = 0; k < K; ++k)
            std::printf("   top %-2zu levels     %lld / %lld = %.3f%%\n", ks[k], match[k], compared[k], pct(match[k], compared[k]));
        std::printf("engine replay       %zu ops in %.1f ms = %.2f M ops/s, %.0f ns/op mean (single thread)\n",
                    log.size(), secs * 1e3, double(log.size()) / secs / 1e6, secs * 1e9 / double(log.size()));
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
}
