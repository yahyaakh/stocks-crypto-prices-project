import { BrowserRouter, Routes, Route, Link } from "react-router-dom"
import Watchlist from "./pages/Watchlist"
import StockOverview from "./pages/StockOverview"

export default function App() {
  return (
    <BrowserRouter basename="/live">
      <nav style={{ padding: "1rem", borderBottom: "1px solid #333" }}>
        <Link to="/" style={{ marginRight: "1rem", color: "white" }}>
          Watchlist
        </Link>
        <Link to="/stock/MSFT" style={{ color: "white" }}>
          Stock Overview
        </Link>
      </nav>

      <Routes>
        <Route path="/" element={<Watchlist />} />
        <Route path="/stock/:symbol" element={<StockOverview />} />
      </Routes>
    </BrowserRouter>
  )
}