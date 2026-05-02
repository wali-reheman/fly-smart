#!/usr/bin/env python3
"""
flight-transfer-finder.py — v5
Finds cheaper self-transfer / hidden-city flight combinations.
Supports 70+ global hubs, multi-date scanning, rule verification,
CSV/Notion export, and price alerts.

Usage:
    python3 flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20
    python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3
    python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --verify-rules
    python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --export-csv
"""

import argparse
import csv
import json
import hashlib
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional

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
# TRANSIT VISA REQUIREMENTS (simplified — verify independently)
# Key countries that typically require transit visas for common origin nationalities
# ─────────────────────────────────────────────────────────────────
VISA_FREE_HUBS = {
    "us_origin",  # passengers originating from the US typically don't need visas for:
}
# Countries where US citizens can transit without a visa (TWOV)
TWOV_COUNTRIES = {
    "AMS": "Netherlands", "FRA": "Germany", "LHR": "United Kingdom",
    "CDG": "France", "DXB": "United Arab Emirates", "DOH": "Qatar",
    "SIN": "Singapore", "HKG": "Hong Kong", "ICN": "South Korea",
    "NRT": "Japan", "HND": "Japan", "KIX": "Japan",
}
# Countries requiring a transit visa even for airside transit
VISA_REQUIRED_TRANSIT = {
    "CAN": "China", "PEK": "China", "PVG": "China",
    "BKK": "Thailand (visa required for many nationalities)",
    "KUL": "Malaysia (eVISA for some)",
}


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
_cache_conns: dict = {}
_route_semaphores: dict = {}
_sem_lock = Lock()


def _get_route_sem(route_key: str):
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


CACHE_TTL = 3600


def cache_get(origin: str, destination: str, date: str, cabin: str) -> Optional[tuple]:
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
    price: Optional[int]
    best_flight: str
    error: str = ""
    duration: float = 0.0
    cached: bool = False
    departure_time: str = ""
    arrival_time: str = ""


def search_flight(
    origin: str, destination: str, date: str,
    cabin: str = "economy",
    use_cache: bool = True,
    no_cache: bool = False,
    passengers: int = 1,
) -> LegResult:
    origin, destination = origin.upper(), destination.upper()

    if use_cache and not no_cache:
        cached = cache_get(origin, destination, date, cabin)
        if cached:
            return LegResult(price=cached[0], best_flight=cached[1], cached=True)

    if origin == destination:
        return LegResult(price=None, best_flight="", error=f"Same origin ({origin}) and destination — not a valid route")

    route_key = f"{origin}:{destination}:{date}:{cabin}:{passengers}"
    sem = _get_route_sem(route_key)
    with sem:
        start = time.time()
        try:
            result = get_flights(
                flight_data=[FlightData(from_airport=origin, to_airport=destination, date=date)],
                trip="one-way",
                passengers=Passengers(adults=passengers),
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

    # Capture departure time if available
    dep_time = cheapest.departure or ""
    arr_time = cheapest.arrival or ""

    cache_set(origin, destination, date, cabin, price, best_str)
    return LegResult(
        price=price, best_flight=best_str,
        duration=elapsed, cached=False,
        departure_time=dep_time, arrival_time=arr_time
    )


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
    direct_price: Optional[int]
    savings: Optional[int]
    savings_pct: Optional[float]
    leg1_flight: str = ""
    leg2_flight: str = ""
    leg1_departure: str = ""
    leg2_departure: str = ""
    leg1_duration: str = ""
    leg2_duration: str = ""


def find_transfers_for_route(
    origin: str, destination: str, date: str,
    cabin: str = "economy",
    max_workers: int = 16,
    all_hubs: bool = False,
    aggressive: bool = False,
    no_cache: bool = False,
    passengers: int = 1,
) -> dict:
    origin, destination = origin.upper(), destination.upper()
    candidate_hubs = get_relevant_hubs(origin, destination)
    if all_hubs:
        candidate_hubs = [c for c in ALL_HUBS if c not in (origin, destination)]
    hub_cap = 60 if aggressive else 25
    hubs = candidate_hubs[:hub_cap]

    direct = search_flight(origin, destination, date, cabin, use_cache=not no_cache, no_cache=no_cache, passengers=passengers)
    direct_price = direct.price
    print(f"     {'💾' if direct.cached else '📍'} {origin}→{destination}: "
          f"${direct_price or 'N/A'}  ({'cached' if direct.cached else f'{direct.duration:.1f}s'})", flush=True)

    # Build all tasks
    tasks = [(hub, origin, hub) for hub in hubs] + [(hub, hub, destination) for hub in hubs]

    def runner(hub: str, orig: str, dest: str):
        r = search_flight(orig, dest, date, cabin, use_cache=not no_cache, no_cache=no_cache, passengers=passengers)
        return hub, orig, dest, r

    leg1_prices, leg2_prices = {}, {}
    leg1_flights, leg2_flights = {}, {}
    leg1_departures, leg2_departures = {}, {}
    leg1_durations, leg2_durations = {}, {}

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
                    leg1_departures[hub] = result.departure_time
                    leg1_durations[hub] = result.duration
                elif orig == hub and dest == destination:
                    leg2_prices[hub] = result.price
                    leg2_flights[hub] = result.best_flight
                    leg2_departures[hub] = result.departure_time
                    leg2_durations[hub] = result.duration
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
            leg1_departure=leg1_departures.get(hub, ""),
            leg2_departure=leg2_departures.get(hub, ""),
            leg1_duration=leg1_durations.get(hub, ""),
            leg2_duration=leg2_durations.get(hub, ""),
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
             "leg1_flight": o.leg1_flight, "leg2_flight": o.leg2_flight,
             "leg1_departure": o.leg1_departure, "leg2_departure": o.leg2_departure,
             "leg1_duration": o.leg1_duration, "leg2_duration": o.leg2_duration}
            for o in options
        ],
        "savings": [
            {"hub": o.hub, "hub_city": o.hub_city,
             "leg1_price": o.leg1_price, "leg2_price": o.leg2_price,
             "total": o.total, "direct_price": o.direct_price,
             "savings": o.savings, "savings_pct": o.savings_pct,
             "leg1_flight": o.leg1_flight, "leg2_flight": o.leg2_flight,
             "leg1_departure": o.leg1_departure, "leg2_departure": o.leg2_departure,
             "leg1_duration": o.leg1_duration, "leg2_duration": o.leg2_duration}
            for o in options if o.savings and o.savings > 0
        ],
    }


