#!/usr/bin/env python3
"""
flight-transfer-finder.py — v4
Uses fast_flights as a Python library (zero subprocess overhead)
with configurable timeout and improved concurrency.

Usage:
    python3 flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20
    python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3
"""

import argparse
import json
import hashlib
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

# ─────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────
VENV_PYTHON = Path.home() / ".hermes/venvs/flight-search/bin/python3"
CACHE_DIR = Path.home() / ".hermes/cache/flights"
HISTORY_FILE = Path.home() / ".hermes/data/flight-searches.jsonl"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
CACHE_DB = CACHE_DIR / "transfer_cache.db"

# ─────────────────────────────────────────────────────────────────
# IMPORT fast_flights AS A LIBRARY (zero subprocess overhead)
# ─────────────────────────────────────────────────────────────────
# Ensure we use the venv's Python packages
sys.path.insert(0, str(VENV_PYTHON.parent.parent / "lib/python3.14/site-packages"))
from fast_flights import FlightData, Passengers, get_flights  # type: ignore

# ─────────────────────────────────────────────────────────────────
# HUB REGIONS — 70+ airports
# ─────────────────────────────────────────────────────────────────
HUB_REGIONS = {
    "Northeast Asia": {
        "NRT": "Tokyo Narita", "HND": "Tokyo Haneda", "ICN": "Seoul Incheon",
        "TPE": "Taipei Taoyuan", "KIX": "Osaka Kansai", "FUK": "Fukuoka",
        "OKA": "Okinawa", "GMP": "Seoul Gimpo", "TSA": "Taipei Songshan",
    },
    "Greater China": {
        "PVG": "Shanghai Pudong", "PEK": "Beijing Capital", "CAN": "Guangzhou",
        "SZX": "Shenzhen", "XMM": "Xiamen", "CTU": "Chengdu", "XIY": "Xi'an",
        "HGH": "Hangzhou", "NKG": "Nanjing", "CKG": "Chongqing",
        "HAK": "Haikou", "SYX": "Sanya",
    },
    "Southeast Asia": {
        "SIN": "Singapore Changi", "BKK": "Bangkok Suvarnabhumi",
        "KUL": "Kuala Lumpur", "MNL": "Manila", "CGK": "Jakarta",
        "HAN": "Hanoi", "SGN": "Ho Chi Minh City", "SUB": "Surabaya",
        "DPS": "Bali Denpasar", "RGN": "Yangon", "PEN": "Penang",
    },
    "Middle East": {
        "DXB": "Dubai", "DOH": "Doha", "AUH": "Abu Dhabi",
        "DWC": "Dubai Al Maktoum", "SAW": "Istanbul Sabiha",
        "IST": "Istanbul Airport", "AMM": "Amman", "BEY": "Beirut",
    },
    "Europe": {
        "LHR": "London Heathrow", "FRA": "Frankfurt", "AMS": "Amsterdam",
        "CDG": "Paris CDG", "MAD": "Madrid", "BCN": "Barcelona",
        "FCO": "Rome Fiumicino", "MUC": "Munich", "ZRH": "Zurich",
        "VIE": "Vienna", "CPH": "Copenhagen", "ARN": "Stockholm",
        "OSL": "Oslo", "HEL": "Helsinki", "DUB": "Dublin", "MAN": "Manchester",
    },
    "South Asia": {
        "BOM": "Mumbai", "DEL": "Delhi", "BLR": "Bangalore",
        "MAA": "Chennai", "CCU": "Kolkata",
    },
    "US West Coast": {
        "LAX": "Los Angeles", "SFO": "San Francisco", "SEA": "Seattle",
        "PDX": "Portland", "SAN": "San Diego", "LAS": "Las Vegas",
        "SJC": "San Jose", "SMF": "Sacramento", "OAK": "Oakland",
    },
    "US East Coast": {
        "JFK": "New York JFK", "EWR": "Newark", "BOS": "Boston",
        "ORD": "Chicago O'Hare", "IAD": "Washington Dulles", "DCA": "Washington Reagan",
        "ATL": "Atlanta", "MIA": "Miami", "FLL": "Fort Lauderdale",
        "TPA": "Tampa", "PHL": "Philadelphia", "CLT": "Charlotte",
        "DTW": "Detroit", "BNA": "Nashville", "MSP": "Minneapolis",
    },
    "US Central": {
        "DFW": "Dallas Fort Worth", "DEN": "Denver", "IAH": "Houston Intercontinental",
        "AUS": "Austin", "STL": "St. Louis", "OMA": "Omaha",
        "SLC": "Salt Lake City", "PHX": "Phoenix", "ABQ": "Albuquerque",
    },
    "Canada & Mexico": {
        "YVR": "Vancouver", "YYZ": "Toronto Pearson", "YUL": "Montreal",
        "MEX": "Mexico City", "GDL": "Guadalajara", "CUN": "Cancun",
    },
    "Oceania": {
        "SYD": "Sydney", "MEL": "Melbourne", "BNE": "Brisbane",
        "PER": "Perth", "AKL": "Auckland", "WLG": "Wellington",
    },
    "Africa": {
        "JNB": "Johannesburg", "CPT": "Cape Town", "CAI": "Cairo",
        "NBO": "Nairobi", "LOS": "Lagos", "ACC": "Accra",
    },
}
ALL_HUBS = {code: city for region in HUB_REGIONS.values() for code, city in region.items()}

