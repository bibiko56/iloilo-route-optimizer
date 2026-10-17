"""
benchmark.py
------------
Runs BFS, Greedy, Dijkstra and A* on many random start/drop-off pairs and saves
the numbers you need for the Results section of the paper.

    python benchmark.py                          # 40 pairs, shortest distance, drive graph
    python benchmark.py --pairs 50 --weight time
    python benchmark.py --kind walk
    python benchmark.py --mapbox                 # also compare with Mapbox (needs MAPBOX_TOKEN env var)

Outputs (next to this file):
    benchmark_results.csv   one row per pair per algorithm
    benchmark_summary.csv   averages per algorithm (put this table in your paper)
    benchmark_chart.png     bar chart of nodes expanded (only if matplotlib is installed)
"""
import argparse
import csv
import json
import os
import random
import statistics
import time
from pathlib import Path

from algorithms import compare_all, haversine_m, load_graph

HERE = Path(__file__).parent
MAPBOX_PROFILE = {"drive": "mapbox/driving", "bike": "mapbox/cycling", "walk": "mapbox/walking"}


def mapbox_distance_km(profile, start, goal, token):
    import requests

    url = (
        f"https://api.mapbox.com/directions/v5/{profile}/"
        f"{start[1]},{start[0]};{goal[1]},{goal[0]}?access_token={token}&geometries=geojson"
    )
    try:
        data = requests.get(url, timeout=8).json()
        if data.get("code") == "Ok":
            return data["routes"][0]["distance"] / 1000.0
    except Exception:
        pass
    return None


def sample_points(graph, how_many):
    places_file = HERE / "iloilo_places.json"
    if places_file.exists():
        with open(places_file, encoding="utf-8") as f:
            return [(p["lat"], p["lon"]) for p in json.load(f)]
    return list(graph.nodes.values())  # fallback: random road nodes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="drive", choices=["drive", "bike", "walk"])
    ap.add_argument("--pairs", type=int, default=40)
    ap.add_argument("--weight", default="distance", choices=["distance", "time"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--graph", default=None, help="path to graph json (default: iloilo_graph_<kind>.json)")
    ap.add_argument("--min_km", type=float, default=0.5, help="min straight-line distance of a pair")
    ap.add_argument("--max_km", type=float, default=10.0, help="max straight-line distance of a pair")
    ap.add_argument("--mapbox", action="store_true")
    args = ap.parse_args()

    graph_path = Path(args.graph) if args.graph else HERE / f"iloilo_graph_{args.kind}.json"
    if not graph_path.exists():
        raise SystemExit(f"{graph_path.name} not found. Run:  python build_graph.py {args.kind}")
    token = os.environ.get("MAPBOX_TOKEN", "")
    if args.mapbox and not token:
        raise SystemExit("--mapbox needs the MAPBOX_TOKEN environment variable.")

    print(f"Loading {graph_path.name} ...")
    g = load_graph(graph_path)
    print(f"Graph: {len(g.nodes):,} nodes")

    points = sample_points(g, args.pairs)
    rng = random.Random(args.seed)

    rows, tried, done = [], 0, 0
    while done < args.pairs and tried < args.pairs * 50:
        tried += 1
        a, b = rng.sample(points, 2)
        straight_km = haversine_m(a[0], a[1], b[0], b[1]) / 1000.0
        if not (args.min_km <= straight_km <= args.max_km):
            continue
        s_node, s_off = g.nearest_node(*a)
        t_node, t_off = g.nearest_node(*b)
        if s_node == t_node or max(s_off, t_off) > 500:  # skip points far from any road
            continue

        results = compare_all(g, s_node, t_node, args.weight)
        if not results["Dijkstra"].found:
            continue
        done += 1
        mb = mapbox_distance_km(MAPBOX_PROFILE[args.kind], a, b, token) if args.mapbox else None
        if args.mapbox:
            time.sleep(0.15)
        for name, r in results.items():
            rows.append({
                "pair": done, "algorithm": name, "found": r.found, "straight_km": round(straight_km, 3),
                "distance_km": round(r.distance_m / 1000.0, 3), "time_min": round(r.time_s / 60.0, 2),
                "nodes_expanded": r.expanded, "runtime_ms": round(r.runtime_ms, 2),
                "mapbox_km": round(mb, 3) if mb else "",
                "gap_vs_mapbox_pct": round((r.distance_m / 1000.0 - mb) / mb * 100, 2) if (mb and r.found) else "",
            })
        print(f"  pair {done}/{args.pairs} done", end="\r")
    print()
    if done < args.pairs:
        print(f"Warning: only {done} valid pairs found (wanted {args.pairs}).")

    with open(HERE / "benchmark_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- summary per algorithm -------------------------------------------------
    by_alg, dijk = {}, {}
    for r in rows:
        by_alg.setdefault(r["algorithm"], []).append(r)
        if r["algorithm"] == "Dijkstra":
            dijk[r["pair"]] = r
    key = "distance_km" if args.weight == "distance" else "time_min"

    summary = []
    for name, rs in by_alg.items():
        found = [r for r in rs if r["found"]]
        optimal = [r for r in found if r[key] <= dijk[r["pair"]][key] * 1.001]
        reduction = [1 - r["nodes_expanded"] / dijk[r["pair"]]["nodes_expanded"] for r in rs]
        gaps = [r["gap_vs_mapbox_pct"] for r in found if r["gap_vs_mapbox_pct"] != ""]
        summary.append({
            "algorithm": name,
            "pairs": len(rs),
            "found_pct": round(100 * len(found) / len(rs), 1),
            "optimal_pct": round(100 * len(optimal) / len(rs), 1),
            "avg_distance_km": round(statistics.mean(r["distance_km"] for r in found), 3),
            "avg_time_min": round(statistics.mean(r["time_min"] for r in found), 2),
            "avg_nodes_expanded": round(statistics.mean(r["nodes_expanded"] for r in rs)),
            "avg_runtime_ms": round(statistics.mean(r["runtime_ms"] for r in rs), 2),
            "nodes_saved_vs_dijkstra_pct": round(100 * statistics.mean(reduction), 1),
            "avg_gap_vs_mapbox_pct": round(statistics.mean(gaps), 2) if gaps else "",
        })
    with open(HERE / "benchmark_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    print(f"\nSummary ({done} pairs, optimizing for {args.weight}, {args.kind} graph)")
    cols = list(summary[0].keys())
    print(" | ".join(cols))
    for s in summary:
        print(" | ".join(str(s[c]) for c in cols))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar([s["algorithm"] for s in summary], [s["avg_nodes_expanded"] for s in summary], color="#023e8a")
        ax.set_ylabel("Average nodes expanded")
        ax.set_title("Search effort per algorithm")
        fig.tight_layout()
        fig.savefig(HERE / "benchmark_chart.png", dpi=200)
        print("\nSaved benchmark_chart.png")
    except ImportError:
        print("\n(matplotlib not installed, skipping chart. pip install matplotlib to get benchmark_chart.png)")

    print("Saved benchmark_results.csv and benchmark_summary.csv")


if __name__ == "__main__":
    main()