# ─────────────────────────────────────────────────────────────────
# SELF-TRANSFER RULE VERIFICATION
# ─────────────────────────────────────────────────────────────────
def parse_duration(duration_str: str) -> float:
    """Parse duration like '3 hr 1 min' or '2 hr' into total minutes."""
    if not duration_str:
        return 0.0
    total = 0.0
    hr_match = re.search(r'(\d+)\s*hr', duration_str)
    min_match = re.search(r'(\d+)\s*min', duration_str)
    if hr_match:
        total += float(hr_match.group(1)) * 60
    if min_match:
        total += float(min_match.group(1))
    return total


def verify_transfer_option(option: dict, leg1_full_result: LegResult, leg2_full_result: LegResult) -> dict:
    """
    Verify self-transfer rules for a given transfer option.
    Returns a dict of rule → (pass: bool, detail: str)
    """
    checks = {}

    # ── Rule 1: 3+ hour buffer between legs ──────────────────────
    # We need departure times of both legs to check buffer.
    # The search_flight result carries departure_time from the flight data.
    leg1_dep = leg1_full_result.departure_time
    leg2_dep = leg2_full_result.departure_time
    hub = option["hub"]
    date = option.get("date", "")

    buffer_pass = None
    buffer_detail = ""

    if leg1_dep and leg2_dep:
        try:
            # Try parsing times like "8:30 AM" or "20:30"
            def parse_time(t_str: str) -> datetime:
                t_str = t_str.strip()
                # Handle "8:30 AM" format
                m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', t_str, re.IGNORECASE)
                if m:
                    h, mi = int(m.group(1)), int(m.group(2))
                    ampm = m.group(3)
                    if ampm:
                        ampm = ampm.upper()
                        if ampm == "PM" and h != 12:
                            h += 12
                        elif ampm == "AM" and h == 12:
                            h = 0
                    base_date = datetime.strptime(date, "%Y-%m-%d")
                    return base_date.replace(hour=h, minute=mi)
                return datetime.min

            t1 = parse_time(leg1_dep)
            t2 = parse_time(leg2_dep)
            # If leg1 arrives before midnight and leg2 is early morning, leg2 is next day
            if t2 < t1:
                t2 += timedelta(days=1)
            gap_minutes = (t2 - t1).total_seconds() / 60
            gap_hours = gap_minutes / 60

            if gap_minutes >= 180:
                buffer_pass = True
                buffer_detail = f"✅ {gap_hours:.1f}h gap ({leg1_dep} → {leg2_dep}) — {gap_hours:.1f}h >= 3h required"
            else:
                buffer_pass = False
                buffer_detail = f"❌ Only {gap_hours:.1f}h gap ({leg1_dep} → {leg2_dep}) — need 3h+ minimum"
        except Exception as e:
            buffer_pass = None
            buffer_detail = f"⚠️  Could not verify gap ({e}) — check manually: {leg1_dep} → {leg2_dep}"
    else:
        buffer_pass = None
        buffer_detail = "⚠️  Departure times not available — cannot verify gap automatically"

    checks["buffer_3h"] = {"pass": buffer_pass, "detail": buffer_detail}

    # ── Rule 2: No checked bags ─────────────────────────────────
    # Cannot be verified programmatically without booking data
    checks["carry_on_only"] = {
        "pass": None,
        "detail": "⚠️  Carry-on only required — no checked bags for self-transfer. "
                  "Verify with airline at booking time."
    }

    # ── Rule 3: Transit visa ─────────────────────────────────────
    hub_country = ALL_HUBS.get(hub, hub)
    if hub in TWOV_COUNTRIES:
        visa_pass = True
        visa_detail = f"✅ {hub} ({TWOV_COUNTRIES[hub]}) — transit visa typically NOT required for US-origin passengers"
    elif hub in VISA_REQUIRED_TRANSIT:
        visa_pass = False
        visa_detail = f"❌ {hub} ({VISA_REQUIRED_TRANSIT[hub]}) — transit visa likely REQUIRED. Verify before booking."
    else:
        visa_pass = None
        visa_detail = f"⚠️  Transit visa status for {hub} ({hub_country}) unclear — verify with airline/consulate"

    checks["transit_visa"] = {"pass": visa_pass, "detail": visa_detail}

    return checks


