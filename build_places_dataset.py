"""
build_places_dataset.py
-----------------------
Run this ONCE on your own computer (it needs internet):

    python build_places_dataset.py

It downloads every NAMED place inside the Iloilo City bounding box from
OpenStreetMap (via the Overpass API) and saves them to  iloilo_places.json
next to this file. app.py then searches that file instantly, offline.

It sends several small queries (one per category) with pauses in between so
the free Overpass servers don't rate-limit you. It takes a few minutes.

Optional: create a  manual_places.csv  next to this file to add your own
places (jeepney terminals, local nicknames, places missing from OSM).
Columns:  name,lat,lon,category,aliases
Example:  Iloilo Terminal Market,10.6965,122.5712,market,Super|Terminal Market
(aliases are separated with a | character)
"""
import csv
import json
import time
from pathlib import Path

import requests

# South, West, North, East. Widen/narrow if places are missing or spilling over.
BBOX = (10.65, 122.49, 10.77, 122.62)

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Overpass rejects the default python-requests identity (HTTP 406), so we
# identify ourselves properly.
HEADERS = {
    "User-Agent": "IloiloPathOptimizerCaseStudy/1.0 (student project; local dataset build)",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# Which OSM keys count as a "place" and the order we use to pick a category.
CATEGORY_KEYS = [
    "amenity", "shop", "tourism", "leisure", "office",
    "healthcare", "historic", "public_transport", "place",
]

PAUSE_BETWEEN_QUERIES = 6   # seconds
MAX_ROUNDS_PER_QUERY = 4    # full passes over all mirrors before giving up on a query

HERE = Path(__file__).parent
OUT_FILE = HERE / "iloilo_places.json"
MANUAL_FILE = HERE / "manual_places.csv"


def build_queries():
    """One small query per category instead of one huge query."""
    b = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    selectors = [(k, f'nwr["name"]["{k}"]({b});') for k in CATEGORY_KEYS]
    selectors.append(("bus_stop", f'nwr["name"]["highway"="bus_stop"]({b});'))
    selectors.append(("station", f'nwr["name"]["railway"~"station|halt"]({b});'))
    return [
        (label, f"[out:json][timeout:60];\n(\n  {sel}\n);\nout center tags;")
        for label, sel in selectors
    ]


def run_query(label, query):
    """Try each mirror, retrying with waits on 429/504. Returns a list of elements or None."""
    for round_no in range(1, MAX_ROUNDS_PER_QUERY + 1):
        for url in OVERPASS_MIRRORS:
            try:
                r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=90)
                if r.status_code == 200:
                    return r.json().get("elements", [])
                print(f"    {url.split('/')[2]}: HTTP {r.status_code}")
            except Exception as e:
                print(f"    {url.split('/')[2]}: {type(e).__name__}")
            time.sleep(3)
        wait = 15 * round_no
        print(f"  [{label}] all mirrors busy, waiting {wait}s (round {round_no}/{MAX_ROUNDS_PER_QUERY})...")
        time.sleep(wait)
    return None


def fetch_overpass():
    merged = {}
    failed = []
    queries = build_queries()
    for i, (label, query) in enumerate(queries, 1):
        print(f"[{i}/{len(queries)}] Downloading '{label}' ...")
        elements = run_query(label, query)
        if elements is None:
            print(f"  -> gave up on '{label}'")
            failed.append(label)
        else:
            for el in elements:
                merged[(el.get("type"), el.get("id"))] = el
            print(f"  -> {len(elements)} elements (total unique so far: {len(merged)})")
        time.sleep(PAUSE_BETWEEN_QUERIES)

    if not merged:
        raise SystemExit(
            "No data could be downloaded. Wait 5-10 minutes and run again "
            "(the free servers are rate-limiting), or try a different network."
        )
    if failed:
        print(f"\nWARNING: these categories failed and are missing: {', '.join(failed)}")
        print("Run the script again later to try to fill them in.\n")
    return list(merged.values())


def pick_category(tags):
    for key in CATEGORY_KEYS:
        if key in tags:
            return tags[key] if key in ("amenity", "shop", "tourism", "leisure", "place") else key
    if tags.get("highway") == "bus_stop":
        return "bus_stop"
    if "railway" in tags:
        return "station"
    return "place"


def pick_label(tags):
    """Short helper text shown under the name, e.g. 'Rizal St, Jaro'."""
    street = tags.get("addr:street", "")
    area = tags.get("addr:suburb") or tags.get("addr:barangay") or tags.get("addr:city", "")
    return ", ".join(p for p in (street, area) if p)


def convert(elements):
    places, seen = [], set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not name or lat is None or lon is None:
            continue

        # de-duplicate: same name within ~100 m
        key = (name.lower(), round(lat, 3), round(lon, 3))
        if key in seen:
            continue
        seen.add(key)

        aliases = [tags[k] for k in ("name:en", "alt_name", "short_name", "old_name", "name:hil", "name:tl")
                   if tags.get(k)]
        places.append({
            "name": name,
            "label": pick_label(tags),
            "category": pick_category(tags),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "aliases": aliases,
        })
    return places


def load_manual():
    if not MANUAL_FILE.exists():
        return []
    rows = []
    with open(MANUAL_FILE, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "name": row["name"].strip(),
                    "label": "",
                    "category": (row.get("category") or "custom").strip(),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "aliases": [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()],
                })
            except (KeyError, ValueError):
                print(f"Skipping bad manual row: {row}")
    print(f"Loaded {len(rows)} manual places from {MANUAL_FILE.name}")
    return rows


if __name__ == "__main__":
    elements = fetch_overpass()
    print(f"Downloaded {len(elements)} raw OSM elements")
    places = convert(elements) + load_manual()
    places.sort(key=lambda p: p["name"].lower())
    OUT_FILE.write_text(json.dumps(places, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Saved {len(places)} places to {OUT_FILE}")