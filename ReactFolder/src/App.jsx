import { useEffect, useRef } from "react"
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom"
import Watchlist from "./pages/Watchlist"
import StockOverview from "./pages/StockOverview"

// GoatCounter (loaded by base.html when analytics is on) counts the page the browser loaded. Moving
// between the watchlist and an overview happens inside React without a page load, so count those here.
function CountPageViews() {
  const location = useLocation()
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    window.goatcounter?.count?.({ path: "/live" + location.pathname })
  }, [location.pathname])
  return null
}

// Navigation and symbol search come from the site header (base.html), shared with the Django pages.
export default function App() {
  return (
    <BrowserRouter basename="/live">
      <CountPageViews />
      <Routes>
        <Route path="/" element={<Watchlist />} />
        <Route path="/stock/:symbol" element={<StockOverview />} />
      </Routes>
    </BrowserRouter>
  )
}
