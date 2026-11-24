import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import './Watchlist.css'

const STORAGE_KEY = 'watchlist.symbols'
const REFRESH_MS = 5000
const STARTERS = ['AAPL', 'NVDA', 'MSFT', 'SPY', 'BTC-USD', 'ETH-USD']

// The list lives in this browser only. Storage can be missing or blocked (private windows), so every
// access is wrapped and the page still works without it.
function loadSymbols() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(saved) ? saved.filter(s => typeof s === 'string' && s).slice(0, 50) : []
  } catch {
    return []
  }
}

function saveSymbols(symbols) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(symbols)) } catch { /* not saved */ }
}

async function fetchQuote(symbol) {
  const r = await fetch(`/api/get-price/?symbol=${encodeURIComponent(symbol)}`)
  const data = await r.json()
  if (!r.ok || data.error) throw new Error(data.error || `Could not load ${symbol}`)
  return data
}

// Stocks and ETFs get their name from the symbol list; other Yahoo symbols get their kind.
function kindOf(q) {
  if (q.name) return q.name
  if (q.symbol.endsWith('-USD')) return 'Crypto'
  if (q.symbol.startsWith('^')) return 'Index'
  if (q.symbol.endsWith('=X')) return 'Currency'
  return ''
}

const money = v => v == null ? '—' : '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: v < 1 ? 6 : 2 })
const signed = (v, digits = 2) => (v > 0 ? '+' : '') + v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

function QuoteCard({ quote, onRemove }) {
  const { symbol, price, change, change_pct } = quote
  const dir = change == null ? '' : change > 0 ? 'up' : change < 0 ? 'down' : ''
  return (
    <article className="wl-card">
      <div className="wl-card-top">
        <Link to={`/stock/${encodeURIComponent(symbol)}`} className="wl-symbol" title={`Open the ${symbol} overview`}>
          {symbol}
        </Link>
        <button type="button" className="wl-remove" onClick={() => onRemove(symbol)} aria-label={`Remove ${symbol}`}>×</button>
      </div>
      <div className="wl-name">{kindOf(quote) || ' '}</div>
      <div className="wl-price" key={price}>{price == null ? '…' : money(price)}</div>
      <div className={`wl-change ${dir}`}>
        {change == null
          ? (price == null ? 'Loading' : 'No change data')
          : <>{dir === 'up' ? '▲' : dir === 'down' ? '▼' : ''} {signed(change)} ({signed(change_pct)}%)</>}
      </div>
    </article>
  )
}

