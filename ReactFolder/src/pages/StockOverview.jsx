import { useState, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"

import {
  Card, Metric, Text, Badge, Grid,
  Table, TableHead, TableHeaderCell,
  TableBody, TableRow, TableCell
} from "@tremor/react"

import { AreaChart, Area, BarChart, Bar, Legend, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

const PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y"]
const MAX_RATINGS = 20

// ---- formatting helpers -------------------------------------------------
const isNum = v => typeof v === "number" && Number.isFinite(v)
const money = v => isNum(v)
  ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  : "—"
const signedPct = v => isNum(v) ? (v > 0 ? "+" : "") + v.toFixed(2) + "%" : "—"
// "strong_buy" / "Strong_buy" -> "Strong Buy"
const label = s => s ? String(s).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "—"
const ACTION_COLORS = { upgrade: "green", downgrade: "red", initiate: "blue" }
const TONE_COLORS = { bullish: "#16a34a", neutral: "#94a3b8", bearish: "#dc2626" }
const TREND_SERIES = [
  ["strong_buy", "Strong Buy", "#15803d"], ["buy", "Buy", "#4ade80"], ["hold", "Hold", "#f59e0b"],
  ["sell", "Sell", "#f87171"], ["strong_sell", "Strong Sell", "#b91c1c"],
]
// Feed URLs are third-party data: only ever link to http(s), never javascript: or data: URLs.
const safeHref = u => { try { return ["http:", "https:"].includes(new URL(u).protocol) ? u : undefined } catch { return undefined } }
const getJson = url => fetch(url).then(r => (r.ok ? r.json() : null)).catch(() => null)

function ago(iso) {
  const mins = Math.round((Date.now() - Date.parse(iso)) / 60000)
  if (!Number.isFinite(mins)) return ""
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`
  return `${Math.round(mins / 1440)}d ago`
}

function ToneChip({ label: tone }) {
  if (!tone) return null
  return (
    <span style={{
      padding: "1px 8px", borderRadius: "999px", fontSize: "11px", fontWeight: 700, textTransform: "capitalize",
      backgroundColor: TONE_COLORS[tone], color: tone === "neutral" ? "#0f172a" : "white",
    }}>{tone}</span>
  )
}

export default function StockOverview() {
  const { symbol } = useParams()
  const navigate = useNavigate()
  const [overview, setOverview] = useState(null)
  const [ratings, setRatings] = useState([])
  const [trend, setTrend] = useState(null)
  const [news, setNews] = useState(null)
  const [history, setHistory] = useState([])
  const [period, setPeriod] = useState("1y")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [query, setQuery] = useState("")

  // Secondary panels load on their own, so a slow news feed never delays the main page.
  useEffect(() => {
    let cancelled = false
    setTrend(null)
    setNews(null)
    const s = encodeURIComponent(symbol)
    getJson(`/api/stocks/${s}/recommendation-trend/`).then(d => { if (!cancelled) setTrend(d) })
    getJson(`/api/stocks/${s}/news/`).then(d => { if (!cancelled) setNews(d) })
    return () => { cancelled = true }
  }, [symbol])

  // Company data + analyst ratings: only when the symbol changes.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError("")
    Promise.all([
      fetch(`/api/stocks/${encodeURIComponent(symbol)}/overview/`).then(async r => {
        const body = await r.json().catch(() => ({}))
        if (!r.ok || body.error) throw new Error(body.error || `HTTP ${r.status}`)
        return body
      }),
      fetch(`/api/stocks/${encodeURIComponent(symbol)}/ratings/`).then(r => r.json()).catch(() => []),
    ])
      .then(([o, r]) => {
        if (cancelled) return
        setOverview(o)
        setRatings(Array.isArray(r) ? r : [])
      })
      .catch(e => { if (!cancelled) setError(e.message || "Could not load data") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  // Price history: when the symbol or the chart period changes.
  useEffect(() => {
    let cancelled = false
    fetch(`/api/stocks/${encodeURIComponent(symbol)}/history/?period=${period}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setHistory(Array.isArray(d) ? d : []) })
      .catch(() => { if (!cancelled) setHistory([]) })
    return () => { cancelled = true }
  }, [symbol, period])

  const search = (
    <form
      className="flex gap-2 mb-6"
      onSubmit={e => {
        e.preventDefault()
        const s = query.trim().toUpperCase()
        if (s) { navigate(`/stock/${encodeURIComponent(s)}`); setQuery("") }
      }}
    >
      <input
        type="text"
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Enter symbol e.g. AAPL"
        aria-label="Stock symbol"
        className="border rounded p-2 text-black"
      />
    </form>
  )

  if (loading) return <div className="p-6 max-w-6xl mx-auto">{search}<p style={{ color: "white" }}>Loading {symbol}…</p></div>
  if (error) return (
    <div className="p-6 max-w-6xl mx-auto">
      {search}
      <Card><Text>Could not load <strong>{symbol}</strong>: {error}</Text></Card>
    </div>
  )

  const o = overview
  const buy = (o.strong_buy ?? 0) + (o.buy ?? 0)
  const hold = o.hold ?? 0
  const sell = (o.sell ?? 0) + (o.strong_sell ?? 0)
  const total = buy + hold + sell
  const pct = n => total ? (n / total) * 100 : 0
  const upside = isNum(o.target_mean) && isNum(o.price) && o.price !== 0
    ? ((o.target_mean - o.price) / o.price) * 100 : null
  const up = (o.change_pct ?? 0) >= 0

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {search}

      <div className="flex gap-2 mb-2">
        {PERIODS.map(p => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            style={{
              padding: "4px 12px", borderRadius: "6px", border: "none", cursor: "pointer", color: "white",
              backgroundColor: period === p ? "#3b82f6" : "#374151",
            }}
          >
            {p}
          </button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={history}>
          <XAxis dataKey="date" minTickGap={40} />
          <YAxis
            domain={([min, max]) => [Math.floor(min * 0.98), Math.ceil(max * 1.02)]}
            tickFormatter={v => "$" + v}
          />
          <Tooltip
            formatter={v => [money(v), "Close"]}
            contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px", color: "white" }}
            labelStyle={{ color: "#93c5fd" }}
          />
          <Area type="monotone" dataKey="price" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.2} connectNulls />
        </AreaChart>
      </ResponsiveContainer>

      <Card className="p-6">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3">
            {o.logo ? (
              <img src={o.logo} alt={o.symbol} style={{ width: "48px", height: "48px", borderRadius: "8px" }} />
            ) : (
              <div style={{
                width: "48px", height: "48px", borderRadius: "8px", backgroundColor: "#374151",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "white", fontWeight: "bold", fontSize: "14px",
              }}>
                {o.symbol?.slice(0, 2)}
              </div>
            )}
            <div>
              <Text>{[o.exchange, o.sector].filter(Boolean).join(" · ")}</Text>
              <Metric>{o.name} ({o.symbol})</Metric>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <Metric>{money(o.price)}</Metric>
            <span style={{
              padding: "3px 10px", borderRadius: "6px", fontSize: "13px", fontWeight: "bold", color: "white",
              backgroundColor: up ? "#10b981" : "#ef4444",
            }}>
              {isNum(o.change) ? (o.change >= 0 ? "+" : "-") + money(Math.abs(o.change)) + " " : ""}
              ({signedPct(o.change_pct)})
            </span>
          </div>
        </div>
      </Card>

      <Grid numItems={1} numItemsSm={2} numItemsLg={4} className="gap-4 mt-4">
        <Card>
          <Text>Volume</Text>
          <Metric>{isNum(o.volume) ? o.volume.toLocaleString("en-US") : "—"}</Metric>
        </Card>

        <Card>
          <Text>Mean Analyst Target</Text>
          <Metric>{money(o.target_mean)}</Metric>
          {upside !== null && (
            <span style={{
              display: "inline-block", marginTop: "6px", padding: "2px 8px", borderRadius: "4px",
              fontSize: "12px", color: "white", backgroundColor: upside >= 0 ? "#10b981" : "#ef4444",
            }}>
              {upside >= 0 ? "▲" : "▼"} {Math.abs(upside).toFixed(1)}% {upside >= 0 ? "upside" : "downside"}
            </span>
          )}
        </Card>

        <Card>
          <Text>Consensus</Text>
          <Metric>{label(o.consensus)}</Metric>
        </Card>

        <Card>
          <Text>52-Week Range</Text>
          <Metric>{money(o.year_low)} – {money(o.year_high)}</Metric>
        </Card>
      </Grid>

      <Card className="mt-4" style={{ backgroundColor: "#1f2937" }}>
        <Text>Analyst Recommendations ({total} analysts)</Text>
        <div className="flex gap-6 mt-2">
          <Text>🟢 Buy: {buy}{o.strong_buy ? ` (${o.strong_buy} strong)` : ""}</Text>
          <Text>🟡 Hold: {hold}</Text>
          <Text>🔴 Sell: {sell}{o.strong_sell ? ` (${o.strong_sell} strong)` : ""}</Text>
        </div>
        <div className="mt-3 flex w-full rounded-full overflow-hidden" style={{ height: "12px" }}>
          <div style={{ width: `${pct(buy)}%`, backgroundColor: "#10b981" }}></div>
          <div style={{ width: `${pct(hold)}%`, backgroundColor: "#f59e0b" }}></div>
          <div style={{ width: `${pct(sell)}%`, backgroundColor: "#ef4444" }}></div>
        </div>
      </Card>

      {trend?.months?.length > 0 && (
        <Card className="mt-4">
          <Text>Analyst recommendations by month (source: {trend.source === "finnhub" ? "Finnhub" : "Yahoo Finance"})</Text>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={trend.months} margin={{ top: 12 }}>
              <XAxis dataKey="period" />
              <YAxis allowDecimals={false} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px", color: "white" }}
                cursor={{ fill: "rgba(148,163,184,0.1)" }}
              />
              <Legend />
              {TREND_SERIES.map(([key, name, color]) => (
                <Bar key={key} dataKey={key} name={name} stackId="r" fill={color} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <Text className="mt-2" style={{ fontSize: "12px" }}>
            Analyst panels differ between providers, so these counts can differ from the consensus card above.
          </Text>
        </Card>
      )}

      {news?.tone?.total > 0 && (
        <Card className="mt-4">
          <div className="flex justify-between items-center">
            <Text>Headline tone · last {news.tone.days} days ({news.tone.total} headlines, {news.sources.length} sources)</Text>
            <a href={`/stocknews/?symbol=${encodeURIComponent(o.symbol)}`} style={{ color: "#60a5fa", fontSize: "14px" }}>
              All {news.articles.length} {o.symbol} articles ({news.window_days} days) →
            </a>
          </div>
          <div className="mt-3 flex w-full rounded-full overflow-hidden" style={{ height: "12px" }}>
            {["bullish", "neutral", "bearish"].map(t => (
              <div key={t} style={{ width: `${(100 * news.tone[t]) / news.tone.total}%`, backgroundColor: TONE_COLORS[t] }} />
            ))}
          </div>
          <div className="flex gap-6 mt-2">
            <Text>Bullish: {news.tone.bullish}</Text>
            <Text>Neutral: {news.tone.neutral}</Text>
            <Text>Bearish: {news.tone.bearish}</Text>
            {news.tone.net !== null && <Text>Net: {news.tone.net.toFixed(2)}</Text>}
          </div>
          <ul className="mt-3" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {news.articles.slice(0, 5).map(a => (
              <li key={a.id} style={{ padding: "8px 0", borderTop: "1px solid #1f2937", display: "flex", gap: "10px", alignItems: "center" }}>
                <ToneChip label={a.sentiment?.label} />
                <a href={safeHref(a.url)} target="_blank" rel="noopener noreferrer" style={{ color: "#e5e7eb", flex: 1 }}>{a.headline}</a>
                <span style={{ color: "#9ca3af", fontSize: "12px", whiteSpace: "nowrap" }}>{a.source} · {ago(a.published_at)}</span>
              </li>
            ))}
          </ul>
          {news.tone.model_card && (
            <Text className="mt-2" style={{ fontSize: "12px" }}>
              Scored by: {news.tone.model_card.name}. {news.tone.model_card.measured} Headline tone, not a forecast.
            </Text>
          )}
        </Card>
      )}

      {/* 12-month analyst price targets */}
      <Card className="mt-4">
        <Text>12-Month Price Targets</Text>
        <div className="flex justify-between mt-3">
          <div><Text>Low</Text><Metric>{money(o.target_low)}</Metric></div>
          <div><Text>Median</Text><Metric>{money(o.target_median)}</Metric></div>
          <div><Text>Mean</Text><Metric>{money(o.target_mean)}</Metric></div>
          <div style={{ textAlign: "right" }}><Text>High</Text><Metric>{money(o.target_high)}</Metric></div>
        </div>
      </Card>

      <Card className="mt-4">
        <Text>Recent analyst rating changes{ratings.length > MAX_RATINGS ? ` (latest ${MAX_RATINGS} of ${ratings.length} in the last 12 months)` : ""}</Text>
        {ratings.length === 0 ? (
          <Text className="mt-3">No analyst rating changes in the last 12 months.</Text>
        ) : (
          <Table className="mt-2">
            <TableHead>
              <TableRow>
                <TableHeaderCell>Date</TableHeaderCell>
                <TableHeaderCell>Firm</TableHeaderCell>
                <TableHeaderCell>Grade</TableHeaderCell>
                <TableHeaderCell>Action</TableHeaderCell>
                <TableHeaderCell>Previous Grade</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ratings.slice(0, MAX_RATINGS).map((r, i) => (
                <TableRow key={`${r.date}-${r.firm}-${i}`}>
                  <TableCell>{r.date}</TableCell>
                  <TableCell>{r.firm ?? "—"}</TableCell>
                  <TableCell>{r.new_grade ?? "—"}</TableCell>
                  <TableCell><Badge color={ACTION_COLORS[r.action] ?? "gray"}>{label(r.action)}</Badge></TableCell>
                  <TableCell>{r.previous_grade ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