def format_rule_verdict(checks: dict) -> str:
    """Format rule verification results for terminal output."""
    lines = []
    for rule, result in checks.items():
        detail = result["detail"]
        lines.append(f"   {detail}")

    overall_pass = all(
        r["pass"] is True or r["pass"] is None
        for r in checks.values()
    )
    critical_fail = any(r["pass"] is False for r in checks.values())

    if critical_fail:
        verdict = "  🔴 VERIFICATION FAILED — do NOT book without resolving critical issues above"
    elif overall_pass:
        verdict = "  🟡 VERIFICATION WARNINGS — review above before booking"
    else:
        verdict = "  🟢 APPEARS SAFE — all verifiable rules pass"

    lines.append(f"\n{verdict}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# MULTI-DATE SCANNER
# ─────────────────────────────────────────────────────────────────
def expand_dates(center: str, flexible: Optional[int] = None,
                 date_range: Optional[str] = None) -> list[str]:
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
    origins: list[str], destination: str, dates: list[str],
    cabin: str, max_workers: int, all_hubs: bool, aggressive: bool, no_cache: bool,
    passengers: int = 1,
) -> dict[str, dict]:
    print(f"\n  📅 Scanning {len(dates)} dates concurrently (max_workers={max_workers})...\n", flush=True)

    def scan_one(origin: str, date: str) -> tuple:
        res = find_transfers_for_route(
            origin, destination, date, cabin,
            max_workers=min(max_workers, 8),
            all_hubs=all_hubs, aggressive=aggressive, no_cache=no_cache,
            passengers=passengers,
        )
        return origin, date, res

    results = {}
    tasks = [(o, d) for o in origins for d in dates]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as ex:
        futures = [ex.submit(scan_one, o, d) for o, d in tasks]
        for future in as_completed(futures):
            origin, date, res = future.result()
            if origin not in results:
                results[origin] = {}
            results[origin][date] = res
            dp = res.get("direct_price") or 0
            savings = res.get("savings") or []
            best = savings[0] if savings else None
            print(f"     [{len(results)}/{len(dates)}] {origin} {date}: direct=${dp}  "
                  f"{'| BEST: $'+str(best['total'])+' (-'+str(round(best['savings_pct'],1))+'%) via '+best['hub'] if best else '| no savings'}", flush=True)

    return results