# ─────────────────────────────────────────────────────────────────
# ROUTE INTELLIGENCE
# ─────────────────────────────────────────────────────────────────
def get_relevant_hubs(origin: str, destination: str) -> list[str]:
    origin, destination = origin.upper(), destination.upper()
    US_WEST = {"LAX", "SFO", "SEA", "PDX", "SAN", "LAS", "SJC", "SMF", "OAK"}
    US_EAST = {"JFK", "EWR", "BOS", "ORD", "IAD", "DCA", "ATL", "MIA", "FLL", "TPA", "PHL", "CLT", "DTW", "BNA", "MSP"}
    US_CENTRAL = {"DFW", "DEN", "IAH", "AUS", "STL", "OMA", "SLC", "PHX", "ABQ"}
    US_ALL = US_WEST | US_EAST | US_CENTRAL | {"YVR"}
    NE_ASIA = {"NRT", "HND", "ICN", "TPE", "KIX", "FUK", "OKA", "GMP", "TSA"}
    CHINA = {"PVG", "PEK", "CAN", "SZX", "XMM", "CTU", "XIY", "HGH", "NKG", "CKG", "HAK", "SYX"}
    SEA = {"SIN", "BKK", "KUL", "MNL", "CGK", "HAN", "SGN", "SUB", "DPS", "RGN", "PEN"}
    ME = {"DXB", "DOH", "AUH", "DWC", "SAW", "IST", "AMM", "BEY"}
    EU = {"LHR", "FRA", "AMS", "CDG", "MAD", "BCN", "FCO", "MUC", "ZRH", "VIE", "CPH", "ARN", "OSL", "HEL", "DUB", "MAN"}
    SOUTH_ASIA = {"BOM", "DEL", "BLR", "MAA", "CCU"}

    if origin in US_ALL and destination in (NE_ASIA | CHINA | SEA | {"HKG"}):
        return list(NE_ASIA | CHINA) + list(US_WEST) + ["SIN", "BKK", "KUL"] + list(ME) + list(EU)
    if origin in (NE_ASIA | CHINA | SEA | {"HKG"}) and destination in US_ALL:
        return list(NE_ASIA) + ["SIN", "BKK"] + list(US_WEST) + list(CHINA) + list(US_EAST)
    if origin in EU and destination in (NE_ASIA | CHINA | SEA | {"HKG"}):
        return list(ME) + ["LHR", "FRA", "AMS", "IST"] + list(NE_ASIA) + ["SIN", "BKK"] + list(CHINA)
    if origin in US_ALL and destination in EU:
        return ["LHR", "FRA", "AMS", "CDG", "JFK", "EWR", "ORD", "IST"] + list(US_EAST) + list(US_WEST) + list(ME)
    if origin in US_ALL and destination in SOUTH_ASIA:
        return list(ME) + ["LHR", "DXB", "DOH"] + list(US_EAST) + list(US_WEST) + list(NE_ASIA)
    return list(NE_ASIA) + list(CHINA) + ["SIN", "BKK", "KUL"] + list(ME) + ["LHR", "FRA", "AMS", "IST"] + list(US_WEST) + list(US_EAST)


# ─────────────────────────────────────────────────────────────────
# CACHE — SQLite, thread-safe, 1-hour TTL
# ─────────────────────────────────────────────────────────────────
_cache_lock = Lock()
_cache_conns = {}
_route_semaphores: dict[str, object] = {}
_sem_lock = Lock()


def _get_route_sem(route_key: str) -> object:
    """Per-route semaphore to prevent thundering-herd on the same Google Flights query."""
    with _sem_lock:
        if route_key not in _route_semaphores:
            import threading
            _route_semaphores[route_key] = threading.Semaphore(1)
        return _route_semaphores[route_key]

