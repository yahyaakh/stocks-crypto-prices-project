// Order book tests, written before the implementation. Run one stage at a time:
//   ./build/lob_tests "1 rest"     ./build/lob_tests "3 match"     ./build/lob_tests   (all)
#include <ostream>
#include <random>

#include "lob/order_book.hpp"
#include "minitest.hpp"
#include "reference_book.hpp"

using namespace lob;

namespace lob {
std::ostream& operator<<(std::ostream& os, Side s) { return os << (s == Side::Buy ? "Buy" : "Sell"); }
std::ostream& operator<<(std::ostream& os, const Fill& f) {
    return os << "Fill{taker=" << f.taker << " maker=" << f.maker << " " << f.taker_side << " px=" << f.price << " qty=" << f.qty << "}";
}
std::ostream& operator<<(std::ostream& os, const Level& l) {
    return os << "Level{px=" << l.price << " qty=" << l.qty << " n=" << l.orders << "}";
}
std::ostream& operator<<(std::ostream& os, Reject r) { return os << "Reject(" << int(r) << ")"; }
}  // namespace lob
namespace std {
template <class T>
std::ostream& operator<<(std::ostream& os, const std::optional<T>& o) { return o ? (os << *o) : (os << "nullopt"); }
template <class T>
std::ostream& operator<<(std::ostream& os, const std::vector<T>& v) {
    os << "[";
    for (size_t i = 0; i < v.size(); ++i) os << (i ? ", " : "") << v[i];
    return os << "]";
}
}  // namespace std

constexpr Side B = Side::Buy;
constexpr Side S = Side::Sell;

static std::vector<Level> levels(const OrderBook& ob, Side side, std::size_t n = 100) {
    std::vector<Level> out{{-1, -1, 99}};  // garbage: top_levels must clear it
    ob.top_levels(side, n, out);
    return out;
}

// ===================== Stage 1: a resting book (no crossing orders) =====================

TEST("1 rest: empty book") {
    OrderBook ob;
    CHECK_EQ(ob.best_bid(), std::optional<Price>{});
    CHECK_EQ(ob.best_ask(), std::optional<Price>{});
    CHECK_EQ(ob.order_count(), 0u);
    CHECK_EQ(ob.volume_at(B, 100), 0);
    CHECK(levels(ob, B).empty());
}

TEST("1 rest: non-crossing orders rest and set best bid/ask") {
    OrderBook ob;
    auto r = ob.add_limit(1, B, 99, 10);
    CHECK(r.ok());
    CHECK_EQ(r.filled, 0);
    CHECK_EQ(r.resting, 10);
    ob.add_limit(2, B, 100, 5);
    ob.add_limit(3, B, 98, 7);
    ob.add_limit(4, S, 102, 3);
    ob.add_limit(5, S, 101, 4);
    CHECK_EQ(ob.best_bid(), std::optional<Price>{100});
    CHECK_EQ(ob.best_ask(), std::optional<Price>{101});
    CHECK_EQ(ob.order_count(), 5u);
    CHECK(ob.contains(3));
    CHECK(!ob.contains(42));
    CHECK(ob.fills().empty());
}

TEST("1 rest: levels aggregate quantity and order count") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 5);
    ob.add_limit(2, B, 100, 7);
    ob.add_limit(3, B, 99, 1);
    CHECK_EQ(ob.volume_at(B, 100), 12);
    CHECK_EQ(ob.volume_at(S, 100), 0);
    CHECK_EQ(levels(ob, B), (std::vector<Level>{{100, 12, 2}, {99, 1, 1}}));
}

TEST("1 rest: top_levels sorts best first and respects n") {
    OrderBook ob;
    for (Price p : {105, 103, 104, 101, 102}) ob.add_limit(OrderId(p), S, p, 1);
    for (Price p : {95, 97, 96}) ob.add_limit(OrderId(1000 + p), B, p, 2);
    CHECK_EQ(levels(ob, S, 3), (std::vector<Level>{{101, 1, 1}, {102, 1, 1}, {103, 1, 1}}));
    CHECK_EQ(levels(ob, B), (std::vector<Level>{{97, 2, 1}, {96, 2, 1}, {95, 2, 1}}));
    CHECK(levels(ob, B, 0).empty());
}

