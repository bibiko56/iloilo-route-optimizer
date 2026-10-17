"""
build_graph.py
--------------
Run this ONCE on your own computer (needs internet):

    pip install osmnx
    python build_graph.py              # builds drive, bike and walk graphs
    python build_graph.py drive        # or just the ones you name

It downloads the real Iloilo City road network from OpenStreetMap and saves
iloilo_graph_drive.json / iloilo_graph_bike.json / iloilo_graph_walk.json next to this file.
Intersections become NODES and road segments become weighted EDGES
(length in metres and travel time in seconds). algorithms.py then searches these graphs.

If a download fails because the server is busy, wait a few minutes and run it again.
"""
import json
import sys
import time
from pathlib import Path

import networkx as nx
import osmnx as ox

CENTER = (10.7020, 122.5621)  # lat, lon
RADIUS_M = {"drive": 6000, "bike": 5000, "walk": 5000}  # the whole city is within ~4 km of CENTER

# Default speeds (km/h) by road type for driving; bike and walk use fixed speeds.
DRIVE_SPEEDS_KPH = {
    "motorway": 60, "trunk": 50, "primary": 40, "secondary": 35, "tertiary": 30,
    "unclassified": 25, "residential": 25, "living_street": 15, "service": 15,
}
FIXED_SPEEDS_KPH = {"bike": 15.0, "walk": 4.5}
HERE = Path(__file__).parent


# The default OSMnx server is often overloaded, so we rotate between several.
MIRRORS = [
    "https://overpass-api.de/api",
    "https://overpass.private.coffee/api",
    "https://overpass.kumi.systems/api",
]
RETRY_ROUNDS = 3
RETRY_WAIT_S = 20

ox.settings.use_cache = True        # successful downloads are cached, so re-runs resume quickly
ox.settings.requests_timeout = 120  # give up on a dead server after 2 min instead of 3


def use_mirror(url):
    ox.settings.overpass_url = url       # osmnx 2.x
    ox.settings.overpass_endpoint = url  # osmnx 1.x


def download(kind):
    for rnd in range(1, RETRY_ROUNDS + 1):
        for url in MIRRORS:
            use_mirror(url)
            host = url.split("/")[2]
            try:
                print(f"[{kind}] trying {host} (round {rnd}/{RETRY_ROUNDS}) ...")
                return ox.graph_from_point(CENTER, dist=RADIUS_M[kind], network_type=kind, simplify=True)
            except Exception as e:  # timeout, 429, 504, ... -> try the next server
                print(f"    failed on {host}: {type(e).__name__}")
        wait = RETRY_WAIT_S * rnd
        print(f"[{kind}] all servers failed, waiting {wait}s before trying again...")
        time.sleep(wait)
    raise SystemExit(
        f"Could not download the '{kind}' graph. The free servers may be busy or blocked on this network. "
        "Wait 10 minutes and run again, or try another network (for example a phone hotspot). "
        "Anything already downloaded is cached, so re-running will not start from zero."
    )


def first(value):
    return value[0] if isinstance(value, list) else value


def speed_kph(kind, data):
    if kind in FIXED_SPEEDS_KPH:
        return FIXED_SPEEDS_KPH[kind]
    base = DRIVE_SPEEDS_KPH.get(str(first(data.get("highway", ""))).replace("_link", ""), 25)
    raw = first(data.get("maxspeed"))
    if raw:
        try:
            digits = "".join(ch for ch in str(raw) if ch.isdigit() or ch == ".")
            value = float(digits)
            return value * 1.609 if "mph" in str(raw) else value
        except ValueError:
            pass
    return base


def build(kind):
    print(f"[{kind}] downloading road network (radius {RADIUS_M[kind]} m)...")
    G = download(kind)

    # keep the largest strongly connected part so every node can reach every other
    biggest = max(nx.strongly_connected_components(G), key=len)
    G = G.subgraph(biggest).copy()

    nodes = {str(n): [round(d["y"], 6), round(d["x"], 6)] for n, d in G.nodes(data=True)}

    best = {}
    for u, v, data in G.edges(data=True):
        length = float(data.get("length", 0.0))
        if length <= 0:
            continue
        secs = length / (speed_kph(kind, data) / 3.6)
        key = (u, v)
        if key not in best or length < best[key][0]:
            best[key] = (length, secs)
    edges = [[u, v, round(l, 1), round(t, 1)] for (u, v), (l, t) in best.items()]

    out = HERE / f"iloilo_graph_{kind}.json"
    out.write_text(json.dumps({"nodes": nodes, "edges": edges}, separators=(",", ":")), encoding="utf-8")
    print(f"[{kind}] saved {len(nodes):,} nodes and {len(edges):,} edges to {out.name}")


if __name__ == "__main__":
    kinds = sys.argv[1:] or ["drive", "bike", "walk"]
    for k in kinds:
        if k not in RADIUS_M:
            raise SystemExit(f"Unknown graph type '{k}'. Use: drive, bike, walk")
        build(k)