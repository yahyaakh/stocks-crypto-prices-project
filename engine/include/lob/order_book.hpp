#pragma once
#include <cstddef>
#include <optional>
#include <vector>

#include <functional>
#include <list>
#include <map>
#include <unordered_map>

#include "lob/types.hpp"

namespace lob {

// Single-instrument limit order book with a price-time priority matching engine.
//
// Matching rules (what the tests in tests/test_order_book.cpp check):
//  * Price priority: a buy matches the LOWEST ask first; a sell matches the HIGHEST bid first.
//  * Time priority: within one price level, the order that arrived first fills first (FIFO).
//  * Trades print at the resting (maker) order's price, never at the taker's limit.
//  * A limit order trades while it crosses, then any remainder rests at its limit price.
//  * A market order trades against whatever is there and never rests.
//  * reduce() keeps the order's place in the queue; replace() loses it (cancel + new order).
//
// Not thread-safe: one thread owns the book, as in a real per-instrument matching engine.
class OrderBook {
public:
    // ---- order entry ----------------------------------------------------------------
    // Limit order. Rejects: id already resting (DuplicateId), qty <= 0 (BadQty), price <= 0 (BadPrice).
    AddResult add_limit(OrderId id, Side side, Price price, Qty qty);

    // Market order: fills up to qty against the opposite side, never rests.
    // Rejects: id already resting (DuplicateId), qty <= 0 (BadQty).
    AddResult add_market(OrderId id, Side side, Qty qty);

    // Remove a resting order. Returns false if the id is not resting (unknown, filled, cancelled).
    bool cancel(OrderId id);

    // Reduce a resting order's quantity by `by`, KEEPING time priority (partial cancel, or
    // an execution reported by an external venue). by == remaining removes the order.
    // Returns false if id is unknown or by <= 0 or by > remaining.
    bool reduce(OrderId id, Qty by);

    // Cancel/replace: new price and/or quantity, LOSES time priority and may trade if the new
    // price crosses. Same side and same id as the original.
    // Rejects (and leaves the original order untouched): UnknownId, BadQty, BadPrice.
    AddResult replace(OrderId id, Price new_price, Qty new_qty);

    // ---- queries ----------------------------------------------------------------------
    std::optional<Price> best_bid() const;
    std::optional<Price> best_ask() const;

    // Total resting quantity at exactly this price on this side (0 if the level is empty).
    Qty volume_at(Side side, Price price) const;

    // Best `n` levels of one side, best first (bids descending, asks ascending), into `out`
    // (cleared first). Takes an output buffer so callers can reuse its memory.
    void top_levels(Side side, std::size_t n, std::vector<Level>& out) const;

    std::size_t order_count() const;   // resting orders, both sides
    bool contains(OrderId id) const;    // is this id currently resting?

    // Fills produced by the most recent add_limit / add_market / replace call, in execution
    // order. Each of those calls clears the buffer first; it keeps its capacity, so steady-state
    // matching does not allocate.
    const std::vector<Fill>& fills() const { return fills_; }

private:
    std::vector<Fill> fills_;

    // Complexity: best bid/ask O(1); new price level O(log L); cancel O(1) average
    // (hash lookup + list erase); per-level qty and order count maintained incrementally.
    struct RestingOrder {
        OrderId id;
        Qty qty;
    };

    struct PriceLevel {
        std::list<RestingOrder> queue;   // FIFO: push_back new orders, fill from front()
        Qty total = 0;                   // order count = queue.size()
    };

    struct Locator {
        Side side;
        Price price;
        std::list<RestingOrder>::iterator pos;   // stays valid while other orders are erased
    };

    std::map<Price, PriceLevel, std::greater<Price>> bids_;   // begin() = highest bid
    std::map<Price, PriceLevel> asks_;                        // begin() = lowest ask
    std::unordered_map<OrderId, Locator> index_;

    // Helpers (defined in order_book.cpp):
    void rest(OrderId id, Side side, Price price, Qty qty);
    void remove_order(const Locator& loc);
    template <class Book>
    Qty match(Book& book, OrderId taker, Side side, Qty qty, const Price* limit);  // limit == nullptr for market orders
};


}  // namespace lob