def _get_cache_conn() -> sqlite3.Connection:
    tid = str(os.getpid())
    if tid not in _cache_conns:
        conn = sqlite3.connect(str(CACHE_DB), timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS flight_cache ("
                     "  key TEXT PRIMARY KEY,"
                     "  price INTEGER NOT NULL,"
                     "  best_flight TEXT,"
                     "  fetched_at REAL NOT NULL"
                     ")")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fetched ON flight_cache(fetched_at)")
        _cache_conns[tid] = conn
    return _cache_conns[tid]

def _cache_key(origin: str, destination: str, date: str, cabin: str) -> str:
    return hashlib.sha256(f"{origin}:{destination}:{date}:{cabin}".encode()).hexdigest()[:32]

CACHE_TTL = 3600  # 1 hour

def cache_get(origin: str, destination: str, date: str, cabin: str) -> tuple[int, str] | None:
    key = _cache_key(origin, destination, date, cabin)
    with _cache_lock:
        try:
            conn = _get_cache_conn()
            row = conn.execute(
                "SELECT price, best_flight, fetched_at FROM flight_cache WHERE key = ?", (key,)
            ).fetchone()
            if row and (time.time() - row[2]) < CACHE_TTL:
                return row[0], row[1]
        except sqlite3.Error:
            pass
    return None

def cache_set(origin: str, destination: str, date: str, cabin: str, price: int, best_flight: str):
    key = _cache_key(origin, destination, date, cabin)
    with _cache_lock:
        try:
            conn = _get_cache_conn()
            conn.execute(
                "INSERT OR REPLACE INTO flight_cache (key, price, best_flight, fetched_at) VALUES (?, ?, ?, ?)",
                (key, price, best_flight, time.time())
            )
            conn.commit()
        except sqlite3.Error:
            pass

def _cache_prune():
    try:
        conn = _get_cache_conn()
        deleted = conn.execute(
            "DELETE FROM flight_cache WHERE fetched_at < ?", (time.time() - CACHE_TTL * 48,)
        ).rowcount
        conn.commit()
        if deleted:
            print(f"   🗑️  Pruned {deleted} stale cache entries", flush=True)
    except sqlite3.Error:
        pass

try:
    _cache_prune()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────
# FLIGHT SEARCH — direct library call
# ─────────────────────────────────────────────────────────────────
@dataclass
class LegResult:
    price: int | None
    best_flight: str
    error: str = ""
    duration: float = 0.0
    cached: bool = False


def search_flight(
    origin: str, destination: str, date: str,
    cabin: str = "economy",
    use_cache: bool = True,
    no_cache: bool = False,
) -> LegResult:
    origin, destination = origin.upper(), destination.upper()
    if origin == destination:
        return LegResult(price=None, best_flight="", error="Same origin/destination")

    if use_cache and not no_cache:
        cached = cache_get(origin, destination, date, cabin)
        if cached:
            return LegResult(price=cached[0], best_flight=cached[1], cached=True)

    route_key = f"{origin}:{destination}:{date}:{cabin}"
    sem = _get_route_sem(route_key)
    with sem:
        start = time.time()
        try:
            result = get_flights(
                flight_data=[FlightData(from_airport=origin, to_airport=destination, date=date)],
                trip="one-way",
                passengers=Passengers(adults=1),
                seat=cabin,
            )
        except Exception as e:
            return LegResult(price=None, best_flight="", error=str(e), duration=time.time() - start)

    elapsed = time.time() - start

    if not result.flights:
        return LegResult(price=None, best_flight="", error="No flights", duration=elapsed)

    def _price(f):
        r = (f.price or '').strip()
        digits = re.sub(r'[^\d]', '', r)
        return int(digits) if digits else 999999

    cheapest = min(result.flights, key=_price)
    raw_price = cheapest.price or '$0'
    price = int(re.sub(r'[^\d]', '', raw_price)) if raw_price else 0
    best_str = f"{cheapest.name} {cheapest.departure} {cheapest.arrival} {cheapest.stops}stops {cheapest.price}"

    cache_set(origin, destination, date, cabin, price, best_str)
    return LegResult(price=price, best_flight=best_str, duration=elapsed)


# ─────────────────────────────────────────────────────────────────
# CORE TRANSFER FINDER
# ─────────────────────────────────────────────────────────────────
@dataclass
class TransferOption:
    hub: str
    hub_city: str
    leg1_price: int
    leg2_price: int
    total: int
    direct_price: int | None
    savings: int | None
    savings_pct: float | None
    leg1_flight: str = ""
    leg2_flight: str = ""


def find_transfers_for_route(
    origin: str, destination: str, date: str,
    cabin: str = "economy",
    max_workers: int = 16,
    all_hubs: bool = False,
    aggressive: bool = False,
    no_cache: bool = False,
) -> dict:
    origin, destination = origin.upper(), destination.upper()
    candidate_hubs = get_relevant_hubs(origin, destination)
    if all_hubs:
        candidate_hubs = [c for c in ALL_HUBS if c not in (origin, destination)]
    hub_cap = 60 if aggressive else 25
    hubs = candidate_hubs[:hub_cap]

    direct = search_flight(origin, destination, date, cabin, use_cache=not no_cache, no_cache=no_cache)
    direct_price = direct.price
    print(f"     {'💾' if direct.cached else '📍'} {origin}→{destination}: "
          f"${direct_price or 'N/A'}  ({'cached' if direct.cached else f'{direct.duration:.1f}s'})", flush=True)

    # Build all tasks
    tasks = [(hub, origin, hub) for hub in hubs] + [(hub, hub, destination) for hub in hubs]

    def runner(hub: str, orig: str, dest: str):
        r = search_flight(orig, dest, date, cabin, use_cache=not no_cache, no_cache=no_cache)
        return hub, orig, dest, r

    leg1_prices, leg2_prices = {}, {}
    leg1_flights, leg2_flights = {}, {}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(runner, h, o, d) for h, o, d in tasks]
        done = 0
        for future in as_completed(futures):
            hub, orig, dest, result = future.result()
            done += 1
            if result.price:
                if orig == origin and dest == hub:
                    leg1_prices[hub] = result.price
                    leg1_flights[hub] = result.best_flight
                elif orig == hub and dest == destination:
                    leg2_prices[hub] = result.price
                    leg2_flights[hub] = result.best_flight
            if done % 25 == 0 or done == len(futures):
                print(f"     ... {done}/{len(futures)} done", flush=True)

    options = []
    for hub in hubs:
        if hub not in leg1_prices or hub not in leg2_prices:
            continue
        l1, l2 = leg1_prices[hub], leg2_prices[hub]
        if l1 <= 0 or l2 <= 0:
            continue
        total = l1 + l2
        savings = (direct_price - total) if direct_price else None
        savings_pct = (savings / direct_price * 100) if savings else None
        options.append(TransferOption(
            hub=hub, hub_city=ALL_HUBS.get(hub, hub),
            leg1_price=l1, leg2_price=l2, total=total,
            direct_price=direct_price, savings=savings, savings_pct=savings_pct,
            leg1_flight=leg1_flights.get(hub, ""),
            leg2_flight=leg2_flights.get(hub, ""),
        ))

    options.sort(key=lambda x: x.total)
    return {
        "origin": origin, "destination": destination, "date": date, "cabin": cabin,
        "direct_price": direct_price,
        "direct_flight": direct.best_flight,
        "direct_cached": direct.cached,
        "hubs_checked": hubs,
        "hubs_with_data": len(leg1_prices),
        "transfer_options": [
            {"hub": o.hub, "hub_city": o.hub_city,
             "leg1_price": o.leg1_price, "leg2_price": o.leg2_price,
             "total": o.total, "direct_price": o.direct_price,
             "savings": o.savings, "savings_pct": o.savings_pct,
             "leg1_flight": o.leg1_flight, "leg2_flight": o.leg2_flight}
            for o in options
        ],
        "savings": [o for o in options if o.savings and o.savings > 0],
    }


