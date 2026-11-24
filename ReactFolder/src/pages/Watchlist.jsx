import { useState, useEffect } from 'react'
import '../App.css'

function Watchlist() {
  const [symbol, setSymbol] = useState('') // The Input Box Memory. It stores whatever text the user is currently typing into the search bar
  const [watchlist, setWatchlist] = useState([]) //stores the list of all stocks added by the user.
  const [loading, setLoading] = useState(false)
    // The Status Flag bool true or false
    // false: The app is doing nothing (Button says "Add Stock").
    // true: The app is currently waiting for the server to reply (Button says "Adding...").
  const [error, setError] = useState('')
    // A text message explaining what went wrong
    // (e.g., "Stock not found" or "Server Down").
    // Initial Value: '' (Empty string). This means "No error, everything is fine."

  // Suggestions under the input: US stocks and ETFs matching the symbol or company name typed.
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

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

  const onType = (value) => {
    setSymbol(value.toUpperCase())
    setOpen(Boolean(value.trim()))
    if (!value.trim()) setSuggestions([])
  }

  const onKeyDown = (e) => {
    const shown = open && suggestions.length > 0
    if (shown && e.key === 'ArrowDown') { e.preventDefault(); setActive((active + 1) % suggestions.length) }
    else if (shown && e.key === 'ArrowUp') { e.preventDefault(); setActive(active <= 0 ? suggestions.length - 1 : active - 1) }
    else if (shown && e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'Enter') { e.preventDefault(); handleAddStock(shown && active >= 0 ? suggestions[active].symbol : symbol) }
  }

  // 1. Function to add a NEW stock
  const handleAddStock = async (sym = symbol) => {
    sym = sym.trim().toUpperCase()
    if (!sym) return;
    setOpen(false);
    // Without this line, if a user clicked "Add Stock" while the box was empty,
      // the app would send a request to /api/get-price/?symbol=,
      // which would likely crash the backend or return a messy error.
      // This line protects the app from doing unnecessary work.


    setLoading(true); //The button text instantly changes from "Add Stock" to "Adding...".
      // It prevents the user from double-clicking.
      // If they clicked 5 times quickly, you would accidentally add the same stock 5 times.
      // This "freezes" the button until the work is done.
    setError('');
    // It clears out any text inside your error state variable
      // user d'ont see any old errors


      // limit the api calls and number of stocks a user can add to 5
      // if (watchlist.length >= 5 )
      // {
      //     setError("Maximum limit of 5 stocks reached!")
      //     setLoading(false); // Don't forget to turn off loading!
      //     return;
      // }

    try {
      const response = await fetch(`/api/get-price/?symbol=${encodeURIComponent(sym)}`);
      const data = await response.json();

      // the response should be constant , we do not want it to change
      // preventing accidental overwrites. and good practice

      // await is like a "Pause Button"
      // JavaScript pauses at that line. It basically says:
        // "I will wait right here until the server replies.
        // I won't run the next line until I have the data in my hand.
      // response.json() is important so we can access data.symbol or data.price
        // to turn the http response data to something JS can use

      if (data.error) {
        setError(data.error);
      } else {
        if (watchlist.some(item => item.symbol === data.symbol)) {
          setError("Stock already in list!");
        } else {
          setWatchlist(prev => [...prev, data]);
          setSymbol('');
          setSuggestions([]);
        }
      }
    } catch (err) {
      setError("Could not connect to Django backend or Invalid Symbol");
    }
    setLoading(false);
  };

  // 2. The "Heartbeat" Effect (Updates prices every 5 seconds)
  useEffect(() => {
    const interval = setInterval(() => {
      // We save this timer into a variable named interval
      // Loop through every stock in the list and get the new price
      watchlist.forEach(async (stock) => {
        try {
            const response = await fetch(`/api/get-price/?symbol=${stock.symbol}`);
            const updatedData = await response.json();
            // Update the list with the new data
            if (!updatedData.error) {
                setWatchlist(currentList =>
                    currentList.map(item =>
                        item.symbol === updatedData.symbol ? updatedData : item
                    )
                );
            }
        } catch (err) {
            console.log("Update failed for", stock.symbol);
        }
      });
    }, 5000); // <--- 5000 milliseconds = 5 seconds

    // However, in a real production environment, I would probably increase this to 10 or 15 seconds
    //  to avoid hitting API Rate Limits (blocking)
    // from the data provider and to reduce the load on our backend servers."

    // Cleanup: Stop the timer if the user leaves the page
    return () => clearInterval(interval);
  }, [watchlist]);

  // 3. Delete function
  const removeStock = (symbolToRemove) => {
    setWatchlist(watchlist.filter(s => s.symbol !== symbolToRemove));
  };

  // remove all function

    const clearAll = () => {
        setWatchlist([]) ;
    }

  return (
    <div className="app-container">
      <h1 className="title">Live Watchlist</h1>

{/*The <strong> keyword is an HTML tag used to define text with strong importance.*/}
{/*By default, all web browsers render text inside <strong> tags as Bold.*/}

      {/* --- NEW INFO BOX START --- */}
      <div className="info-box">
        <p><strong>Welcome to your Real-Time Dashboard!</strong></p>
        <ul>
            <li><strong>Track Assets:</strong> Add your favorite Stocks (e.g., AAPL) or Crypto (e.g., BTC-USD).</li>
            <li><strong>Live Updates:</strong> Prices refresh automatically every <strong>5 seconds</strong>.</li>
            <li><strong>Stay Ahead:</strong> Monitor market movements instantly without refreshing.</li>
        </ul>
      </div>
      {/* --- NEW INFO BOX END --- */}


      <div className="search-box">
        <div className="suggest-wrap">
          <input
            type="text"
            placeholder="Symbol or company (e.g., NVDA)"
            aria-label="Symbol or company name"
            role="combobox"
            aria-autocomplete="list"
            aria-controls="watchlist-suggest"
            aria-expanded={open && suggestions.length > 0}
            aria-activedescendant={open && active >= 0 ? `watchlist-suggest-${active}` : undefined}
            autoComplete="off"
            spellCheck={false}
            value={symbol}
            onChange={(e) => onType(e.target.value)}
            onKeyDown={onKeyDown}
            onBlur={() => setOpen(false)}
            onFocus={() => setOpen(Boolean(symbol.trim()))}
          />
          {open && suggestions.length > 0 && (
            <div id="watchlist-suggest" role="listbox" className="watchlist-suggest">
              {suggestions.map((r, i) => (
                <div
                  key={r.symbol}
                  id={`watchlist-suggest-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => { e.preventDefault(); handleAddStock(r.symbol) }}
                >
                  <span className="sym">{r.symbol}</span>
                  <span className="name">{r.name}</span>
                  <span className="exch">{r.exchange}{r.etf ? ' · ETF' : ''}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <button onClick={() => handleAddStock()} disabled={loading}>
          {loading ? 'Adding...' : 'Add Stock or Crypto'}
        </button>
      </div>

      {error && <p className="error-msg">{error}</p>}

      <div className="stock-grid">
          {/*   This is a loop. It goes through every single item inside the watchlist array.*    /}
{/* Translation: "For every stock in my list, create this HTML structure."*/}
        {watchlist.map((stock) => (

          <div key={stock.symbol} className="stock-card">
            <div className="card-header">
              <h3>{stock.symbol}</h3>
              <button className="delete-btn" onClick={() => removeStock(stock.symbol)}>×</button>

            </div>
            {/* Added a key to force animation on change */}
            <div className="price" key={stock.price}>${stock.price}</div>
            <div className={`change ${stock.change >= 0 ? 'green' : 'red'}`}>
              {stock.change > 0 ? '+' : ''}{stock.change} ({stock.change_pct}%)
            </div>

              {/*this is the remove all stocks button*/}
              {/*<button onClick={clearAll} className="delete-btn">Clear All</button>*/}
              {/*show the total number of stocks added and currently live */}
              {/*<p>Currently Tracking: {watchlist.length} assets </p>*/}

          </div>
        ))}
      </div>
    </div>
  )
}

export default Watchlist


//
// key={stock.symbol}
// What is it? A unique ID tag for React.
// Why is it needed? React needs to track which items change, are added, or are deleted.
// If you don't give each item a unique key, React might get confused
// and re-render the whole list (which is slow) or show bugs.


// "useEffect manages the lifecycle of the component to ensure we only start one timer.
// setInterval creates the loop that fetches new data every 5 seconds.
// Together, they create the 'live' experience without crashing the browser."

// onClick={...}: This tells React "When someone clicks this element, run the code inside the curly braces.

// () => ...: This is an Arrow Function. It effectively says "Wait until the click happens, THEN run this."

// Interview Tip: If i just write onClick={removeStock(stock.symbol)}
// (without the arrow function),
// it would run immediately when the page loads and delete everything instantly.
// The arrow function prevents that.



  // useEffect(() => {
  // What it is: This is a React Hook. It tells React to run some code
  // after the component has finished rendering .
  // useEffect acts like a gatekeeper. It ensures the timer starts only
  // once when the component first loads (or when watchlist changes)