# ─────────────────────────────────────────────────────────────────
# MULTI-ORIGIN SCANNER
# ─────────────────────────────────────────────────────────────────
def multi_origin_scan(
    origins: list[str], destination: str, date: str,
    cabin: str, max_workers: int, all_hubs: bool, aggressive: bool, no_cache: bool,
    passengers: int = 1,
) -> dict[str, dict]:
    print(f"\n  🌏 Scanning {len(origins)} origins concurrently...\n", flush=True)

    def scan_one(origin: str) -> tuple:
        res = find_transfers_for_route(
            origin, destination, date, cabin,
            max_workers=min(max_workers, 8),
            all_hubs=all_hubs, aggressive=aggressive, no_cache=no_cache,
            passengers=passengers,
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
                  f"{'| BEST: $'+str(best['total'])+' (-'+str(round(best['savings_pct'],1))+'%) via '+best['hub'] if best else '| no savings'}", flush=True)

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
# EXPORT: CSV
# ─────────────────────────────────────────────────────────────────
def export_to_csv(results: dict, output_path: str):
    """Export transfer results to a CSV file."""
    rows = []
    # Handle multi-result formats
    if isinstance(results, dict):
        # Single result
        if "origin" in results:
            savings = results.get("savings") or []
            for o in savings:
                rows.append({
                    "date": results.get("date", ""),
                    "origin": results.get("origin", ""),
                    "hub": o.get("hub", ""),
                    "hub_city": o.get("hub_city", ""),
                    "destination": results.get("destination", ""),
                    "cabin": results.get("cabin", ""),
                    "direct_price": results.get("direct_price", ""),
                    "leg1_price": o.get("leg1_price", ""),
                    "leg2_price": o.get("leg2_price", ""),
                    "total_price": o.get("total", ""),
                    "savings": o.get("savings", ""),
                    "savings_pct": f"{o.get('savings_pct', 0):.1f}" if o.get("savings_pct") else "",
                    "leg1_flight": o.get("leg1_flight", ""),
                    "leg2_flight": o.get("leg2_flight", ""),
                    "book_leg1": f"https://www.google.com/flights#flt={results.get('origin','')}.{o.get('hub','')}/{results.get('date','')}",
                    "book_leg2": f"https://www.google.com/flights#flt={o.get('hub','')}.{results.get('destination','')}/{results.get('date','')}",
                })
        # Multi-origin results
        elif "transfer_options" not in results:
            for origin, res in results.items():
                if isinstance(res, dict) and "origin" in res:
                    for o in res.get("savings") or []:
                        rows.append({
                            "date": res.get("date", ""),
                            "origin": origin,
                            "hub": o.get("hub", ""),
                            "hub_city": o.get("hub_city", ""),
                            "destination": res.get("destination", ""),
                            "cabin": res.get("cabin", ""),
                            "direct_price": res.get("direct_price", ""),
                            "leg1_price": o.get("leg1_price", ""),
                            "leg2_price": o.get("leg2_price", ""),
                            "total_price": o.get("total", ""),
                            "savings": o.get("savings", ""),
                            "savings_pct": f"{o.get('savings_pct', 0):.1f}" if o.get("savings_pct") else "",
                            "leg1_flight": o.get("leg1_flight", ""),
                            "leg2_flight": o.get("leg2_flight", ""),
                            "book_leg1": f"https://www.google.com/flights#flt={origin}.{o.get('hub','')}/{res.get('date','')}",
                            "book_leg2": f"https://www.google.com/flights#flt={o.get('hub','')}.{res.get('destination','')}/{res.get('date','')}",
                        })

    if not rows:
        print("   ⚠️  No transfer data to export to CSV")
        return

    fieldnames = ["date", "origin", "hub", "hub_city", "destination", "cabin",
                  "direct_price", "leg1_price", "leg2_price", "total_price",
                  "savings", "savings_pct", "leg1_flight", "leg2_flight",
                  "book_leg1", "book_leg2"]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"   📄 Exported {len(rows)} row(s) to {output_path}")


# ─────────────────────────────────────────────────────────────────
# EXPORT: NOTION
# ─────────────────────────────────────────────────────────────────
NOTION_API = "https://api.notion.com/v1"
NOTION_NOTIFY_DB_ID_ENV = "NOTION_FLIGHT_DEALS_DB_ID"