# ─────────────────────────────────────────────────────────────────
# MULTI-DATE SCANNER
# ─────────────────────────────────────────────────────────────────
def expand_dates(center: str, flexible: int | None = None,
                 date_range: str | None = None) -> list[str]:
    if date_range:
        start_str, end_str = date_range.split(":")
        start = datetime.strptime(start_str.strip(), "%Y-%m-%d")
        end = datetime.strptime(end_str.strip(), "%Y-%m-%d")
        dates, current = [], start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates
    if flexible:
        center_dt = datetime.strptime(center, "%Y-%m-%d")
        return [(center_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(-flexible, flexible + 1)]
    return [center]


def multi_date_scan(
    origin: str, destination: str, dates: list[str],
    cabin: str, max_workers: int, all_hubs: bool, aggressive: bool, no_cache: bool,
) -> dict[str, dict]:
    print(f"\n  📅 Scanning {len(dates)} dates concurrently (max_workers={max_workers})...\n", flush=True)

    def scan_one(date: str) -> tuple[str, dict]:
        res = find_transfers_for_route(
            origin, destination, date, cabin,
            max_workers=min(max_workers, 8),
            all_hubs=all_hubs, aggressive=aggressive, no_cache=no_cache,
        )
        return date, res

    results = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(dates))) as ex:
        futures = {ex.submit(scan_one, d): d for d in dates}
        for future in as_completed(futures):
            date, res = future.result()
            results[date] = res
            dp = res.get("direct_price") or 0
            savings = res.get("savings") or []
            best = savings[0] if savings else None
            print(f"     [{len(results)}/{len(dates)}] {date}: direct=${dp}  "
                  f"{'| BEST: $'+str(best.total)+' (-'+str(round(best.savings_pct,1))+'%) via '+best.hub if best else '| no savings'}", flush=True)

    return results