TEST("1 rest: rejects duplicate id, bad qty, bad price without changing the book") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 5);
    CHECK_EQ(ob.add_limit(1, S, 200, 5).reject, Reject::DuplicateId);
    CHECK_EQ(ob.add_limit(2, B, 100, 0).reject, Reject::BadQty);
    CHECK_EQ(ob.add_limit(3, B, 100, -4).reject, Reject::BadQty);
    CHECK_EQ(ob.add_limit(4, B, 0, 4).reject, Reject::BadPrice);
    CHECK_EQ(ob.order_count(), 1u);
    CHECK_EQ(ob.volume_at(B, 100), 5);
    CHECK(!ob.contains(2));
}

// ===================== Stage 2: cancel and reduce =====================

TEST("2 cancel: removes the order and its quantity") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 5);
    ob.add_limit(2, B, 100, 7);
    CHECK(ob.cancel(1));
    CHECK(!ob.contains(1));
    CHECK_EQ(ob.volume_at(B, 100), 7);
    CHECK_EQ(levels(ob, B), (std::vector<Level>{{100, 7, 1}}));
    CHECK_EQ(ob.order_count(), 1u);
}

TEST("2 cancel: unknown or already cancelled id returns false") {
    OrderBook ob;
    CHECK(!ob.cancel(7));
    ob.add_limit(7, S, 100, 1);
    CHECK(ob.cancel(7));
    CHECK(!ob.cancel(7));
}

TEST("2 cancel: emptying the best level moves best price") {
    OrderBook ob;
    ob.add_limit(1, S, 101, 1);
    ob.add_limit(2, S, 102, 1);
    ob.cancel(1);
    CHECK_EQ(ob.best_ask(), std::optional<Price>{102});
    CHECK_EQ(levels(ob, S), (std::vector<Level>{{102, 1, 1}}));  // no empty level left behind
    ob.cancel(2);
    CHECK_EQ(ob.best_ask(), std::optional<Price>{});
}

TEST("2 cancel: cancelling from the middle of a queue keeps the others in order") {
    OrderBook ob;
    ob.add_limit(1, S, 100, 1);
    ob.add_limit(2, S, 100, 1);
    ob.add_limit(3, S, 100, 1);
    CHECK(ob.cancel(2));
    ob.add_market(9, B, 2);
    REQUIRE(ob.fills().size() == 2);
    CHECK_EQ(ob.fills()[0].maker, 1u);
    CHECK_EQ(ob.fills()[1].maker, 3u);
}

TEST("2 cancel: reduce lowers quantity; reduce to zero removes") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 10);
    CHECK(ob.reduce(1, 4));
    CHECK_EQ(ob.volume_at(B, 100), 6);
    CHECK(!ob.reduce(1, 7));   // more than remains
    CHECK(!ob.reduce(1, 0));
    CHECK(!ob.reduce(1, -1));
    CHECK(!ob.reduce(99, 1));  // unknown
    CHECK_EQ(ob.volume_at(B, 100), 6);
    CHECK(ob.reduce(1, 6));
    CHECK(!ob.contains(1));
    CHECK_EQ(ob.best_bid(), std::optional<Price>{});
}

// ===================== Stage 3: matching =====================

TEST("3 match: crossing limit order trades at the MAKER price") {
    OrderBook ob;
    ob.add_limit(1, S, 101, 5);
    auto r = ob.add_limit(2, B, 105, 5);  // willing to pay 105, but the ask is 101
    CHECK(r.ok());
    CHECK_EQ(r.filled, 5);
    CHECK_EQ(r.resting, 0);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{2, 1, B, 101, 5}}));
    CHECK_EQ(ob.order_count(), 0u);
    CHECK(!ob.contains(1));  // fully filled maker is gone from the id index too
    CHECK(!ob.cancel(1));
}

TEST("3 match: equal price crosses; worse price does not") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 5);
    ob.add_limit(2, S, 101, 5);
    CHECK_EQ(ob.fills().size(), 0u);
    ob.add_limit(3, S, 100, 2);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{3, 1, S, 100, 2}}));
    CHECK_EQ(ob.volume_at(B, 100), 3);
}

TEST("3 match: partial fill rests the remainder at the limit price") {
    OrderBook ob;
    ob.add_limit(1, S, 101, 3);
    auto r = ob.add_limit(2, B, 102, 10);
    CHECK_EQ(r.filled, 3);
    CHECK_EQ(r.resting, 7);
    CHECK_EQ(ob.best_bid(), std::optional<Price>{102});
    CHECK_EQ(ob.best_ask(), std::optional<Price>{});
    CHECK_EQ(ob.volume_at(B, 102), 7);
}

