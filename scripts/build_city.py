"""Build a real city road graph from OpenStreetMap (Overpass API).

Fetches major drivable roads + fire stations for Seattle, collapses
degree-2 chains into weighted edges (travel seconds by road class),
keeps the largest connected component, and writes
server/data/seattle_city.json for the runtime to load.

    python3 scripts/build_city.py
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

BBOX = (47.50, -122.43, 47.73, -122.24)          # south, west, north, east
OVERPASS = "https://overpass-api.de/api/interpreter"
OUT = Path(__file__).resolve().parent.parent / "server" / "data" / "seattle_city.json"

# km/h by highway class
SPEED = {
    "motorway": 90, "motorway_link": 60,
    "trunk": 70, "trunk_link": 50,
    "primary": 55, "primary_link": 45,
    "secondary": 45, "tertiary": 40,
}

ROADS_QUERY = f"""
[out:json][timeout:120];
(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link)$"]
  ({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}););
out body; >; out skel qt;
"""

STATIONS_QUERY = f"""
[out:json][timeout:60];
(nwr["amenity"="fire_station"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}););
out center;
"""


def overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS, data=data,
                                 headers={"User-Agent": "dispatch-grid-builder"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def project(lat: float, lon: float, lat0: float, lon0: float,
            klat: float, klon: float) -> tuple[float, float]:
    """Project to local km, y growing southward (SVG convention)."""
    return ((lon - lon0) * klon, (lat0 - lat) * klat)


def main() -> None:
    print("fetching roads…")
    roads = overpass(ROADS_QUERY)
    coords: dict[int, tuple[float, float]] = {}
    ways = []
    for el in roads["elements"]:
        if el["type"] == "node":
            coords[el["id"]] = (el["lat"], el["lon"])
        elif el["type"] == "way":
            ways.append(el)
    print(f"  {len(ways)} ways, {len(coords)} raw nodes")

    lat_mid = (BBOX[0] + BBOX[2]) / 2
    lat0, lon0 = BBOX[2], BBOX[1]                 # top-left origin
    klat = 110.574                                # km per degree latitude
    klon = 111.320 * math.cos(math.radians(lat_mid))

    # count how many ways touch each node: >=2 means intersection
    usage = defaultdict(int)
    for w in ways:
        for n in w["nodes"]:
            usage[n] += 1

    def seg_km(a: int, b: int) -> float:
        (la1, lo1), (la2, lo2) = coords[a], coords[b]
        return math.hypot((la1 - la2) * klat, (lo1 - lo2) * klon)

    # collapse each way into edges between kept nodes (intersections/endpoints)
    adj: dict[int, dict[int, float]] = defaultdict(dict)
    for w in ways:
        nodes = [n for n in w["nodes"] if n in coords]
        if len(nodes) < 2:
            continue
        speed = SPEED.get(w["tags"].get("highway", ""), 40)
        kept = [i for i, n in enumerate(nodes)
                if i in (0, len(nodes) - 1) or usage[n] >= 2]
        for i, j in zip(kept, kept[1:]):
            km = sum(seg_km(nodes[k], nodes[k + 1]) for k in range(i, j))
            if km <= 0:
                continue
            secs = km / speed * 3600.0
            a, b = nodes[i], nodes[j]
            if a != b:
                prev = adj[a].get(b)
                if prev is None or secs < prev:
                    adj[a][b] = secs
                    adj[b][a] = secs

    # largest connected component
    seen: set[int] = set()
    best: set[int] = set()
    for start in adj:
        if start in seen:
            continue
        comp = {start}
        stack = [start]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in comp:
                    comp.add(v)
                    stack.append(v)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    print(f"  {len(best)} nodes in largest component "
          f"({sum(len(adj[n]) for n in best) // 2} edges)")

    remap = {osm: i for i, osm in enumerate(sorted(best))}
    nodes_xy = {}
    latlon = {}
    for osm, i in remap.items():
        la, lo = coords[osm]
        x, y = project(la, lo, lat0, lon0, klat, klon)
        nodes_xy[str(i)] = [round(x, 4), round(y, 4)]
        latlon[str(i)] = [la, lo]
    edges = []
    for osm, i in remap.items():
        for nb, secs in adj[osm].items():
            j = remap.get(nb)
            if j is not None and i < j:
                edges.append([i, j, round(secs, 1)])

    print("fetching fire stations…")
    st = overpass(STATIONS_QUERY)
    stations = []
    for el in st["elements"]:
        la = el.get("lat") or el.get("center", {}).get("lat")
        lo = el.get("lon") or el.get("center", {}).get("lon")
        if la is None:
            continue
        x, y = project(la, lo, lat0, lon0, klat, klon)
        nearest = min(nodes_xy, key=lambda n: (nodes_xy[n][0] - x) ** 2 +
                                              (nodes_xy[n][1] - y) ** 2)
        name = el.get("tags", {}).get("name", "Fire Station")
        stations.append({"node": int(nearest), "name": name})
    # dedupe stations that snapped to the same node
    stations = list({s["node"]: s for s in stations}.values())
    print(f"  {len(stations)} stations")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "city": "Seattle",
        "bbox": BBOX,
        "projection": {"lat0": lat0, "lon0": lon0, "klat": klat, "klon": klon},
        "nodes": nodes_xy,
        "latlon": latlon,
        "edges": edges,
        "stations": stations,
    }))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
