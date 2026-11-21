#include "lob/order_book.hpp"

#include <algorithm>
#include <iterator>

// Price-time priority limit order book.
//
// Layout (see order_book.hpp):
//   bids_ / asks_ : std::map price -> PriceLevel. Bids use std::greater so begin() is the best
//                   price on both sides: best bid/ask is O(1), a new level is O(log L).
//   PriceLevel    : std::list FIFO queue + running total. std::list never invalidates iterators
//                   to other elements on erase, so a stored iterator gives O(1) cancel.
//   index_        : hash map id -> Locator {side, price, iterator into the queue}.
//
// Invariant between calls: every queued order has exactly one index_ entry (and vice versa),
// and no PriceLevel is ever empty (empty levels are erased immediately).

namespace lob {

// ---------------------------------------------------------------- helpers

// Append a new order to the back of its price level (back of the queue = lowest time priority).
void OrderBook::rest(OrderId id, Side side, Price price, Qty qty) {
    auto put = [&](auto& book) {
        PriceLevel& level = book[price];  // creates the level if it doesn't exist yet
        level.queue.push_back(RestingOrder{id, qty});
        level.total += qty;
        index_[id] = Locator{side, price, std::prev(level.queue.end())};
    };
    if (side == Side::Buy) put(bids_);
    else put(asks_);
}

// Remove one order from its level; erase the level if it becomes empty.
// The caller is responsible for erasing the index_ entry.
void OrderBook::remove_order(const Locator& loc) {
    auto take_out = [&](auto& book) {
        auto lvl = book.find(loc.price);
        lvl->second.total -= loc.pos->qty;
        lvl->second.queue.erase(loc.pos);  // O(1): we hold the iterator
        if (lvl->second.queue.empty()) book.erase(lvl);
    };
    if (loc.side == Side::Buy) take_out(bids_);
    else take_out(asks_);
}

// Match an incoming order against the opposite side's book. `limit == nullptr` = market order.
// Returns the quantity left unfilled. Appends one Fill per (taker, maker) execution.
template <class Book>
Qty OrderBook::match(Book& book, OrderId taker, Side side, Qty qty, const Price* limit) {
    while (qty > 0 && !book.empty()) {
        auto lvl = book.begin();  // re-read every iteration: the previous level may have been erased
        const Price level_price = lvl->first;

        // Price check: a buy stops at asks above its limit, a sell at bids below its limit.
        if (limit && (side == Side::Buy ? level_price > *limit : level_price < *limit)) break;

        PriceLevel& level = lvl->second;
        while (qty > 0 && !level.queue.empty()) {
            RestingOrder& maker = level.queue.front();  // oldest order first: time priority
            const Qty traded = std::min(qty, maker.qty);

            // The trade prints at the MAKER's price (the resting level), never the taker's limit.
            fills_.push_back(Fill{taker, maker.id, side, level_price, traded});

            qty -= traded;
            maker.qty -= traded;
            level.total -= traded;
            if (maker.qty == 0) {
                index_.erase(maker.id);  // fully filled: gone from the index...
                level.queue.pop_front(); // ...and from the queue
            }
        }
        if (level.queue.empty()) book.erase(lvl);  // never leave an empty level behind
    }
    return qty;
}

// ---------------------------------------------------------------- order entry

AddResult OrderBook::add_limit(OrderId id, Side side, Price price, Qty qty) {
    fills_.clear();
    if (contains(id)) return AddResult{Reject::DuplicateId};
    if (qty <= 0) return AddResult{Reject::BadQty};
    if (price <= 0) return AddResult{Reject::BadPrice};

    // Trade first while the order crosses the opposite side...
    const Qty remaining = (side == Side::Buy) ? match(asks_, id, side, qty, &price)
                                              : match(bids_, id, side, qty, &price);
    // ...then rest whatever is left at the limit price.
    if (remaining > 0) rest(id, side, price, remaining);
    return AddResult{Reject::None, qty - remaining, remaining};
}

AddResult OrderBook::add_market(OrderId id, Side side, Qty qty) {
    fills_.clear();
    if (contains(id)) return AddResult{Reject::DuplicateId};
    if (qty <= 0) return AddResult{Reject::BadQty};

    const Qty remaining = (side == Side::Buy) ? match(asks_, id, side, qty, nullptr)
                                              : match(bids_, id, side, qty, nullptr);
    return AddResult{Reject::None, qty - remaining, 0};  // a market order never rests
}

bool OrderBook::cancel(OrderId id) {
    auto it = index_.find(id);
    if (it == index_.end()) return false;
    remove_order(it->second);
    index_.erase(it);
    return true;
}

bool OrderBook::reduce(OrderId id, Qty by) {
    auto it = index_.find(id);
    if (it == index_.end()) return false;
    const Locator& loc = it->second;
    if (by <= 0 || by > loc.pos->qty) return false;
    if (by == loc.pos->qty) return cancel(id);

    // Shrink in place: the order keeps its position in the queue (time priority).
    loc.pos->qty -= by;
    if (loc.side == Side::Buy) bids_.find(loc.price)->second.total -= by;
    else asks_.find(loc.price)->second.total -= by;
    return true;
}

AddResult OrderBook::replace(OrderId id, Price new_price, Qty new_qty) {
    // Validate everything first, so a rejected replace leaves the original order untouched.
    auto it = index_.find(id);
    if (it == index_.end()) { fills_.clear(); return AddResult{Reject::UnknownId}; }
    if (new_qty <= 0) { fills_.clear(); return AddResult{Reject::BadQty}; }
    if (new_price <= 0) { fills_.clear(); return AddResult{Reject::BadPrice}; }

    const Side side = it->second.side;  // read before cancel() invalidates `it`
    cancel(id);
    return add_limit(id, side, new_price, new_qty);  // back of the queue: priority is lost
}

// ---------------------------------------------------------------- queries

std::optional<Price> OrderBook::best_bid() const {
    if (bids_.empty()) return std::nullopt;
    return bids_.begin()->first;
}

std::optional<Price> OrderBook::best_ask() const {
    if (asks_.empty()) return std::nullopt;
    return asks_.begin()->first;
}

Qty OrderBook::volume_at(Side side, Price price) const {
    auto lookup = [&](const auto& book) -> Qty {
        auto it = book.find(price);
        return it == book.end() ? 0 : it->second.total;
    };
    return side == Side::Buy ? lookup(bids_) : lookup(asks_);
}

void OrderBook::top_levels(Side side, std::size_t n, std::vector<Level>& out) const {
    out.clear();
    auto collect = [&](const auto& book) {
        for (const auto& [price, level] : book) {
            if (out.size() >= n) break;
            out.push_back(Level{price, level.total, static_cast<std::uint32_t>(level.queue.size())});
        }
    };
    if (side == Side::Buy) collect(bids_);
    else collect(asks_);
}

std::size_t OrderBook::order_count() const { return index_.size(); }

bool OrderBook::contains(OrderId id) const { return index_.contains(id); }

}  // namespace lob