TEST("3 match: sweeps levels best price first and stops at the limit") {
    OrderBook ob;
    ob.add_limit(1, S, 103, 5);
    ob.add_limit(2, S, 101, 2);
    ob.add_limit(3, S, 102, 2);
    ob.add_limit(4, S, 104, 9);
    auto r = ob.add_limit(10, B, 103, 6);
    CHECK_EQ(r.filled, 6);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{10, 2, B, 101, 2}, {10, 3, B, 102, 2}, {10, 1, B, 103, 2}}));
    CHECK_EQ(levels(ob, S), (std::vector<Level>{{103, 3, 1}, {104, 9, 1}}));
}

TEST("3 match: FIFO within a price level (time priority)") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 2);
    ob.add_limit(2, B, 100, 2);
    ob.add_limit(3, B, 100, 2);
    ob.add_limit(9, S, 100, 3);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{9, 1, S, 100, 2}, {9, 2, S, 100, 1}}));
    CHECK_EQ(levels(ob, B), (std::vector<Level>{{100, 3, 2}}));
}

TEST("3 match: market order never rests, fills what is available") {
    OrderBook ob;
    ob.add_limit(1, S, 101, 2);
    ob.add_limit(2, S, 150, 3);
    auto r = ob.add_market(9, B, 10);
    CHECK(r.ok());
    CHECK_EQ(r.filled, 5);
    CHECK_EQ(r.resting, 0);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{9, 1, B, 101, 2}, {9, 2, B, 150, 3}}));
    CHECK(!ob.contains(9));
    CHECK_EQ(ob.order_count(), 0u);
}

TEST("3 match: market order into an empty side fills nothing") {
    OrderBook ob;
    ob.add_limit(1, B, 100, 5);
    auto r = ob.add_market(9, B, 5);
    CHECK(r.ok());
    CHECK_EQ(r.filled, 0);
    CHECK(ob.fills().empty());
    CHECK_EQ(ob.add_market(10, S, 0).reject, Reject::BadQty);
    CHECK_EQ(ob.add_market(1, S, 1).reject, Reject::DuplicateId);
}

TEST("3 match: fills() only holds the latest call's fills") {
    OrderBook ob;
    ob.add_limit(1, S, 100, 5);
    ob.add_market(2, B, 1);
    CHECK_EQ(ob.fills().size(), 1u);
    ob.add_limit(3, B, 90, 1);  // no trade
    CHECK(ob.fills().empty());
}

TEST("3 match: reduce keeps time priority") {
    OrderBook ob;
    ob.add_limit(1, S, 100, 5);
    ob.add_limit(2, S, 100, 5);
    ob.reduce(1, 4);  // still first in the queue
    ob.add_market(9, B, 2);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{9, 1, B, 100, 1}, {9, 2, B, 100, 1}}));
}

TEST("3 match: a filled id can be reused afterwards") {
    OrderBook ob;
    ob.add_limit(1, S, 100, 1);
    ob.add_market(2, B, 1);
    CHECK(ob.add_limit(1, S, 100, 1).ok());
}

// ===================== Stage 4: replace (cancel/replace) =====================

TEST("4 replace: loses time priority even at the same price") {
    OrderBook ob;
    ob.add_limit(1, S, 100, 5);
    ob.add_limit(2, S, 100, 5);
    CHECK(ob.replace(1, 100, 5).ok());  // back of the queue now
    ob.add_market(9, B, 1);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{9, 2, B, 100, 1}}));
}

TEST("4 replace: moving to a crossing price trades") {
    OrderBook ob;
    ob.add_limit(1, B, 99, 5);
    ob.add_limit(2, S, 101, 3);
    auto r = ob.replace(1, 101, 5);
    CHECK_EQ(r.filled, 3);
    CHECK_EQ(r.resting, 2);
    CHECK_EQ(ob.fills(), (std::vector<Fill>{{1, 2, B, 101, 3}}));
    CHECK_EQ(levels(ob, B), (std::vector<Level>{{101, 2, 1}}));
}