# ─────────────────────────────────────────────────────────────────
# MULTI-ORIGIN SCANNER
# ─────────────────────────────────────────────────────────────────
def multi_origin_scan(
    origins: list[str], destination: str, date: str,
    cabin: str, max_workers: int, all_hubs: bool, aggressive: bool, no_cache: bool,
) -> dict[str, dict]:
    print(f"\n  🌏 Scanning {len(origins)} origins concurrently...\n", flush=True)

    def scan_one(origin: str) -> tuple[str, dict]:
        res = find_transfers_for_route(
            origin, destination, date, cabin,
            max_workers=min(max_workers, 8),
            all_hubs=all_hubs, aggressive=aggressive, no_cache=no_cache,
        )
        return origin, res

    results = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(origins))) as ex:
        futures = {ex.submit(scan_one, o): o for o in origins}
        for future in as_completed(futures):
            origin, res = future.result()
            results[origin] = res
            dp = res.get("direct_price") or 0
            savings = res.get("savings") or []
            best = savings[0] if savings else None
            print(f"     [{len(results)}/{len(origins)}] {origin}: direct=${dp}  "
                  f"{'| BEST: $'+str(best.total)+' (-'+str(round(best.savings_pct,1))+'%) via '+best.hub if best else '| no savings'}", flush=True)

    return results


# ─────────────────────────────────────────────────────────────────
# PERSISTENT HISTORY
# ─────────────────────────────────────────────────────────────────
def save_to_history(entry: dict):
    try:
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps({**entry, "saved_at": datetime.now().isoformat()}, default=str) + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────
# OUTPUT FORMATTERS
# ─────────────────────────────────────────────────────────────────
def format_single(results: dict) -> str:
    origin = results["origin"]; destination = results["destination"]
    date = results["date"]; cabin = results["cabin"]
    direct_price = results.get("direct_price") or 0
    no_direct = not direct_price
    options = results.get("transfer_options", [])
    savings = results.get("savings") or []

    W = 65
    out = []
    out.append("=" * W)
    out.append(f"✈️  {origin} → {destination}  |  {date}  |  {cabin.title()}")
    if no_direct:
        out.append(f"   ⚠️ No direct price data — showing hub combos by total cost")
    else:
        cached_tag = " 💾" if results.get("direct_cached") else ""
        out.append(f"   Direct: ${direct_price:,}{cached_tag}  |  "
                   f"{results['hubs_with_data']}/{len(results['hubs_checked'])} hubs with data")
    out.append("=" * W)

    if savings:
        out.append(f"\n✅ {len(savings)} cheaper transfer(s) found:\n")
        for i, o in enumerate(savings[:10], 1):
            out.append(f"  [{i:2d}] {origin} → {o['hub']} → {destination}")
            out.append(f"       {origin}→{o['hub']}: ${o['leg1_price']:,}  +  "
                      f"{o['hub']}→{destination}: ${o['leg2_price']:,}  =  ${o['total']:,}")
            out.append(f"       Save ${o['savings']:,} ({o['savings_pct']:.1f}%)   vs. direct ${direct_price:,}")
            out.append(f"       ({o['hub_city']})\n")
        best = savings[0]
        out.append(f"  🏆 BEST: {origin}→{best['hub']}→{destination} = ${best['total']:,}  "
                   f"save ${best['savings']:,} ({best['savings_pct']:.1f}%)")
        out.append(f"\n  ⚠️  Self-transfer: 2 separate one-ways | carry-on only | 3h+ buffer | check {best['hub']} transit visa")
        out.append(f"\n  🔗 Book: https://www.google.com/flights#flt={origin}.{best['hub']}/{date}")
        out.append(f"          https://www.google.com/flights#flt={best['hub']}.{destination}/{date}")
    elif options:
        out.append(f"\n❌ No transfer saves vs. direct (${direct_price:,}). {len(options)} hubs checked.")
        best = options[0]
        out.append(f"   Closest: {origin}→{best['hub']}→{destination} = ${best['total']:,} "
                   f"(+${best['total']-direct_price:,} more)")
    else:
        out.append(f"\n❌ No data retrieved. Check airport codes and date (2+ weeks out).")

    if options:
        out.append(f"\n📊 All {len(options)} hubs (sorted by total):")
        out.append(f"   {'Hub':<6} {'Leg1':>7} {'Leg2':>7} {'Total':>8} {'vs Direct':>12}")
        out.append(f"   {'-'*6} {'-'*7} {'-'*7} {'-'*8} {'-'*12}")
        for o in options[:12]:
            diff = (o['total'] - direct_price) if direct_price else None
            if diff is None:    diff_str, flag = "N/A", ""
            elif diff < 0:      diff_str, flag = f"-${-diff:,}", "✅"
            else:               diff_str, flag = f"+${diff:,}", "❌"
            out.append(f"   {o['hub']:<6} ${o['leg1_price']:>6,} ${o['leg2_price']:>6,} ${o['total']:>7,}  {diff_str:>12} {flag}")
        if len(options) > 12:
            out.append(f"   ... and {len(options)-12} more")

    out.append("\n" + "=" * W)
    return "\n".join(out)


