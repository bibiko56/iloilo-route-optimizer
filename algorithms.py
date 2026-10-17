"""
algorithms.py
-------------
Our own implementations of four search algorithms on a road graph:

    bfs       Breadth-First Search       (fewest road segments, ignores distance)
    greedy    Greedy Best-First Search   (always heads toward the goal; fast but NOT optimal)
    dijkstra  Dijkstra's algorithm       (optimal, but explores in every direction)
    astar     A* with haversine heuristic (optimal, explores far fewer nodes)

Every algorithm counts the nodes it expands, so the algorithms can be compared fairly.
Only the Python standard library is needed here.
"""
import heapq
import json
import math
import time
from collections import deque
from dataclasses import dataclass, field

EARTH_R = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


class RoadGraph:
    """
    nodes: {node_id: (lat, lon)}
    adj:   {node_id: [(neighbor_id, length_m, time_s), ...]}   (directed edges)
    """

    CELL_DEG = 0.005  # grid cell for fast nearest-node lookup

    def __init__(self, nodes, adj):
        self.nodes = nodes
        self.adj = adj
        # fastest speed (m/s) in the graph, used to keep the time heuristic admissible
        self.vmax = max(
            (length / secs for edges in adj.values() for _, length, secs in edges if secs > 0),
            default=1.0,
        )
        self._grid = {}
        for nid, (la, lo) in nodes.items():
            self._grid.setdefault((int(la // self.CELL_DEG), int(lo // self.CELL_DEG)), []).append(nid)

    def nearest_node(self, lat, lon):
        """Snap a lat/lon to the closest road node. Returns (node_id, distance_m)."""
        ci, cj = int(lat // self.CELL_DEG), int(lon // self.CELL_DEG)
        best, best_d = None, float("inf")
        for r in range(0, 80):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    for nid in self._grid.get((ci + di, cj + dj), ()):
                        la, lo = self.nodes[nid]
                        d = haversine_m(lat, lon, la, lo)
                        if d < best_d:
                            best, best_d = nid, d
            # a node in a farther ring is at least r * (smallest cell size in metres) away
            if best is not None and best_d <= r * 540:
                break
        if best is None:
            raise ValueError("Graph has no nodes near this point.")
        return best, best_d


def load_graph(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    nodes = {int(k): (v[0], v[1]) for k, v in data["nodes"].items()}
    adj = {nid: [] for nid in nodes}
    for u, v, length, secs in data["edges"]:
        adj[int(u)].append((int(v), float(length), float(secs)))
    return RoadGraph(nodes, adj)


@dataclass
class SearchResult:
    name: str
    found: bool
    path: list = field(default_factory=list)
    distance_m: float = 0.0
    time_s: float = 0.0
    expanded: int = 0
    runtime_ms: float = 0.0

    def as_dict(self):
        return {
            "name": self.name, "found": self.found, "path": self.path,
            "distance_m": self.distance_m, "time_s": self.time_s,
            "expanded": self.expanded, "runtime_ms": self.runtime_ms,
        }


def _finish(name, parent, s, t, expanded, t0):
    """Rebuild the path from the parent links and total up distance and time."""
    runtime = (time.perf_counter() - t0) * 1000.0
    if s != t and t not in parent:
        return SearchResult(name, False, expanded=expanded, runtime_ms=runtime)
    path, dist, secs, cur = [t], 0.0, 0.0, t
    while cur != s:
        u, length, tt = parent[cur]
        dist += length
        secs += tt
        path.append(u)
        cur = u
    path.reverse()
    return SearchResult(name, True, path, dist, secs, expanded, runtime)


def _cost_index(weight):
    # edge tuple = (neighbor, length_m, time_s)
    return 1 if weight == "distance" else 2


def _heuristic(g, goal, weight):
    glat, glon = g.nodes[goal]
    scale = 1.0 if weight == "distance" else 1.0 / g.vmax

    def h(n):
        la, lo = g.nodes[n]
        return haversine_m(la, lo, glat, glon) * scale

    return h


def bfs(g, s, t, weight="distance"):
    t0 = time.perf_counter()
    parent, seen, queue, expanded = {}, {s}, deque([s]), 0
    while queue:
        u = queue.popleft()
        expanded += 1
        if u == t:
            break
        for v, length, secs in g.adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                parent[v] = (u, length, secs)
                queue.append(v)
    return _finish("BFS", parent, s, t, expanded, t0)


def greedy(g, s, t, weight="distance"):
    t0 = time.perf_counter()
    h = _heuristic(g, t, weight)
    parent, seen, expanded = {}, {s}, 0
    heap = [(h(s), s)]
    while heap:
        _, u = heapq.heappop(heap)
        expanded += 1
        if u == t:
            break
        for v, length, secs in g.adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                parent[v] = (u, length, secs)
                heapq.heappush(heap, (h(v), v))
    return _finish("Greedy best-first", parent, s, t, expanded, t0)


def dijkstra(g, s, t, weight="distance"):
    t0 = time.perf_counter()
    ci = _cost_index(weight)
    best, parent, closed, expanded = {s: 0.0}, {}, set(), 0
    heap = [(0.0, s)]
    while heap:
        d, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        expanded += 1
        if u == t:
            break
        for e in g.adj.get(u, ()):
            v = e[0]
            nd = d + e[ci]
            if nd < best.get(v, float("inf")):
                best[v] = nd
                parent[v] = (u, e[1], e[2])
                heapq.heappush(heap, (nd, v))
    return _finish("Dijkstra", parent, s, t, expanded, t0)


def astar(g, s, t, weight="distance"):
    t0 = time.perf_counter()
    ci = _cost_index(weight)
    h = _heuristic(g, t, weight)
    best, parent, closed, expanded = {s: 0.0}, {}, set(), 0
    heap = [(h(s), s)]
    while heap:
        _, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        expanded += 1
        if u == t:
            break
        gu = best[u]
        for e in g.adj.get(u, ()):
            v = e[0]
            ng = gu + e[ci]
            if ng < best.get(v, float("inf")):
                best[v] = ng
                parent[v] = (u, e[1], e[2])
                heapq.heappush(heap, (ng + h(v), v))
    return _finish("A*", parent, s, t, expanded, t0)


ALGORITHMS = {
    "BFS": bfs,
    "Greedy best-first": greedy,
    "Dijkstra": dijkstra,
    "A*": astar,
}


def compare_all(g, s, t, weight="distance"):
    """Run every algorithm on the same start/goal. Returns {name: SearchResult}."""
    return {name: fn(g, s, t, weight) for name, fn in ALGORITHMS.items()}