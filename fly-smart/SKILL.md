---
name: fly-smart
description: Find cheaper flight routes using hidden-city arbitrage and hub transfer combinations. Activates when users search for flights, find cheap flights, compare routes, or look for budget travel deals. Supports 70+ global hubs, multi-date scanning, SQLite caching, and self-transfer detection. No API keys required.
version: "1.0.0"
license: MIT
compatibility: macOS, Linux (Python 3.10+ with venv)
metadata:
  author: wali-reheman
  hermes:
    tags: [flights, travel, self-transfer, hidden-city, google-flights, budget-travel, arbitrage, hub-transfer]
    category: productivity
required_environment_variables:
  - name: VENV_PATH
    prompt: Python venv path for flight-search
    help: Defaults to ~/.hermes/venvs/flight-search. Only change if custom path needed.
    required_for: all operations
---

# Flight Search Skill

## When to Use

- User asks to search for flights, find cheap flights, or compare flight routes
- User wants to find the cheapest way to fly between two cities
- User mentions "hidden city", "self transfer", "transfer flights", or "hub hopping"
- User asks about budget travel or arbitrage opportunities in airfares
- User wants multi-date flight searches or flexible date options
- User wants to search flights from multiple nearby airports simultaneously

## Procedure

### Step 1 — Set Up the Python Environment

Create an isolated venv (required due to PEP 668 dependency conflicts):

```bash
python3 -m venv ~/.hermes/venvs/flight-search
~/.hermes/venvs/flight-search/bin/pip install flight-search
```

The venv installs the `flight-search` CLI at:
`~/.hermes/venvs/flight-search/bin/flight-search`

And the `flight-transfer-finder.py` script at:
`~/.hermes/scripts/flight-transfer-finder.py`

### Step 2 — Quick Direct Flight Search (CLI)

For single-date, direct origin→destination lookups:

```bash
~/.hermes/venvs/flight-search/bin/flight-search <ORIGIN> <DESTINATION> -d YYYY-MM-DD [options]
```

**Options:**
- `-d YYYY-MM-DD` — Departure date (required)
- `-r YYYY-MM-DD` — Return date
- `-a N` — Number of adults (default: 1)
- `-C cabin` — Cabin class: economy, premium-economy, business, first
- `-l N` — Max results to return
- `-o text|json` — Output format

### Step 3 — Transfer Finder for Hidden-City and Hub Arbitrage

For cheaper routes via intermediate hubs (separate tickets, no checked bags):

```bash
python3 ~/.hermes/scripts/flight-transfer-finder.py -o <ORIGIN> -d <DESTINATION> -dt <YYYY-MM-DD> [options]
```

**Key arguments:**
- `-o` — Origin airport(s), comma-separated for multi-origin searches
- `-d` — Destination airport IATA code
- `-dt` — Reference departure date
- `--flexible N` — Scan ±N days around the reference date
- `--aggressive` — Check 60 hubs (default: 25 contextually chosen hubs)
- `--all-hubs` — Check all 70+ global hubs
- `--save-route` — Append results to `~/.hermes/data/flight-searches.jsonl`
- `--json` — Raw JSON output for programmatic processing

### Step 4 — Interpret Results

The script returns a sorted list of route options:
- **Direct**: Standard non-stop or single-ticket routes
- **Transfer**: Two separate tickets via a hub — cheaper but requires:
  - No checked bags (carry-on + personal item only)
  - 3+ hours between legs for immigration/customs/terminal transfer
  - Valid transit visa for the hub country if needed

### Step 5 — Verify Successful Search

- Results show price in USD, departure/arrival times, stops, and cabin
- Empty price fields (`$N/A`) indicate the route was rate-limited — retry with fewer threads or cache bypass
- SQLite cache expires after 1 hour; use `--no-cache` to force fresh results

## Examples

### Example 1: Single date, direct route

```
Input: "Find flights from LAX to HKG on May 20th"
Expected behavior: Run `flight-search LAX HKG -d 2026-05-20` and present top results with prices, times, and stops.
```

### Example 2: Cheaper route via transfer

```
Input: "Find the cheapest way to fly from SFO to HKG, I don't mind a layover"
Expected behavior: Run transfer finder with `--flexible 3` to check ±3 days across 25+ hubs. Present savings vs direct booking.
```

### Example 3: Multi-origin power search

```
Input: "Compare flights from SFO, LAX, and OAK to Bangkok for mid-June"
Expected behavior: Run transfer finder with `-o SFO,LAX,OAK -d BKK -dt 2026-06-15 --flexible 5`. Aggregate and rank all results.
```

## Pitfalls

- **Wrong field names crash `get_flights()`**: Use `from_airport`/`to_airport`, NOT `origin`/`destination` — the API uses different field names than typical conventions
- **System Python vs venv Python**: Always call from the venv Python, not system Python — httpx version mismatch causes `ModuleNotFoundError`
- **16+ threads triggers Google rate-limiting**: Use 8 threads max; the per-route semaphore prevents thundering herd but thread count still matters
- **Empty price strings crash `min()`**: Some routes return `$N/A` or blank prices — always validate price is numeric before `int()` conversion
- **Self-transfer requires two separate bookings**: These are notrefundable if one leg cancels; do not use for tight connections
- **3-hour minimum connection time for self-transfer**: Less time risks missing the second leg due to delays, customs, or terminal transfers

## Verification

- Run `python3 ~/.hermes/scripts/flight-transfer-finder.py -o <ORIGIN> -d <DEST> -dt <DATE> --json` and confirm JSON output with valid prices
- Confirm no `ModuleNotFoundError` or `ValueError` in stderr
- For rate-limit cases, verify `--no-cache` bypasses stale cached `$N/A` results
- Confirm results are sorted by total price ascending
