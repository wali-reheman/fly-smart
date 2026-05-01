---
name: fly-smart
description: Find cheaper flight routes using hidden-city arbitrage and hub transfer combinations — exploits pricing differences between airlines and routes that Google Flights doesn't surface directly. No API keys. Supports 70+ global hubs, multi-date and multi-origin scanning, SQLite caching, and self-transfer detection.
license: MIT
metadata:
  author: wali-reheman
  version: "1.0.0"
  tags: [flights, travel, self-transfer, hidden-city, google-flights, budget-travel, arbitrage, hub-transfer]
triggers:
  - "search flights"
  - "find flights"
  - "flight deals"
  - "cheap flights"
  - "flights from X to Y"
  - "transfer flights"
  - "hidden city"
  - "self transfer"
  - "fly smart"
  - "cheaper route"
tools:
  - terminal
  - web_search
  - browser
---

# Flight Search Skill

## Tool Setup

**Python library**: `fast_flights` — calls Google Flights via httpx, no subprocess.

**Installation** (venv required due to PEP 668):
```bash
python3 -m venv ~/.hermes/venvs/flight-search
~/.hermes/venvs/flight-search/bin/pip install flight-search
```

**CLI binary**: `~/.hermes/venvs/flight-search/bin/flight-search`

---

## 1. Direct Flight Search (CLI)

```bash
~/.hermes/venvs/flight-search/bin/flight-search <ORIGIN> <DESTINATION> -d YYYY-MM-DD [options]
```

| Option | Description |
|--------|-------------|
| `-d YYYY-MM-DD` | Departure date (required) |
| `-r YYYY-MM-DD` | Return date |
| `-a N` | Adults (default 1) |
| `-C` | Cabin: economy, premium-economy, business, first |
| `-l N` | Max results |
| `-o text\|json` | Output format |

---

## 2. Transfer Finder v4 — Self-Transfer / Hidden-City

**Script**: `~/.hermes/scripts/flight-transfer-finder.py`

Calls `fast_flights` as a Python library (zero subprocess overhead). Per-route semaphore prevents Google rate-limiting. Checks 70+ global hubs concurrently with SQLite cache (1h TTL).

### fast_flights Library Usage Pattern

**Correct import** (venv Python, not system Python):
```python
import sys
sys.path.insert(0, "~/.hermes/venvs/flight-search/lib/python3.14/site-packages")
from fast_flights import FlightData, Passengers, get_flights
```

**Correct API call**:
```python
result = get_flights(
    flight_data=[FlightData(from_airport="LAX", to_airport="HKG", date="2026-05-20")],
    trip="one-way",
    passengers=Passengers(adults=1),
    seat="economy",
)
# result.flights: list of Flight namedtuples with .price, .name, .departure, .arrival, .stops
```

**Common mistakes**:
- ❌ `FlightData(origin=..., destination=...)` — wrong field names, use `from_airport`/`to_airport`
- ❌ `Passengers(adults=1)` without import — must `from fast_flights import Passengers`
- ❌ Calling from system Python — httpx version mismatch, must use venv Python
- ❌ Concurrent calls to same route from multiple threads — triggers Google rate limiting; use per-route semaphore
- ❌ 16+ threads for httpx — connection pool exhausts at ~16; 8 threads is optimal

### Concurrency Architecture

```
ThreadPoolExecutor(max_workers=8)
  └─ search_flight(origin, dest, date, cabin)
       ├─ cache_get()  → SQLite (thread-safe, 1h TTL)
       ├─ per-route semaphore (prevents thundering herd on same URL)
       └─ get_flights()  → httpx → Google Flights
```

**Per-route semaphore pattern** (critical for Google rate-limit survival):
```python
_route_semaphores: dict[str, threading.Semaphore] = {}
_sem_lock = Lock()

def _get_route_sem(route_key: str) -> threading.Semaphore:
    with _sem_lock:
        if route_key not in _route_semaphores:
            _route_semaphores[route_key] = threading.Semaphore(1)
        return _route_semaphores[route_key]

# In search_flight():
with _get_route_sem(f"{origin}:{destination}:{date}:{cabin}"):
    result = get_flights(...)
```

