"""Build a real city road graph from OpenStreetMap (Overpass API).

For any configured city this fetches major drivable roads, fire stations
and named landmarks (hospitals, malls, universities, rail stations),
collapses degree-2 chains into weighted edges (travel seconds by road
class), keeps the largest connected component, and writes
server/data/<city>_city.json for the runtime to load.

    python3 scripts/build_city.py seattle
    python3 scripts/build_city.py delhi mumbai

Adding a city = adding one CITIES entry and running this script.
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# south, west, north, east
CITIES: dict[str, dict] = {
    "seattle": {"name": "Seattle", "country": "US",
                "bbox": (47.50, -122.43, 47.73, -122.24)},
    "delhi":   {"name": "Delhi", "country": "IN",
                "bbox": (28.45, 77.02, 28.72, 77.32)},
    "mumbai":  {"name": "Mumbai", "country": "IN",
                "bbox": (18.89, 72.77, 19.28, 73.03)},
}

OVERPASS = "https://overpass-api.de/api/interpreter"
DATA_DIR = Path(__file__).resolve().parent.parent / "server" / "data"
MIN_STATIONS = 10   # synthesize spread-out stations below this
MAX_POIS = 150

SPEED = {  # km/h by highway class
    "motorway": 90, "motorway_link": 60,
    "trunk": 70, "trunk_link": 50,
    "primary": 55, "primary_link": 45,
    "secondary": 45, "tertiary": 40,
}

HIGHWAY_RE = "^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link)$"


def overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS, data=data,
                                 headers={"User-Agent": "dispatch-grid-builder"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())


def build(key: str) -> None:
    cfg = CITIES[key]
    s, w, n, e = cfg["bbox"]
    bbox = f"{s},{w},{n},{e}"

    print(f"[{key}] fetching roads…")
    roads = overpass(f'[out:json][timeout:180];'
                     f'(way["highway"~"{HIGHWAY_RE}"]({bbox}););'
                     f'out body; >; out skel qt;')
    coords: dict[int, tuple[float, float]] = {}
    ways = []
    for el in roads["elements"]:
        if el["type"] == "node":
            coords[el["id"]] = (el["lat"], el["lon"])
        elif el["type"] == "way":
            ways.append(el)
    print(f"  {len(ways)} ways, {len(coords)} raw nodes")

    lat_mid = (s + n) / 2
    lat0, lon0 = n, w                              # top-left origin
    klat = 110.574
    klon = 111.320 * math.cos(math.radians(lat_mid))

    def project(lat: float, lon: float) -> tuple[float, float]:
        return ((lon - lon0) * klon, (lat0 - lat) * klat)

    usage = defaultdict(int)
    for wy in ways:
        for nd in wy["nodes"]:
            usage[nd] += 1

    def seg_km(a: int, b: int) -> float:
        (la1, lo1), (la2, lo2) = coords[a], coords[b]
        return math.hypot((la1 - la2) * klat, (lo1 - lo2) * klon)

    adj: dict[int, dict[int, float]] = defaultdict(dict)
    for wy in ways:
        nodes = [nd for nd in wy["nodes"] if nd in coords]
        if len(nodes) < 2:
            continue
        speed = SPEED.get(wy["tags"].get("highway", ""), 40)
        kept = [i for i, nd in enumerate(nodes)
                if i in (0, len(nodes) - 1) or usage[nd] >= 2]
        for i, j in zip(kept, kept[1:]):
            km = sum(seg_km(nodes[k], nodes[k + 1]) for k in range(i, j))
            if km <= 0:
                continue
            secs = km / speed * 3600.0
            a, b = nodes[i], nodes[j]
            if a != b and (adj[a].get(b) is None or secs < adj[a][b]):
                adj[a][b] = secs
                adj[b][a] = secs

    # largest connected component
    seen: set[int] = set()
    best: set[int] = set()
    for start in adj:
        if start in seen:
            continue
        comp, stack = {start}, [start]
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
          f"({sum(len(adj[nd]) for nd in best) // 2} edges)")

    remap = {osm: i for i, osm in enumerate(sorted(best))}
    nodes_xy: dict[str, list[float]] = {}
    latlon: dict[str, list[float]] = {}
    for osm, i in remap.items():
        la, lo = coords[osm]
        x, y = project(la, lo)
        nodes_xy[str(i)] = [round(x, 4), round(y, 4)]
        latlon[str(i)] = [la, lo]
    edges = []
    for osm, i in remap.items():
        for nb, secs in adj[osm].items():
            j = remap.get(nb)
            if j is not None and i < j:
                edges.append([i, j, round(secs, 1)])

    def nearest(x: float, y: float) -> str:
        return min(nodes_xy, key=lambda nd: (nodes_xy[nd][0] - x) ** 2 +
                                            (nodes_xy[nd][1] - y) ** 2)

    print(f"[{key}] fetching fire stations…")
    time.sleep(5)  # be polite to Overpass between queries
    st = overpass(f'[out:json][timeout:120];'
                  f'(nwr["amenity"="fire_station"]({bbox}););out center;')
    stations = []
    for el in st["elements"]:
        la = el.get("lat") or el.get("center", {}).get("lat")
        lo = el.get("lon") or el.get("center", {}).get("lon")
        if la is None:
            continue
        x, y = project(la, lo)
        stations.append({"node": int(nearest(x, y)),
                         "name": el.get("tags", {}).get("name", "Fire Station")})
    stations = list({st["node"]: st for st in stations}.values())
    print(f"  {len(stations)} OSM fire stations")

    # sparse OSM coverage (common outside the US/EU): synthesize extra
    # stations by farthest-point sampling so the fleet has spread bases
    if len(stations) < MIN_STATIONS:
        have = [nodes_xy[str(st["node"])] for st in stations] or \
               [nodes_xy[nearest((max(p[0] for p in nodes_xy.values())) / 2,
                                 (max(p[1] for p in nodes_xy.values())) / 2)]]
        all_ids = list(nodes_xy)
        step = max(1, len(all_ids) // 800)
        candidates = all_ids[::step]
        while len(stations) < MIN_STATIONS + 2:
            def dmin(nd: str) -> float:
                x, y = nodes_xy[nd]
                return min((x - hx) ** 2 + (y - hy) ** 2 for hx, hy in have)
            pick = max(candidates, key=dmin)
            have.append(nodes_xy[pick])
            stations.append({"node": int(pick),
                             "name": f"Station {len(stations) + 1}"})
        print(f"  padded to {len(stations)} with synthesized stations")

    print(f"[{key}] fetching landmarks…")
    time.sleep(5)
    poi_raw = overpass(
        f'[out:json][timeout:120];('
        f'nwr["amenity"~"^(hospital|university)$"]["name"]({bbox});'
        f'nwr["railway"="station"]["name"]({bbox});'
        f'nwr["shop"="mall"]["name"]({bbox});'
        f');out center;')
    pois = []
    seen_names: set[str] = set()
    for el in poi_raw["elements"]:
        name = el.get("tags", {}).get("name")
        la = el.get("lat") or el.get("center", {}).get("lat")
        lo = el.get("lon") or el.get("center", {}).get("lon")
        if not name or la is None or name in seen_names:
            continue
        seen_names.add(name)
        x, y = project(la, lo)
        pois.append({"node": int(nearest(x, y)), "name": name})
        if len(pois) >= MAX_POIS:
            break
    print(f"  {len(pois)} named landmarks")

    out = DATA_DIR / f"{key}_city.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "city": cfg["name"],
        "country": cfg["country"],
        "bbox": list(cfg["bbox"]),
        "projection": {"lat0": lat0, "lon0": lon0, "klat": klat, "klon": klon},
        "nodes": nodes_xy,
        "latlon": latlon,
        "edges": edges,
        "stations": stations,
        "pois": pois,
    }))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)\n")


if __name__ == "__main__":
    keys = sys.argv[1:] or ["seattle"]
    for k in keys:
        if k not in CITIES:
            sys.exit(f"unknown city {k!r} — add it to CITIES first "
                     f"(known: {', '.join(CITIES)})")
        build(k)
        if k != keys[-1]:
            time.sleep(10)