function Watchlist() {
  const [symbol, setSymbol] = useState('')
  // [{symbol, name, price, change, change_pct}]; prices are null until the first refresh.
  const [watchlist, setWatchlist] = useState(() => loadSymbols().map(s => ({ symbol: s, price: null, change: null })))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState(null)

  // Suggestions under the input: US stocks and ETFs matching the symbol or company name typed.
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

  const symbolsKey = watchlist.map(q => q.symbol).join(',')
  useEffect(() => { saveSymbols(symbolsKey ? symbolsKey.split(',') : []) }, [symbolsKey])

  // Refresh every price every few seconds while the page is visible. Depends on the list of symbols
  // only, so a price update doesn't restart the timer.
  const symbolsRef = useRef([])
  useEffect(() => {
    symbolsRef.current = symbolsKey ? symbolsKey.split(',') : []
  }, [symbolsKey])
  useEffect(() => {
    let stopped = false
    async function refresh() {
      const list = symbolsRef.current
      if (!list.length || document.hidden) return
      const results = await Promise.allSettled(list.map(fetchQuote))
      if (stopped) return
      const fresh = new Map()
      results.forEach(r => { if (r.status === 'fulfilled') fresh.set(r.value.symbol, r.value) })
      setWatchlist(current => current.map(q => fresh.has(q.symbol) ? { ...q, ...fresh.get(q.symbol) } : q))
      if (fresh.size) setUpdatedAt(new Date())
    }
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, REFRESH_MS)
    return () => { stopped = true; clearTimeout(first); clearInterval(timer) }
  }, [symbolsKey])

  useEffect(() => {
    const q = symbol.trim()
    if (!q) return
    const ctrl = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const r = await fetch(`/api/symbols/?q=${encodeURIComponent(q)}`, { signal: ctrl.signal })
        if (!r.ok) return
        const data = await r.json()
        setSuggestions(data.results || [])
        setActive(-1)
      } catch { /* aborted or offline: the plain input still works */ }
    }, 150)
    return () => { clearTimeout(timer); ctrl.abort() }
  }, [symbol])

  const addStock = async (raw = symbol) => {
    const sym = raw.trim().toUpperCase()
    if (!sym || loading) return
    setOpen(false)
    setError('')
    if (watchlist.some(q => q.symbol === sym)) { setError(`${sym} is already in your watchlist.`); return }
    setLoading(true)
    try {
      const quote = await fetchQuote(sym)
      if (watchlist.some(q => q.symbol === quote.symbol)) {
        setError(`${quote.symbol} is already in your watchlist.`)
      } else {
        setWatchlist(prev => [...prev, quote])
        window.mwCount?.('watchlist-add')
        setSymbol('')
        setSuggestions([])
      }
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Could not reach the server. Try again.' : err.message)
    }
    setLoading(false)
  }

  const removeStock = sym => setWatchlist(prev => prev.filter(q => q.symbol !== sym))

  const clearAll = () => {
    if (window.confirm(`Remove all ${watchlist.length} symbols from your watchlist?`)) setWatchlist([])
  }

  const onType = value => {
    setSymbol(value.toUpperCase())
    setOpen(Boolean(value.trim()))
    if (!value.trim()) setSuggestions([])
  }

  const onKeyDown = e => {
    const shown = open && suggestions.length > 0
    if (shown && e.key === 'ArrowDown') { e.preventDefault(); setActive((active + 1) % suggestions.length) }
    else if (shown && e.key === 'ArrowUp') { e.preventDefault(); setActive(active <= 0 ? suggestions.length - 1 : active - 1) }
    else if (shown && e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'Enter') { e.preventDefault(); addStock(shown && active >= 0 ? suggestions[active].symbol : symbol) }
  }

  const listShown = open && suggestions.length > 0

  return (
    <div className="wl">
      <header className="wl-head">
        <h1>Watchlist</h1>
        <p className="wl-sub">
          Stocks, ETFs, crypto and indices. Prices update every 5 seconds while this page is open;
          your list is saved in this browser.
        </p>
      </header>

      <form className="wl-form" role="search" onSubmit={e => { e.preventDefault(); addStock() }}>
        <div className="wl-input-wrap">
          <input
            className="wl-input"
            type="text"
            placeholder="Symbol or company name"
            aria-label="Symbol or company name"
            role="combobox"
            aria-autocomplete="list"
            aria-controls="watchlist-suggest"
            aria-expanded={listShown}
            aria-activedescendant={listShown && active >= 0 ? `watchlist-suggest-${active}` : undefined}
            autoComplete="off"
            spellCheck={false}
            value={symbol}
            onChange={e => onType(e.target.value)}
            onKeyDown={onKeyDown}
            onBlur={() => setOpen(false)}
            onFocus={() => setOpen(Boolean(symbol.trim()))}
          />
          {listShown && (
            <div id="watchlist-suggest" role="listbox" className="wl-suggest">
              {suggestions.map((r, i) => (
                <div
                  key={r.symbol}
                  id={`watchlist-suggest-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={e => { e.preventDefault(); addStock(r.symbol) }}
                >
                  <span className="sym">{r.symbol}</span>
                  <span className="name">{r.name}</span>
                  <span className="exch">{r.exchange}{r.etf ? ' · ETF' : ''}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <button type="submit" className="wl-add" disabled={loading}>{loading ? 'Adding…' : 'Add'}</button>
      </form>

      {error && <p className="wl-error" role="alert">{error}</p>}

      {watchlist.length === 0 ? (
        <div className="wl-empty">
          <p>Your watchlist is empty. Add a symbol above, or start with one of these:</p>
          <div className="wl-starters">
            {STARTERS.map(s => (
              <button key={s} type="button" onClick={() => addStock(s)} disabled={loading}>+ {s}</button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="wl-bar">
            <span>
              {watchlist.length} symbol{watchlist.length === 1 ? '' : 's'}
              {updatedAt && <> · updated {updatedAt.toLocaleTimeString()}</>}
            </span>
            <button type="button" className="wl-clear" onClick={clearAll}>Clear all</button>
          </div>
          <div className="wl-grid">
            {watchlist.map(q => <QuoteCard key={q.symbol} quote={q} onRemove={removeStock} />)}
          </div>
          <p className="wl-note">Prices from Yahoo Finance; the change is against the previous session's close.</p>
        </>
      )}
    </div>
  )
}

export default Watchlist