def format_multi_date(all_results: dict, origin: str, destination: str, cabin: str) -> str:
    dates = sorted(all_results.keys())
    date_direct_prices, date_best_transfers, all_savings = {}, {}, []

    for date, res in all_results.items():
        dp = res.get("direct_price") or 0
        date_direct_prices[date] = dp
        savings_list = res.get("savings") or []
        if savings_list:
            best = savings_list[0]
            date_best_transfers[date] = best
            all_savings.append((date, best))

    all_savings.sort(key=lambda x: x[1].total if x[1].total else 999999)

    W = 70
    out = []
    out.append("=" * W)
    out.append(f"✈️  MULTI-DATE SCAN  |  {origin} → {destination}  |  {len(dates)} dates  |  {cabin.title()}")
    out.append("=" * W)

    out.append("\n📅 PRICE CALENDAR")
    out.append(f"   {'Date':<14} {'Direct':>8} {'Best Transfer':>13} {'Savings':>10}  Route")
    out.append(f"   {'-'*12} {'-'*8} {'-'*13} {'-'*10} {'-'*20}")
    for date in dates:
        dp = date_direct_prices[date]
        best = date_best_transfers.get(date)
        if best:
            out.append(f"   {date:<14} ${dp:>7,} ${best.total:>12,} {f'-{best.savings_pct:.1f}%':>10}  {origin}→{best.hub}→{destination}")
        elif dp:
            out.append(f"   {date:<14} ${dp:>7,} {'—':>13} {'—':>10}")
        else:
            out.append(f"   {date:<14} {'N/A':>8} {'—':>13} {'—':>10}")

    if all_savings:
        out.append(f"\n🏆 TOP TRANSFERS (sorted by total price):\n")
        for i, (date, best) in enumerate(all_savings[:10], 1):
            dp = date_direct_prices[date]
            out.append(f"  [{i:2d}] {date}  |  ${best.total:,}  |  save ${best.savings:,} ({best.savings_pct:.1f}%)")
            out.append(f"      {origin}→{best.hub}→{destination}  via {best.hub} ({best.hub_city})")
            out.append(f"      Direct: ${dp:,}  |  Leg1: ${best.leg1_price:,}  Leg2: ${best.leg2_price:,}\n")

        best_date, best_opt = all_savings[0]
        out.append(f"  🏆 BEST OVERALL: {origin}→{best_opt.hub}→{destination} on {best_date}")
        out.append(f"     Total: ${best_opt.total:,}  |  Save ${best_opt.savings:,} ({best_opt.savings_pct:.1f}%)")
        out.append(f"     ⚠️  Self-transfer: 2 one-ways | carry-on only | 3h+ buffer | check {best_opt.hub} transit visa")
        out.append(f"\n  🔗 Book leg 1: https://www.google.com/flights#flt={origin}.{best_opt.hub}/{best_date}")
        out.append(f"  🔗 Book leg 2: https://www.google.com/flights#flt={best_opt.hub}.{destination}/{best_date}")
    else:
        out.append(f"\n❌ No savings found across any of the {len(dates)} dates scanned.")

    out.append("\n" + "=" * W)
    return "\n".join(out)