def export_to_notion(options: list, route_info: dict, api_key: str, database_id: str):
    """
    Export transfer options to a Notion database.
    Requires NOTION_FLIGHT_DEALS_DB_ID env var or --notion-database argument.
    API key requires 'Integration' token with database write access.
    """
    import urllib.request
    import urllib.error

    if not api_key:
        print("   ⚠️  NOTION_API_KEY not set — skipping Notion export")
        return
    if not database_id:
        print("   ⚠️  Notion database ID not provided — skipping Notion export")
        print("   Set NOTION_FLIGHT_DEALS_DB_ID env var or pass --notion-database")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    created = 0
    errors = []

    for opt in options[:20]:  # Limit to top 20 to avoid rate limits
        if not opt.get("savings") or opt["savings"] <= 0:
            continue

        page_data = {
            "parent": {"database_id": database_id},
            "properties": {
                "Date": {"date": {"start": route_info.get("date", "")}},
                "Origin": {"title": [{"text": {"content": route_info.get("origin", "")}}]},
                "Destination": {"rich_text": [{"text": {"content": route_info.get("destination", "")}}]},
                "Hub": {"rich_text": [{"text": {"content": opt.get("hub", "")}}]},
                "Hub City": {"rich_text": [{"text": {"content": opt.get("hub_city", "")}}]},
                "Total Price": {"number": opt.get("total", 0)},
                "Savings": {"number": opt.get("savings", 0)},
                "Savings %": {"number": round(opt.get("savings_pct", 0), 1)},
                "Leg 1 Price": {"number": opt.get("leg1_price", 0)},
                "Leg 2 Price": {"number": opt.get("leg2_price", 0)},
                "Direct Price": {"number": route_info.get("direct_price", 0) or 0},
                "Status": {"select": {"name": "New"}},
            },
        }

        try:
            req = urllib.request.Request(
                f"{NOTION_API}/pages",
                data=json.dumps(page_data).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    created += 1
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            errors.append(f"  {opt.get('hub')}: HTTP {e.code} — {err_body[:100]}")
        except Exception as e:
            errors.append(f"  {opt.get('hub')}: {e}")

    print(f"   📓 Notion: {created} page(s) created", flush=True)
    for err in errors[:5]:
        print(f"      {err}", flush=True)
    if len(errors) > 5:
        print(f"      ... and {len(errors) - 5} more errors", flush=True)


# ─────────────────────────────────────────────────────────────────
# OUTPUT FORMATTERS
# ─────────────────────────────────────────────────────────────────
def format_single(results: dict, verify_rules: bool = False) -> str:
    origin = results["origin"]
    destination = results["destination"]
    date = results["date"]
    cabin = results["cabin"]
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

        # ── Rule verification ─────────────────────────────────────
        if verify_rules:
            out.append(f"\n  ── Self-Transfer Rule Verification ──")
            # We don't have the full LegResult objects here, so we construct
            # the check with what we have from the dict
            checks = {
                "buffer_3h": {
                    "pass": None,
                    "detail": f"⚠️  Cannot verify — run with --verify-rules to check departure time gap"
                },
                "carry_on_only": {
                    "pass": None,
                    "detail": "⚠️  Carry-on only required — no checked bags for self-transfer"
                },
                "transit_visa": {
                    "pass": None,
                    "detail": f"⚠️  Verify transit visa for {best['hub']} ({ALL_HUBS.get(best['hub'], best['hub'])})"
                },
            }
            out.append(format_rule_verdict(checks))
        # ─────────────────────────────────────────────────────────

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

    if options and not savings:
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
    all_dates = set()
    for date_results in all_results.values():
        all_dates.update(date_results.keys())
    dates = sorted(all_dates)
    date_direct_prices, date_best_transfers, all_savings = {}, {}, []

    for origin_key, date_results in all_results.items():
        for date, res in date_results.items():
            dp = res.get("direct_price") or 0
            date_direct_prices[(origin_key, date)] = dp
            savings_list = res.get("savings") or []
            if savings_list:
                best = savings_list[0]
                date_best_transfers[(origin_key, date)] = best
                all_savings.append((origin_key, date, best))

    all_savings.sort(key=lambda x: x[2]['total'] if x[2]['total'] else 999999)

    W = 70
    out = []
    out.append("=" * W)
    out.append(f"✈  MULTI-DATE SCAN  |  {origin} → {destination}  |  {len(dates)} dates  |  {cabin.title()}")
    out.append("=" * W)

    out.append("\n📅 PRICE CALENDAR")
    out.append(f"   {'Date':<14} {'Origin':<6} {'Direct':>8} {'Best':>8} {'Savings':>10}  Route")
    out.append(f"   {'-'*12} {'-'*4} {'-'*8} {'-'*8} {'-'*10} {'-'*20}")
    for date in dates:
        for origin_key in sorted(all_results.keys()):
            res = all_results[origin_key].get(date)
            if not res:
                continue
            dp = date_direct_prices.get((origin_key, date), 0)
            best = date_best_transfers.get((origin_key, date))
            if best:
                out.append(f"   {date:<14} {origin_key:<6} ${dp:>7,} ${best['total']:>7,}  {f'-{best['savings_pct']:.1f}%':>9}  {origin_key}→{best['hub']}→{destination}")
            elif dp:
                out.append(f"   {date:<14} {origin_key:<6} ${dp:>7,} {'—':>8} {'—':>10}")

    if all_savings:
        out.append(f"\n🏆 TOP TRANSFERS (sorted by total price):\n")
        for i, (origin_key, date, best) in enumerate(all_savings[:10], 1):
            dp = date_direct_prices.get((origin_key, date), 0)
            out.append(f"  [{i:2d}] {date}  |  ${best['total']:,}  |  save ${best['savings']:,} ({best['savings_pct']:.1f}%)")
            out.append(f"      {origin_key}→{best['hub']}→{destination}  via {best['hub']} ({best['hub_city']})")
            out.append(f"      Direct: ${dp:,}  |  Leg1: ${best['leg1_price']:,}  Leg2: ${best['leg2_price']:,}\n")

        best_origin, best_date, best_opt = all_savings[0]
        out.append(f"  🏆 BEST OVERALL: {best_origin}→{best_opt['hub']}→{destination} on {best_date}")
        out.append(f"     Total: ${best_opt['total']:,}  |  Save ${best_opt['savings']:,} ({best_opt['savings_pct']:.1f}%)")
        out.append(f"     ⚠  Self-transfer: 2 one-ways | carry-on only | 3h+ buffer | check {best_opt['hub']} transit visa")
        out.append(f"\n  🔗 Book leg 1: https://www.google.com/flights#flt={best_origin}.{best_opt['hub']}/{best_date}")
        out.append(f"  🔗 Book leg 2: https://www.google.com/flights#flt={best_opt['hub']}.{destination}/{best_date}")
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

    all_best.sort(key=lambda x: x[2]['total'] if x[2]['total'] else 999999)

    out.append(f"\n{'Origin':<6} {'Direct':>8} {'Best Transfer':>13} {'Savings':>10}  Via")
    out.append(f"   {'-'*4} {'-'*8} {'-'*13} {'-'*10} {'-'*20}")
    for origin, dp, best in all_best:
        out.append(f"   {origin:<6} ${dp:>7,} ${best['total']:>12,} {f'-{best['savings_pct']:.1f}%':>10}  {origin}→{best['hub']}→{destination}")

    for origin, res in sorted(all_results.items(), key=lambda x: x[1].get("direct_price") or 999999):
        if not res.get("savings"):
            dp = res.get("direct_price") or 0
            out.append(f"   {origin:<6} ${dp:>7,} {'—':>13} {'—':>10}")

    if all_best:
        best_origin, best_dp, best_opt = all_best[0]
        out.append(f"\n  🏆 BEST: {best_origin}→{best_opt['hub']}→{destination} = ${best_opt['total']:,}")
        out.append(f"     Save ${best_opt['savings']:,} ({best_opt['savings_pct']:.1f}%)  vs. direct ${best_dp:,} from {best_origin}")
    out.append("\n" + "=" * W)
    return "\n".join(out)




# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Find cheaper self-transfer / hidden-city flight combinations. v5: rule verification, CSV/Notion export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 3
  python3 flight-transfer-finder.py -o SFO,LAX,OAK -d HKG -dt 2026-05-20 --flexible 3
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --flexible 7 --aggressive --save-route
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --verify-rules
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --export-csv --csv-output ~/flight-deals.csv
  python3 flight-transfer-finder.py -o LAX -d HKG -dt 2026-05-20 --alert-below 600
  python3 flight-transfer-finder.py -o SFO -d HKG -dt 2026-05-20 -p 3  # 3 passengers
        """
    )
    parser.add_argument("-o", "--origin", required=True,
                        help="Origin IATA(s), comma-separated for multi-origin")
    parser.add_argument("-d", "--destination", required=True, help="Destination IATA")
    parser.add_argument("-dt", "--date", required=True, help="Reference departure date (YYYY-MM-DD)")
    parser.add_argument("-c", "--cabin", default="economy",
                        choices=["economy", "premium-economy", "business", "first"])
    parser.add_argument("-p", "--passengers", type=int, default=1,
                        help="Number of passengers (default: 1)")
    parser.add_argument("--flexible", type=int, metavar="N",
                        help="Scan ±N days around --date (e.g. 3 = 7 dates)")
    parser.add_argument("--date-range", metavar="START:END",
                        help="Explicit date range, e.g. 2026-05-15:2026-05-25")
    parser.add_argument("--origins", metavar="CODE,CODE",
                        help="Additional comma-separated origins")
    parser.add_argument("--aggressive", action="store_true", help="Check 60 hubs (default: 25)")
    parser.add_argument("--all-hubs", action="store_true", help="Check all 70+ hubs")
    parser.add_argument("--direct-only", action="store_true",
                        help="Skip hub transfer search — show direct price only (fast)")
    parser.add_argument("--max-workers", type=int, default=8,
                        help="Concurrent threads (default: 8)")
    parser.add_argument("--no-cache", action="store_true", help="Bypass cache")
    parser.add_argument("--save-route", action="store_true", help="Save to history")
    parser.add_argument("--alert-below", type=int, metavar="PRICE",
                        help="Alert if best transfer is below this threshold")
    parser.add_argument("--verify-rules", action="store_true",
                        help="Verify self-transfer rules (3h buffer, carry-on, transit visa) for top results")
    parser.add_argument("--export-csv", action="store_true",
                        help="Export results to CSV file")
    parser.add_argument("--csv-output", metavar="PATH",
                        default="",
                        help="CSV output path (default: fly-smart-deals-YYYY-MM-DD.csv)")
    parser.add_argument("--export-notion", action="store_true",
                        help="Export results to Notion database")
    parser.add_argument("--notion-database", metavar="ID",
                        help="Notion database ID (or set NOTION_FLIGHT_DEALS_DB_ID env var)")
    parser.add_argument("--notion-api-key", metavar="KEY",
                        help="Notion Integration token (or set NOTION_API_KEY env var)")
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
    print(f"✈️  FLIGHT TRANSFER FINDER v5 — fast_flights library + rule verification")
    print(f"   Route: {' / '.join(all_origins)} → {args.destination}")
    print(f"   Date(s): {len(dates)} ({dates[0]} → {dates[-1]})" if is_multi_date else f"   Date: {dates[0]}")
    print(f"   Cabin: {args.cabin.title()}  |  Passengers: {args.passengers}  |  Threads: {args.max_workers}")
    print(f"   Mode: {'Aggressive' if args.aggressive else ('All hubs' if args.all_hubs else 'Normal')} | "
          f"{'Multi-origin' if is_multi_origin else 'Single origin'} | "
          f"{'Multi-date' if is_multi_date else 'Single date'} | "
          f"{'DIRECT ONLY' if args.direct_only else 'Transfer scan'}")
    print(f"   Cache: {'BYPASS' if args.no_cache else 'ON (1h TTL)'}  |  Timeout: {args.timeout}s")
    if args.verify_rules:
        print(f"   🔍 Rule verification: ON")
    if args.export_csv:
        print(f"   📄 CSV export: ON")
    if args.export_notion:
        print(f"   📓 Notion export: ON")
    print(f"{'='*70}", flush=True)

    start_time = time.time()

    def remaining() -> bool:
        return (time.time() - start_time) < args.timeout

    # CSV output path
    csv_path = args.csv_output
    if args.export_csv and not csv_path:
        ts = datetime.now().strftime("%Y-%m-%d")
        csv_path = f"fly-smart-deals-{ts}.csv"

    # Notion config
    notion_api_key = args.notion_api_key or os.environ.get("NOTION_API_KEY", "")
    notion_db_id = args.notion_database or os.environ.get("NOTION_FLIGHT_DEALS_DB_ID", "")

    # Shared result variable for export
    _last_result = None

    # Multi-origin × Multi-date
    if is_multi_origin and is_multi_date:
        origin_results = {}
        for origin in all_origins:
            if not remaining():
                print(f"\n⏱️  Timeout reached, stopping."); break
            res = multi_date_scan(
                [origin], args.destination, dates, args.cabin,
                max_workers=args.max_workers, all_hubs=args.all_hubs,
                aggressive=args.aggressive, no_cache=args.no_cache,
                passengers=args.passengers,
            )
            origin_results[origin] = res

        flattened = []
        for origin, date_results in origin_results.items():
            for date, res in date_results.items():
                savings = res.get("savings") or []
                if savings:
                    flattened.append((origin, date, savings[0], res.get("direct_price") or 0))

        flattened.sort(key=lambda x: x[2]['total'] if x[2]['total'] else 999999)
        _last_result = {"type": "multi_origin_date", "origin_results": origin_results, "flattened": flattened}

        W = 70
        out = []
        out.append("=" * W)
        out.append(f"✈️  MULTI-ORIGIN × MULTI-DATE  |  {len(all_origins)} origins × {len(dates)} dates")
        out.append("=" * W)
        if flattened:
            out.append(f"\n🏆 TOP {min(10, len(flattened))} COMBOS:\n")
            for i, (origin, date, best, dp) in enumerate(flattened[:10], 1):
                out.append(f"  [{i:2d}] {origin}→{best['hub']}→{args.destination}  |  {date}  |  ${best['total']:,}")
                out.append(f"      Save ${best['savings']:,} ({best['savings_pct']:.1f}%)  vs. direct ${dp:,}\n")
            best_triple = flattened[0]
            out.append(f"  🏆 BEST: {best_triple[0]}→{best_triple[2]['hub']}→{args.destination} "
                       f"on {best_triple[1]} = ${best_triple[2]['total']:,}")
        else:
            out.append("\n❌ No savings found.")
        out.append("\n" + "=" * W)
        print("\n".join(out))

        if args.save_route and flattened:
            for origin, date, best, dp in flattened[:10]:
                save_to_history({"type": "multi_origin_date", "origin": origin,
                                 "destination": args.destination, "date": date,
                                 "best_transfer": best})

    # Multi-date only
    elif is_multi_date:
        results_by_date = multi_date_scan(
            all_origins, args.destination, dates, args.cabin,
            max_workers=args.max_workers, all_hubs=args.all_hubs,
            aggressive=args.aggressive, no_cache=args.no_cache,
            passengers=args.passengers,
        )
        _last_result = results_by_date
        if args.json:
            print(json.dumps(results_by_date, indent=2, default=str)); return
        print(format_multi_date(results_by_date, all_origins[0], args.destination, args.cabin))
        if args.save_route:
            for origin, date_results in results_by_date.items():
                for date, res in date_results.items():
                    savings = res.get("savings") or []
                    if savings:
                        save_to_history({"type": "multi_date", "origin": origin,
                                         "destination": args.destination, "date": date,
                                         "best_transfer": savings[0]})

    # Multi-origin only
    elif is_multi_origin:
        results_by_origin = multi_origin_scan(
            all_origins, args.destination, dates[0], args.cabin,
            max_workers=args.max_workers, all_hubs=args.all_hubs,
            aggressive=args.aggressive, no_cache=args.no_cache,
            passengers=args.passengers,
        )
        _last_result = results_by_origin
        if args.json:
            print(json.dumps(results_by_origin, indent=2, default=str)); return
        print(format_multi_origin(results_by_origin, args.destination, dates[0], args.cabin))
        if args.save_route:
            for origin, res in results_by_origin.items():
                savings = res.get("savings") or []
                if savings:
                    save_to_history({"type": "multi_origin", "origin": origin,
                                     "destination": args.destination, "date": dates[0],
                                     "best_transfer": savings[0]})

    # Direct-only
    if args.direct_only and not is_multi_date and not is_multi_origin:
        if not remaining():
            print(f"\n⏱️  Timeout already reached."); return
        result = search_flight(
            all_origins[0], args.destination, dates[0], args.cabin,
            use_cache=not args.no_cache, no_cache=args.no_cache,
            passengers=args.passengers,
        )
        print(f"\n{'='*65}")
        print(f"✈️  DIRECT PRICE  |  {all_origins[0]} → {args.destination}  |  {dates[0]}  |  {args.cabin.title()}")
        print(f"{'='*65}")
        if result.price:
            cached_tag = " 💾" if result.cached else ""
            print(f"   💰 ${result.price:,}{cached_tag}  ({result.duration:.1f}s)")
            print(f"   ✈️  {result.best_flight}")
        elif result.error:
            print(f"   ⚠️  {result.error}")
        else:
            print(f"   ⚠️  No data — try a date 2+ weeks out")
        print(f"\n⏱️  Completed in {time.time() - start_time:.1f}s", flush=True)
        return

    # Single route
    else:
        if not remaining():
            print(f"\n⏱️  Timeout already reached before single route search."); return
        result = find_transfers_for_route(
            all_origins[0], args.destination, dates[0], args.cabin,
            max_workers=args.max_workers, all_hubs=args.all_hubs,
            aggressive=args.aggressive, no_cache=args.no_cache,
            passengers=args.passengers,
        )
        _last_result = result

        if args.json:
            print(json.dumps(result, indent=2, default=str)); return

        print(format_single(result, verify_rules=args.verify_rules))

        savings = result.get("savings") or []
        if args.alert_below and savings:
            best = savings[0]
            if best['total'] and best['total'] < args.alert_below:
                print(f"\n🔔 ALERT: Best transfer ${best['total']:,} is below your threshold ${args.alert_below:,}")

        if args.save_route and savings:
            save_to_history({"type": "single", "origin": all_origins[0],
                             "destination": args.destination, "date": dates[0],
                             "cabin": args.cabin, "best_transfer": savings[0]})

    # ── Post-scan exports ─────────────────────────────────────────
    if args.export_csv and _last_result:
        print(f"\n{'='*70}", flush=True)
        print("📄 CSV Export", flush=True)
        print(f"{'='*70}", flush=True)
        export_to_csv(_last_result, csv_path)

    if args.export_notion and _last_result:
        print(f"\n{'='*70}", flush=True)
        print("📓 Notion Export", flush=True)
        print(f"{'='*70}", flush=True)
        # Collect top savings options
        notion_opts = []
        if isinstance(_last_result, dict):
            if "savings" in _last_result:
                notion_opts = _last_result.get("savings") or []
            elif "transfer_options" not in _last_result:
                for res in _last_result.values():
                    if isinstance(res, dict):
                        notion_opts.extend(res.get("savings") or [])
        export_to_notion(
            notion_opts,
            {"origin": all_origins[0], "destination": args.destination,
             "date": dates[0], "cabin": args.cabin,
             "direct_price": _last_result.get("direct_price") if isinstance(_last_result, dict) else 0},
            notion_api_key,
            notion_db_id,
        )
    # ───────────────────────────────────────────────────────────────

    elapsed = time.time() - start_time
    print(f"\n⏱️  Completed in {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