TEST("4 replace: rejects leave the original order untouched") {
    OrderBook ob;
    ob.add_limit(1, B, 99, 5);
    CHECK_EQ(ob.replace(2, 99, 5).reject, Reject::UnknownId);
    CHECK_EQ(ob.replace(1, 99, 0).reject, Reject::BadQty);
    CHECK_EQ(ob.replace(1, -5, 1).reject, Reject::BadPrice);
    CHECK_EQ(levels(ob, B), (std::vector<Level>{{99, 5, 1}}));
}

// ===================== Stage 5: differential test against the reference model =====================

TEST("5 diff: 200k random operations match the reference model exactly") {
    OrderBook ob;
    ref::ReferenceBook rb;
    std::mt19937_64 rng(20261120);  // fixed seed: failures are reproducible
    std::vector<OrderId> live;
    OrderId next_id = 1;
    std::vector<Level> got;

    for (int step = 0; step < 200'000; ++step) {
        int op = int(rng() % 100);
        Side side = (rng() & 1) ? B : S;
        Price px = 1000 + Price(rng() % 21) - 10;  // tight range => lots of crossing
        Qty qty = 1 + Qty(rng() % 20);
        auto pick = [&]() -> OrderId { return live.empty() ? 999'999'999 : live[rng() % live.size()]; };

        if (op < 55) {
            OrderId id = (rng() % 50 == 0) ? pick() : next_id++;  // ~2% duplicate ids
            auto a = ob.add_limit(id, side, px, qty);
            auto e = rb.add_limit(id, side, px, qty);
            if (a.reject != e.reject || a.filled != e.filled || a.resting != e.resting) {
                CHECK_EQ(a.reject, e.reject); CHECK_EQ(a.filled, e.filled); CHECK_EQ(a.resting, e.resting);
                std::printf("    diverged at step %d (add_limit id=%llu)\n", step, (unsigned long long)id); return;
            }
            if (e.resting > 0) live.push_back(id);
        } else if (op < 62) {
            OrderId id = next_id++;
            auto a = ob.add_market(id, side, qty);
            auto e = rb.add_market(id, side, qty);
            if (a.filled != e.filled) { CHECK_EQ(a.filled, e.filled); std::printf("    diverged at step %d (market)\n", step); return; }
        } else if (op < 85) {
            OrderId id = pick();
            if (ob.cancel(id) != rb.cancel(id)) { std::printf("    diverged at step %d (cancel id=%llu)\n", step, (unsigned long long)id); CHECK(false); return; }
        } else if (op < 93) {
            OrderId id = pick();
            Qty by = 1 + Qty(rng() % 10);
            if (ob.reduce(id, by) != rb.reduce(id, by)) { std::printf("    diverged at step %d (reduce)\n", step); CHECK(false); return; }
        } else {
            OrderId id = pick();
            auto a = ob.replace(id, px, qty);
            auto e = rb.replace(id, px, qty);
            if (a.reject != e.reject || a.filled != e.filled) { CHECK_EQ(a.reject, e.reject); CHECK_EQ(a.filled, e.filled); std::printf("    diverged at step %d (replace)\n", step); return; }
        }

        if (ob.fills() != rb.fills()) {
            CHECK_EQ(ob.fills(), rb.fills());
            std::printf("    diverged at step %d (fills)\n", step);
            return;
        }
        if (step % 97 == 0) {  // full-depth comparison is O(n); sample it
            for (Side sd : {B, S}) {
                ob.top_levels(sd, 1000, got);
                if (got != rb.top_levels(sd, 1000)) { CHECK_EQ(got, rb.top_levels(sd, 1000)); std::printf("    diverged at step %d (depth)\n", step); return; }
            }
            if (ob.order_count() != rb.order_count()) { CHECK_EQ(ob.order_count(), rb.order_count()); return; }
        }
        if (ob.best_bid() != rb.best(B) || ob.best_ask() != rb.best(S)) {
            CHECK_EQ(ob.best_bid(), rb.best(B)); CHECK_EQ(ob.best_ask(), rb.best(S));
            std::printf("    diverged at step %d (top of book)\n", step);
            return;
        }
        if (live.size() > 4000) live.erase(live.begin(), live.begin() + 2000);  // keep pick() useful
    }
    CHECK(!(ob.best_bid() && ob.best_ask() && *ob.best_bid() >= *ob.best_ask()));  // never crossed at rest
}

int main(int argc, char** argv) { return minitest::run(argc, argv); }