def format_multi_origin(all_results: dict, destination: str, date: str, cabin: str) -> str:
    W = 70
    out = []
    out.append("=" * W)
    out.append(f"✈️  MULTI-ORIGIN SCAN  |  {len(all_results)} origins → {destination}  |  {date}  |  {cabin.title()}")
    out.append("=" * W)

    all_best = []
    for origin, res in sorted(all_results.items(), key=lambda x: x[1].get("direct_price") or 999999):
        dp = res.get("direct_price") or 0
        savings_list = res.get("savings") or []
        if savings_list:
            all_best.append((origin, dp, savings_list[0]))

    all_best.sort(key=lambda x: x[2].total if x[2].total else 999999)

    out.append(f"\n{'Origin':<6} {'Direct':>8} {'Best Transfer':>13} {'Savings':>10}  Via")
    out.append(f"   {'-'*4} {'-'*8} {'-'*13} {'-'*10} {'-'*20}")
    for origin, dp, best in all_best:
        out.append(f"   {origin:<6} ${dp:>7,} ${best.total:>12,} {f'-{best.savings_pct:.1f}%':>10}  {origin}→{best.hub}→{destination}")

    for origin, res in sorted(all_results.items(), key=lambda x: x[1].get("direct_price") or 999999):
        if not res.get("savings"):
            dp = res.get("direct_price") or 0
            out.append(f"   {origin:<6} ${dp:>7,} {'—':>13} {'—':>10}")

    if all_best:
        best_origin, best_dp, best_opt = all_best[0]
        out.append(f"\n  🏆 BEST: {best_origin}→{best_opt.hub}→{destination} = ${best_opt.total:,}")
        out.append(f"     Save ${best_opt.savings:,} ({best_opt.savings_pct:.1f}%)  vs. direct ${best_dp:,} from {best_origin}")
    out.append("\n" + "=" * W)
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Find cheaper self-transfer / hidden-city flight combinations. v4: direct fast_flights library, no subprocess.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3
  python3 flight-transfer-finder.py -o SFO,LAX,OAK -d HKG -dt 2026-05-20 --flexible 3
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 7 --aggressive --save-route
  python3 flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20 --timeout 300
        """
    )
    parser.add_argument("-o", "--origin", required=True,
                        help="Origin IATA(s), comma-separated for multi-origin")
    parser.add_argument("-d", "--destination", required=True, help="Destination IATA")
    parser.add_argument("-dt", "--date", required=True, help="Reference departure date (YYYY-MM-DD)")
    parser.add_argument("-c", "--cabin", default="economy",
                        choices=["economy", "premium-economy", "business", "first"])
    parser.add_argument("--flexible", type=int, metavar="N",
                        help="Scan ±N days around --date (e.g. 3 = 7 dates)")
    parser.add_argument("--date-range", metavar="START:END",
                        help="Explicit date range, e.g. 2026-05-15:2026-05-25")
    parser.add_argument("--origins", metavar="CODE,CODE",
                        help="Additional comma-separated origins")
    parser.add_argument("--aggressive", action="store_true", help="Check 60 hubs (default: 25)")
    parser.add_argument("--all-hubs", action="store_true", help="Check all 70+ hubs")
    parser.add_argument("--max-workers", type=int, default=8,
                        help="Concurrent threads (default: 8)")
    parser.add_argument("--no-cache", action="store_true", help="Bypass cache")
    parser.add_argument("--save-route", action="store_true", help="Save to history")
    parser.add_argument("--alert-below", type=int, metavar="PRICE",
                        help="Alert if best transfer is below this threshold")
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Overall timeout in seconds (default: 600)")

    args = parser.parse_args()

    primary_origins = [o.strip().upper() for o in args.origin.split(",")]
    if args.origins:
        extra = [o.strip().upper() for o in args.origins.split(",")]
        seen = set(primary_origins)
        for o in extra:
            if o not in seen:
                primary_origins.append(o); seen.add(o)
    all_origins = primary_origins

    dates = expand_dates(args.date, flexible=args.flexible, date_range=args.date_range)
    is_multi_date = len(dates) > 1
    is_multi_origin = len(all_origins) > 1

    print(f"\n{'='*70}")
    print(f"✈️  FLIGHT TRANSFER FINDER v4 — fast_flights library (no subprocess)")
    print(f"   Route: {' / '.join(all_origins)} → {args.destination}")
    print(f"   Date(s): {len(dates)} ({dates[0]} → {dates[-1]})" if is_multi_date else f"   Date: {dates[0]}")
    print(f"   Cabin: {args.cabin.title()}  |  Threads: {args.max_workers}")
    print(f"   Mode: {'Aggressive' if args.aggressive else ('All hubs' if args.all_hubs else 'Normal')} | "
          f"{'Multi-origin' if is_multi_origin else 'Single origin'} | "
          f"{'Multi-date' if is_multi_date else 'Single date'}")
    print(f"   Cache: {'BYPASS' if args.no_cache else 'ON (1h TTL)'}  |  Timeout: {args.timeout}s")
    print(f"{'='*70}", flush=True)

    start_time = time.time()

    def remaining() -> bool:
        return (time.time() - start_time) < args.timeout

    # Multi-origin × Multi-date
    if is_multi_origin and is_multi_date:
        origin_results = {}
        for origin in all_origins:
            if not remaining():
                print(f"\n⏱️  Timeout reached, stopping."); break
            res = multi_date_scan(origin, args.destination, dates, args.cabin,
                                  max_workers=args.max_workers, all_hubs=args.all_hubs,
                                  aggressive=args.aggressive, no_cache=args.no_cache)
            origin_results[origin] = res

        flattened = []
        for origin, date_results in origin_results.items():
            for date, res in date_results.items():
                savings = res.get("savings") or []
                if savings:
                    flattened.append((origin, date, savings[0], res.get("direct_price") or 0))
        flattened.sort(key=lambda x: x[2].total if x[2].total else 999999)

        W = 70
        out = []
        out.append("=" * W)
        out.append(f"✈️  MULTI-ORIGIN × MULTI-DATE  |  {len(all_origins)} origins × {len(dates)} dates")
        out.append("=" * W)
        if flattened:
            out.append(f"\n🏆 TOP {min(10, len(flattened))} COMBOS:\n")
            for i, (origin, date, best, dp) in enumerate(flattened[:10], 1):
                out.append(f"  [{i:2d}] {origin}→{best.hub}→{args.destination}  |  {date}  |  ${best.total:,}")
                out.append(f"      Save ${best.savings:,} ({best.savings_pct:.1f}%)  vs. direct ${dp:,}\n")
            best_triple = flattened[0]
            out.append(f"  🏆 BEST: {best_triple[0]}→{best_triple[2].hub}→{args.destination} "
                       f"on {best_triple[1]} = ${best_triple[2].total:,}")
        else:
            out.append("\n❌ No savings found.")
        out.append("\n" + "=" * W)
        print("\n".join(out))
        if args.save_route:
            for origin, date_results in origin_results.items():
                for date, res in date_results.items():
                    savings = res.get("savings") or []
                    if savings:
                        save_to_history({"type": "multi_origin_date", "origin": origin,
                                         "destination": args.destination, "date": date,
                                         "best_transfer": asdict(savings[0]), "all_results": res})

    # Multi-date only
    elif is_multi_date:
        results_by_date = {}
        for date in dates:
            if not remaining():
                print(f"\n⏱️  Timeout reached, stopping."); break
            _, res = multi_date_scan(all_origins[0], args.destination, [date], args.cabin,
                                    max_workers=args.max_workers, all_hubs=args.all_hubs,
                                    aggressive=args.aggressive, no_cache=args.no_cache).__next__() \
                if False else None, None
            # simpler: scan one date at a time through multi_date_scan
        results_by_date = multi_date_scan(
            all_origins[0], args.destination, dates, args.cabin,
            max_workers=args.max_workers, all_hubs=args.all_hubs,
            aggressive=args.aggressive, no_cache=args.no_cache,
        )
        if args.json:
            print(json.dumps(results_by_date, indent=2, default=str)); return
        print(format_multi_date(results_by_date, all_origins[0], args.destination, args.cabin))
        if args.save_route:
            for date, res in results_by_date.items():
                savings = res.get("savings") or []
                if savings:
                    save_to_history({"type": "multi_date", "origin": all_origins[0],
                                     "destination": args.destination, "date": date,
                                     "best_transfer": asdict(savings[0]), "all_results": res})

    # Multi-origin only
    elif is_multi_origin:
        results_by_origin = multi_origin_scan(
            all_origins, args.destination, dates[0], args.cabin,
            max_workers=args.max_workers, all_hubs=args.all_hubs,
            aggressive=args.aggressive, no_cache=args.no_cache,
        )
        if args.json:
            print(json.dumps(results_by_origin, indent=2, default=str)); return
        print(format_multi_origin(results_by_origin, args.destination, dates[0], args.cabin))
        if args.save_route:
            for origin, res in results_by_origin.items():
                savings = res.get("savings") or []
                if savings:
                    save_to_history({"type": "multi_origin", "origin": origin,
                                     "destination": args.destination, "date": dates[0],
                                     "best_transfer": asdict(savings[0]), "all_results": res})

    # Single route
    else:
        if not remaining():
            print(f"\n⏱️  Timeout already reached before single route search."); return
        result = find_transfers_for_route(
            all_origins[0], args.destination, dates[0], args.cabin,
            max_workers=args.max_workers, all_hubs=args.all_hubs,
            aggressive=args.aggressive, no_cache=args.no_cache,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str)); return
        print(format_single(result))
        savings = result.get("savings") or []
        if args.alert_below and savings:
            best = savings[0]
            if best.total and best.total < args.alert_below:
                print(f"\n🔔 ALERT: Best transfer ${best.total:,} is below your threshold ${args.alert_below:,}")
        if args.save_route and savings:
            save_to_history({"type": "single", "origin": all_origins[0],
                             "destination": args.destination, "date": dates[0],
                             "cabin": args.cabin, "best_transfer": asdict(savings[0]),
                             "all_results": result})

    elapsed = time.time() - start_time
    print(f"\n⏱️  Completed in {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
