#pragma once
#include <cstdint>

namespace lob {

// Prices are integer ticks, never floating point: 0.1 + 0.2 != 0.3 in binary floating point,
// and an order book must compare prices for exact equality. LOBSTER uses dollars * 10'000.
using Price = std::int64_t;
using Qty = std::int64_t;
using OrderId = std::uint64_t;

enum class Side : std::uint8_t { Buy, Sell };

constexpr Side opposite(Side s) { return s == Side::Buy ? Side::Sell : Side::Buy; }

// One execution between an incoming (taker/aggressor) order and a resting (maker) order.
// It always prints at the maker's price: the resting order set the price, the taker crossed it.
struct Fill {
    OrderId taker;
    OrderId maker;
    Side taker_side;
    Price price;
    Qty qty;

    bool operator==(const Fill&) const = default;
};

// Aggregated view of one price level, as a market-data feed would publish it.
struct Level {
    Price price;
    Qty qty;              // total resting quantity at this price
    std::uint32_t orders; // number of resting orders at this price

    bool operator==(const Level&) const = default;
};

enum class Reject : std::uint8_t { None, DuplicateId, BadQty, BadPrice, UnknownId };

struct AddResult {
    Reject reject = Reject::None;
    Qty filled = 0;   // quantity executed immediately against the book
    Qty resting = 0;  // quantity left resting in the book (always 0 for market orders)

    bool ok() const { return reject == Reject::None; }
};

}  // namespace lob