### Debugging / Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ValueError: invalid literal for int()` on price | Flight.price is empty/whitespace string | Strip price, check digits before int() conversion |
| `TypeError: get_flights() got unexpected keyword argument` | Wrong field names on FlightData | Use `from_airport`/`to_airport`, not `origin`/`destination` |
| `ModuleNotFoundError: No module named 'playwright'` | Called with `fetch_mode='local'` | Don't use `fetch_mode='local'`; 'common' mode works fine |
| `Impersonate 'chrome_126' does not exist` | Normal httpx impersonation warning | Safe to ignore; fast_flights falls back to random user agent |
| All calls return `$N/A` prices | 16+ threads overwhelming Google | Reduce to 8 workers; per-route semaphore prevents thundering herd |
| `ValueError: min() arg is an empty sequence` | All flights filtered out | Check price parsing; empty-string prices crash `min()` |

### Hub Routing Intelligence

The script uses `get_relevant_hubs(origin, destination)` to pick 25 contextually relevant hubs instead of all 70+. Logic:
- US West Coast → Asia/HKG: bias toward Northeast Asia + Greater China + SEA hubs
- East Coast US → Europe: bias toward LHR/FRA/AMS/CDG + Middle East + US East
- Override with `--aggressive` (60 hubs) or `--all-hubs` (all 70+)

### Examples

```bash
# Single date
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20

# Multi-date ±3 days (7 dates in parallel)
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3

# Multi-origin
python3 ~/.hermes/scripts/flight-transfer-finder.py -o SFO,LAX,OAK -d HKG -dt 2026-05-20

# Full power: ±7 days, 60 hubs, save history, 10min timeout
python3 ~/.hermes/scripts/flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 \
  --flexible 7 --aggressive --save-route --timeout 600
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-o` | Origin(s), comma-separated | required |
| `-d` | Destination IATA | required |
| `-dt` | Reference departure date | required |
| `--flexible N` | Scan ±N days around --dt | off |
| `--date-range START:END` | Explicit YYYY-MM-DD:YYYY-MM-DD range | off |
| `--aggressive` | Check 60 hubs (default: 25) | off |
| `--all-hubs` | Check all 70+ hubs | off |
| `--max-workers N` | Concurrent threads (8 is optimal) | 8 |
| `--no-cache` | Bypass cache, force fresh | cache on |
| `--save-route` | Append results to `~/.hermes/data/flight-searches.jsonl` | off |
| `--alert-below PRICE` | Only report if best transfer < PRICE | off |
| `--timeout N` | Overall timeout in seconds | 600 |
| `--json` | Raw JSON output | off |

### Hub Regions (70+ airports)

Northeast Asia (NRT, HND, ICN, TPE, KIX…), Greater China (PVG, PEK, CAN, SZX…), Southeast Asia (SIN, BKK, KUL…), Middle East (DXB, DOH, IST…), Europe (LHR, FRA, AMS, CDG…), US West/East/Central, Canada/Mexico, Oceania, Africa.

> **See also**: `references/transfer-routes.md` — route-specific hub recommendations (e.g. US→HKG: TPE/SEA/NRT dominate; Europe→HKG: DXB/DOH competitive).

### Self-Transfer Rules

- Book **two separate one-way tickets** — not a round-trip
- **No checked bags** — carry-on + personal item only
- **3h+ buffer** between connecting legs
- Check **transit visa** requirements for the hub country

### Performance (v4 vs v3)

| Scan | v3 (subprocess) | v4 (library + semaphore) |
|------|----------------|--------------------------|
| DC × 3 origins × 7 dates | 214s | **66s** |
| CA × 5 origins × 7 dates | timeout | **118s** |

**Why Python + httpx is optimal here, not Rust**: the bottleneck is network I/O (waiting for Google's servers to respond), not CPU computation. Rust would not make HTTP faster. The async httpx layer already saturates the network pipe efficiently.

---

## 3. Alternatives

| Method | Best For | API Key |
|--------|----------|---------|
| `flight-search` CLI | Quick terminal lookups | No |
| Transfer Finder v4 | Self-transfer / hidden-city deals | No |
| Browser automation (Chrome CDP) | Full interactive search, multi-city | No |
| MCP server `fli` | AI assistant integration | No |
| Skyscanner / Amadeus API | Production apps needing licensed data | Yes |
