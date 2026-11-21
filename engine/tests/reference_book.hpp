#pragma once
// Deliberately naive reference implementation: one flat vector, linear scans everywhere.
// Too slow for production, but short enough to be obviously correct. The randomised test
// runs the real OrderBook and this model side by side and requires identical behaviour
// (differential testing).
#include <algorithm>
#include <optional>
#include <vector>

#include "lob/types.hpp"

namespace lob::ref {

class ReferenceBook {
public:
    AddResult add_limit(OrderId id, Side side, Price price, Qty qty) {
        fills_.clear();
        if (find(id) != orders_.end()) return {Reject::DuplicateId};
        if (qty <= 0) return {Reject::BadQty};
        if (price <= 0) return {Reject::BadPrice};
        Qty left = match(id, side, qty, price);
        if (left > 0) orders_.push_back({id, side, price, left, seq_++});
        return {Reject::None, qty - left, left};
    }

    AddResult add_market(OrderId id, Side side, Qty qty) {
        fills_.clear();
        if (find(id) != orders_.end()) return {Reject::DuplicateId};
        if (qty <= 0) return {Reject::BadQty};
        Qty left = match(id, side, qty, std::nullopt);
        return {Reject::None, qty - left, 0};
    }

    bool cancel(OrderId id) {
        auto it = find(id);
        if (it == orders_.end()) return false;
        orders_.erase(it);
        return true;
    }

    bool reduce(OrderId id, Qty by) {
        auto it = find(id);
        if (it == orders_.end() || by <= 0 || by > it->qty) return false;
        it->qty -= by;  // seq unchanged: keeps time priority
        if (it->qty == 0) orders_.erase(it);
        return true;
    }

    AddResult replace(OrderId id, Price price, Qty qty) {
        auto it = find(id);
        if (it == orders_.end()) { fills_.clear(); return {Reject::UnknownId}; }
        if (qty <= 0) { fills_.clear(); return {Reject::BadQty}; }
        if (price <= 0) { fills_.clear(); return {Reject::BadPrice}; }
        Side side = it->side;
        orders_.erase(it);
        return add_limit(id, side, price, qty);
    }

    std::optional<Price> best(Side side) const {
        std::optional<Price> b;
        for (auto& o : orders_)
            if (o.side == side && (!b || (side == Side::Buy ? o.price > *b : o.price < *b))) b = o.price;
        return b;
    }

    Qty volume_at(Side side, Price price) const {
        Qty v = 0;
        for (auto& o : orders_) if (o.side == side && o.price == price) v += o.qty;
        return v;
    }

    std::vector<Level> top_levels(Side side, std::size_t n) const {
        std::vector<Level> lv;
        for (auto& o : orders_) {
            if (o.side != side) continue;
            auto it = std::find_if(lv.begin(), lv.end(), [&](const Level& l) { return l.price == o.price; });
            if (it == lv.end()) lv.push_back({o.price, o.qty, 1});
            else { it->qty += o.qty; ++it->orders; }
        }
        std::sort(lv.begin(), lv.end(), [&](const Level& a, const Level& b) {
            return side == Side::Buy ? a.price > b.price : a.price < b.price;
        });
        if (lv.size() > n) lv.resize(n);
        return lv;
    }

    std::size_t order_count() const { return orders_.size(); }
    bool contains(OrderId id) const { return std::any_of(orders_.begin(), orders_.end(), [&](auto& o) { return o.id == id; }); }
    const std::vector<Fill>& fills() const { return fills_; }

private:
    struct Order { OrderId id; Side side; Price price; Qty qty; std::uint64_t seq; };

    std::vector<Order>::iterator find(OrderId id) {
        return std::find_if(orders_.begin(), orders_.end(), [&](auto& o) { return o.id == id; });
    }

    // Repeatedly pick the best crossing maker (best price, then lowest seq) and trade with it.
    Qty match(OrderId taker, Side side, Qty qty, std::optional<Price> limit) {
        while (qty > 0) {
            auto best = orders_.end();
            for (auto it = orders_.begin(); it != orders_.end(); ++it) {
                if (it->side == side) continue;
                bool crosses = !limit || (side == Side::Buy ? it->price <= *limit : it->price >= *limit);
                if (!crosses) continue;
                if (best == orders_.end()) { best = it; continue; }
                bool better_price = side == Side::Buy ? it->price < best->price : it->price > best->price;
                if (better_price || (it->price == best->price && it->seq < best->seq)) best = it;
            }
            if (best == orders_.end()) break;
            Qty q = std::min(qty, best->qty);
            fills_.push_back({taker, best->id, side, best->price, q});
            qty -= q;
            best->qty -= q;
            if (best->qty == 0) orders_.erase(best);
        }
        return qty;
    }

    std::vector<Order> orders_;
    std::vector<Fill> fills_;
    std::uint64_t seq_ = 0;
};

}  // namespace lob::ref
