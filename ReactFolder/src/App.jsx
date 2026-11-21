import { BrowserRouter, Routes, Route } from "react-router-dom"
import Watchlist from "./pages/Watchlist"
import StockOverview from "./pages/StockOverview"

// Navigation and symbol search come from the site header (base.html), shared with the Django pages.
export default function App() {
  return (
    <BrowserRouter basename="/live">
      <Routes>
        <Route path="/" element={<Watchlist />} />
        <Route path="/stock/:symbol" element={<StockOverview />} />
      </Routes>
    </BrowserRouter>
  )
}
