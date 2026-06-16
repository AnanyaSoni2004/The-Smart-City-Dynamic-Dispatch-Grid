"""City road network as a weighted graph + shortest path routing.

Node = intersection, Edge = road segment, Weight = travel time (seconds),
modulated by live congestion multipliers and hard road closures.
"""
from __future__ import annotations

import heapq
import math
import random
from typing import Optional


class CityGraph:
    def __init__(self, width: int = 12, height: int = 12, block_seconds: float = 45.0,
                 seed: int = 7):
        self.width, self.height = width, height
        self.coords: dict[int, tuple[float, float]] = {}
        self.adj: dict[int, dict[int, float]] = {}          # base travel times
        self.congestion: dict[tuple[int, int], float] = {}  # multiplier >= 1
        self.closed: set[tuple[int, int]] = set()
        rng = random.Random(seed)

        for y in range(height):
            for x in range(width):
                n = y * width + x
                self.coords[n] = (float(x), float(y))
                self.adj[n] = {}
        for y in range(height):
            for x in range(width):
                n = y * width + x
                for dx, dy in ((1, 0), (0, 1)):
                    xx, yy = x + dx, y + dy
                    if xx < width and yy < height:
                        m = yy * width + xx
                        w = block_seconds * rng.uniform(0.8, 1.6)
                        self.adj[n][m] = w
                        self.adj[m][n] = w
        # a few diagonal "arterial" shortcuts
        for _ in range(width):
            a, b = rng.choice(list(self.coords)), rng.choice(list(self.coords))
            if a != b:
                d = self._euclid(a, b) * block_seconds * 0.7
                self.adj[a][b] = d
                self.adj[b][a] = d

    # ---------------- live conditions ----------------
    def _key(self, a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def close_road(self, a: int, b: int) -> None:
        self.closed.add(self._key(a, b))

    def reopen_road(self, a: int, b: int) -> None:
        self.closed.discard(self._key(a, b))

    def set_congestion(self, a: int, b: int, mult: float) -> None:
        self.congestion[self._key(a, b)] = max(1.0, mult)

    def edge_time(self, a: int, b: int) -> Optional[float]:
        if self._key(a, b) in self.closed:
            return None
        base = self.adj[a].get(b)
        if base is None:
            return None
        return base * self.congestion.get(self._key(a, b), 1.0)

    def _euclid(self, a: int, b: int) -> float:
        (x1, y1), (x2, y2) = self.coords[a], self.coords[b]
        return math.hypot(x1 - x2, y1 - y2)

    # ---------------- shortest paths ----------------
    def dijkstra(self, src: int, dst: int) -> tuple[Optional[list[int]], float]:
        dist = {src: 0.0}
        prev: dict[int, int] = {}
        pq = [(0.0, src)]
        seen: set[int] = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in seen:
                continue
            if u == dst:
                break
            seen.add(u)
            for v in self.adj[u]:
                w = self.edge_time(u, v)
                if w is None:
                    continue
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if dst not in dist:
            return None, math.inf
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        return path[::-1], dist[dst]

    def astar(self, src: int, dst: int, min_block: float = 30.0) -> tuple[Optional[list[int]], float]:
        """A* with an admissible euclidean-distance heuristic."""
        def h(n: int) -> float:
            return self._euclid(n, dst) * min_block

        g = {src: 0.0}
        prev: dict[int, int] = {}
        pq = [(h(src), src)]
        seen: set[int] = set()
        while pq:
            f, u = heapq.heappop(pq)
            if u == dst:
                path = [dst]
                while path[-1] != src:
                    path.append(prev[path[-1]])
                return path[::-1], g[dst]
            if u in seen:
                continue
            seen.add(u)
            for v in self.adj[u]:
                w = self.edge_time(u, v)
                if w is None:
                    continue
                ng = g[u] + w
                if ng < g.get(v, math.inf):
                    g[v] = ng
                    prev[v] = u
                    heapq.heappush(pq, (ng + h(v), v))
        return None, math.inf

    def route(self, src: int, dst: int) -> tuple[Optional[list[int]], float]:
        """Default router: A*; falls back to Dijkstra if heuristic search fails."""
        path, t = self.astar(src, dst)
        if path is None:
            path, t = self.dijkstra(src, dst)
        return path, t

    def reroute_if_blocked(self, current: int, dst: int,
                           old_route: list[int]) -> tuple[Optional[list[int]], float]:
        """Dynamic re-routing: if any remaining edge is now closed or the
        remaining route got >40% slower, recompute from current position."""
        if not old_route or current not in old_route:
            return self.route(current, dst)
        idx = old_route.index(current)
        remaining = old_route[idx:]
        ok, t_old = True, 0.0
        for a, b in zip(remaining, remaining[1:]):
            w = self.edge_time(a, b)
            if w is None:
                ok = False
                break
            t_old += w
        new_path, t_new = self.route(current, dst)
        if not ok or (new_path and t_new < t_old / 1.4):
            return new_path, t_new
        return remaining, t_old
