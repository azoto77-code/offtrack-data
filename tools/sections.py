#!/usr/bin/env python3
"""The official average speed stretches of a zone, as lines along the roads of OpenStreetMap.

Two lists, both from the authorities and both without the road between the two ends:
- the Tutor of the Italian motorways (Polizia di Stato, tools/data/tutor.csv from tutor_pdf.py): from one exit to the
  next, by name. Each exit is the motorway_junction of OSM with the same name; of the junctions with those names, the
  two nearest along a carriageway, at most MAX_SECTION_M apart, are the stretch. An exit not found is reported;
- the "cinemómetros de velocidad media" of the DGT (Spain, DATEX II, CC BY): the coordinates of the two ends. Each end
  is the nearest road within SNAP_M, and the stretch the shortest way from the first to the second.
The road is found with the one-way rules, so each stretch lies on its own carriageway. The DGT's fixed cameras of the
same file come as points.

Each stretch becomes a speed camera at its start, with camera:type=average_speed, so an app that knows only points
warns of it all the same, and the line in "section:line" (Google's encoded polyline, precision 5), its length in
"section:m" and the limit of OSM when it is the same along the whole stretch.
"""
import csv
import hashlib
import heapq
import math
import re
import unicodedata
import xml.etree.ElementTree as ET

import osmium

# The roads a stretch can run along; links are left out, so a way from one carriageway to the other is not found.
CLASSES = {"motorway", "trunk", "primary", "secondary"}
TUTOR_CLASSES = {"motorway", "trunk"}

# The slip roads, kept apart: a Tutor stretch may start or end on one, when its exit is mapped on the slip road of an
# interchange ("Villesse" on the ramp to the A34), and only when the carriageways alone give no way.
LINKS = {"motorway_link", "trunk_link"}

# The most of a stretch that may run on slip roads.
MAX_LINKS_M = 3000.0

# How much longer than the straight line a stretch may be: a motorway is seldom a third longer, while a way that turns
# back at an interchange (an end mapped on the carriageway the other way, or on the other road of the interchange) is
# two or three times longer.
DETOUR = 1.5

# The longest stretch looked for: the Tutor stretches are 2 to 30 km long.
MAX_SECTION_M = 45_000.0

# How far from a DGT end its road may be.
SNAP_M = 80.0

# How far from an exit's junction its carriageway may be: less than the gap to the other carriageway.
JUNCTION_M = 25.0

# How far the other carriageway may be: OSM often has an exit's junction on one carriageway only, and the stretch
# going the other way starts from the carriageway across from it.
OTHER_CARRIAGEWAY_M = 200.0

# A stretch shorter than this is two names of the same exit.
MIN_SECTION_M = 500.0

# The cells of the grid that tells which ways to read, in degrees: about 5 km.
CELL = 0.05

# The line keeps a point every few metres where the road bends: SIMPLIFY_M off the real line at most.
SIMPLIFY_M = 4.0

# A camera already within this distance of a stretch's start is that same camera.
SAME_M = 50.0

DATEX = "{http://datex2.eu/schema/1_0/1_0}"
POLIZIA = "Polizia di Stato"
DGT = "DGT"


def distance_m(a, b):
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * 110_540, (a[1] - b[1]) * 111_320 * k)


# ---------------------------------------------------------------------------------------------------- the two lists


def norm(name):
    """An exit's name to compare: capitals without accents, only letters and digits, a few spellings made one."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    s = s.replace("'", "")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    words = s.split()
    out = []
    i = 0
    while i < len(words):
        w = words[i]
        # "S.M. CAPUAVETERE", "SM CAPUAVETERE"
        if w == "S" and i + 1 < len(words) and words[i + 1] == "M":
            out += ["SANTA", "MARIA"]
            i += 2
            continue
        out += ALIASES.get(w, [w])
        i += 1
    return " ".join(out)


ALIASES = {
    "SM": ["SANTA", "MARIA"],
    "S": ["SAN"],
    "CAPUAVETERE": ["CAPUA", "VETERE"],
    "COLLEFFERRO": ["COLLEFERRO"],
    "ZONA": ["Z"],
    "IND": ["I"],
    "INDUSTRIALE": ["I"],
    "LAZZARODIR": ["LAZZARO"],
}


def tutor_list(path):
    """The stretches of tutor.csv: [(from, to, direction, note)]."""
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    return [(r["da"], r["a"], r["direzione"], r["nota"]) for r in csv.DictReader(lines)]


def dgt_list(path):
    """The DGT's file: ([(id, road, (lat, lon) from, (lat, lon) to)], [(id, road, lat, lon)]) of stretches and fixed cameras."""
    root = ET.parse(path).getroot()
    sections, fixed = [], []
    for loc in root.iter(DATEX + "predefinedLocation"):
        lid = loc.get("id")
        if not lid:
            continue
        inner = loc.find(DATEX + "predefinedLocation")
        if inner is None:
            continue
        road = (inner.findtext(f".//{DATEX}roadNumber") or "").strip()
        lin = inner.find(DATEX + "tpeglinearLocation")
        pt = inner.find(DATEX + "tpegpointLocation")
        if lin is not None:
            a, b = _coords(lin.find(DATEX + "from")), _coords(lin.find(DATEX + "to"))
            if a and b:
                sections.append((lid.removeprefix("GUID_"), road, a, b))
        elif pt is not None:
            p = _coords(pt.find(DATEX + "point"))
            if p:
                fixed.append((lid.removeprefix("GUID_"), road, p[0], p[1]))
    return sections, fixed


def _coords(el):
    if el is None:
        return None
    try:
        return float(el.findtext(f"{DATEX}pointCoordinates/{DATEX}latitude")), float(
            el.findtext(f"{DATEX}pointCoordinates/{DATEX}longitude"))
    except (TypeError, ValueError):
        return None


# Exits the Polizia calls otherwise than OSM.
NAMES = {
    "PIACENZA NORD": "BASSO LODIGIANO",
}

# Words before an exit's name in the Polizia's list: "ALL SAN LAZZARO" is the junction of San Lazzaro.
_LEADING = ("ALLACCIAMENTO ", "ALL ", "NODO ", "VIADOTTO ")


def lookup(by_name, name):
    """The junctions called [name]. When none is called just so, those whose name is near it, word by word: one
    starting with it, one holding it ("CAMPEGINE" in "Terre di Canossa Campegine"), one it starts with, one it holds
    ("Corso Malta" in "VIADOTTO CORSO MALTA"), the first kind found."""
    n = norm(NAMES.get(name.strip().upper(), name))
    for lead in _LEADING:
        if n.startswith(lead) and len(n) > len(lead) + 2:
            n = n[len(lead):]
            break
    if n in by_name:
        return by_name[n]
    padded = f" {n} "
    # From the closest to the loosest: a name that goes on ("SAN DONA" and "San Donà di Piave"), one that holds it
    # ("Castel Maggiore Bologna Interporto"), one it goes on from ("RAVENNA SUD" and "Ravenna", but not "BOLOGNA
    # INTERPORTO" and "Bologna" while a name holds it whole), one it holds.
    tiers = (
        lambda k: k.startswith(n + " "),
        lambda k: f" {k} ".find(padded) >= 0,
        lambda k: n.startswith(k + " "),
        lambda k: len(k) >= 6 and padded.find(f" {k} ") >= 0,
    )
    for tier in tiers:
        out = [x for k, v in by_name.items() if tier(k) for x in v]
        if out:
            return out
    return []


# Interchanges the Polizia names by their roads: "ALL A15 A1 N" is where the A15 joins the A1, its northern branch.
_INTERCHANGE = re.compile(r"^(?:ALL|ALLACCIAMENTO|NODO)\s+(.*?)(?:\s+(?:N|S|E|O|NORD|SUD|EST|OVEST))?$")
_ROAD = re.compile(r"A\d+|SPV|RAC RM [NS]")
# The motorways called otherwise on OSM: the "raccordi" of Rome are the A1's branches, A1dir.
ROAD_REFS = {"RAC RM N": "A1DIR", "RAC RM S": "A1DIR"}

# How near each other two roads come at their interchange, the links between them left out.
INTERCHANGE_M = 1000.0

# The points of a road taken as its interchange: both carriageways at the place where it comes nearest the other road.
INTERCHANGE_NEAR_M = 300.0

# Two places where the same roads meet are this far apart at least.
INTERCHANGE_APART_M = 5000.0


def interchange(name):
    """The two roads of an interchange named by them, as refs of OSM: ("A15", "A1") for "ALL A15 A1 N"; None for an
    exit named by a place, or with a road unknown."""
    s = re.sub(r"[^A-Z0-9]+", " ", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()).strip()
    m = _INTERCHANGE.match(s)
    if not m:
        return None
    rest = m.group(1).strip()
    roads = _ROAD.findall(rest)
    if len(roads) != 2 or _ROAD.sub("", rest).strip():
        return None
    a, b = (ROAD_REFS.get(r, r) for r in roads)
    return (a, b) if a != b else None


def ref_key(ref):
    return ref.replace(" ", "").upper()


class RefNodes(osmium.SimpleHandler):
    """The nodes of the motorways and trunk roads with one of [refs]: ref -> [(lat, lon)]."""

    def __init__(self, refs):
        super().__init__()
        self.refs = refs
        self.nodes = {r: [] for r in refs}

    def way(self, w):
        if w.tags.get("highway") not in TUTOR_CLASSES:
            return
        mine = {ref_key(r) for r in (w.tags.get("ref") or "").split(";")} & self.refs
        for r in mine:
            self.nodes[r] += [(n.location.lat, n.location.lon) for n in w.nodes if n.location.valid()]


def meeting(xs, ys, reach=INTERCHANGE_M):
    """Where the road of the points [xs] meets that of [ys]: at each place where it comes within [reach] of it, its
    point nearest to it and its others within INTERCHANGE_NEAR_M of that one, the other carriageway."""
    c = 0.015
    grid = {}
    for q in ys:
        grid.setdefault((int(q[0] // c), int(q[1] // c)), []).append(q)
    close = []
    for p in xs:
        gy, gx = int(p[0] // c), int(p[1] // c)
        d = min((distance_m(p, q) for dy in (-1, 0, 1) for dx in (-1, 0, 1) for q in grid.get((gy + dy, gx + dx), ())),
                default=math.inf)
        if d <= reach:
            close.append((d, p))
    close.sort()
    places = []
    for _, p in close:
        if all(distance_m(p, o) > INTERCHANGE_APART_M for o in places):
            places.append(p)
    return list({p for p in xs if any(distance_m(p, o) <= INTERCHANGE_NEAR_M for o in places)})


def interchanges(pbf, pairs):
    """The points of each interchange of [pairs] ((ref, ref)): on both roads, as junctions without an id."""
    h = RefNodes({r for pair in pairs for r in pair})
    h.apply_file(str(pbf), locations=True, idx="flex_mem")
    out = {}
    for a, b in pairs:
        pts = meeting(h.nodes[a], h.nodes[b]) + meeting(h.nodes[b], h.nodes[a])
        out[(a, b)] = [(None, lat, lon) for lat, lon in pts]
    return out


# ----------------------------------------------------------------------------------------------------- the roads


class Junctions(osmium.SimpleHandler):
    """The motorway exits with a name: normalized name -> [(node id, lat, lon)]."""

    def __init__(self):
        super().__init__()
        self.by_name = {}

    def node(self, n):
        if n.tags.get("highway") != "motorway_junction" or not n.location.valid():
            return
        for key in ("name", "official_name", "alt_name"):
            v = n.tags.get(key)
            if v:
                for part in v.split(";"):
                    self.by_name.setdefault(norm(part), []).append((n.id, n.location.lat, n.location.lon))


class Roads(osmium.SimpleHandler):
    """The ways of CLASSES with a node in one of [cells], as a graph with the one-way rules."""

    def __init__(self, cells):
        super().__init__()
        self.cells = cells
        self.coords = {}
        self.edges = {}
        self.ways = []

    def way(self, w):
        hw = w.tags.get("highway")
        if hw not in CLASSES and hw not in LINKS:
            return
        pts = [(r.ref, r.location.lat, r.location.lon) for r in w.nodes if r.location.valid()]
        if len(pts) < 2 or not any(cell_of(p[1], p[2]) in self.cells for p in pts):
            return
        oneway = w.tags.get("oneway", "")
        forward = oneway in ("yes", "1", "true") or hw == "motorway" or w.tags.get("junction") in ("roundabout", "circular")
        backward = oneway == "-1"
        if oneway == "no":
            forward = False
        wi = len(self.ways)
        self.ways.append((hw, w.tags.get("maxspeed"), w.tags.get("ref")))
        for (a, la, oa), (b, lb, ob) in zip(pts, pts[1:]):
            self.coords[a] = (la, oa)
            self.coords[b] = (lb, ob)
            d = distance_m((la, oa), (lb, ob))
            if not backward:
                self.edges.setdefault(a, []).append((b, d, wi))
            if not forward:
                self.edges.setdefault(b, []).append((a, d, wi))


def cell_of(lat, lon):
    return int(math.floor(lat / CELL)), int(math.floor(lon / CELL))


def cells_around(a, b, pad=1):
    """The cells of the box of [a] and [b], [pad] cells wider."""
    (y0, x0), (y1, x1) = cell_of(*a), cell_of(*b)
    return {(y, x) for y in range(min(y0, y1) - pad, max(y0, y1) + pad + 1)
            for x in range(min(x0, x1) - pad, max(x0, x1) + pad + 1)}


def shortest(roads, starts, ends, classes, limit=MAX_SECTION_M):
    """The shortest way from one of [starts] to one of [ends] on ways of [classes]: (metres, [node ids]) or None.
    Both are lists of nodes or dicts of a node with the metres to add before it or after it."""
    starts = starts if isinstance(starts, dict) else dict.fromkeys(starts, 0.0)
    ends = ends if isinstance(ends, dict) else dict.fromkeys(ends, 0.0)
    best = dict(starts)
    back = {}
    heap = [(d, s) for s, d in starts.items()]
    heapq.heapify(heap)
    found = None
    while heap:
        d, n = heapq.heappop(heap)
        if found and d >= found[0]:
            break
        if d > best.get(n, math.inf):
            continue
        if n in ends and (found is None or d + ends[n] < found[0]):
            found = (d + ends[n], n)
        for m, w, wi in roads.edges.get(n, ()):
            if roads.ways[wi][0] not in classes:
                continue
            nd = d + w
            if nd <= limit and nd < best.get(m, math.inf):
                best[m] = nd
                back[m] = n
                heapq.heappush(heap, (nd, m))
    if not found:
        return None
    path = [found[1]]
    while path[-1] in back:
        path.append(back[path[-1]])
    return found[0], path[::-1]


def segment_grid(roads):
    """The directed segments of [roads] by the cells they cross: cell -> [(a, b, way index)]."""
    grid = {}
    for a, out in roads.edges.items():
        pa = roads.coords[a]
        for b, d, wi in out:
            pb = roads.coords[b]
            steps = max(1, int(d // 1000))
            cells = {cell_of(pa[0] + (pb[0] - pa[0]) * i / steps, pa[1] + (pb[1] - pa[1]) * i / steps) for i in range(steps + 1)}
            for c in cells:
                grid.setdefault(c, []).append((a, b, wi))
    return grid


def snap(roads, grid, p, radius, classes=CLASSES):
    """The segments of ways of [classes] within [radius] of [p]: [(a, b, point on the segment nearest to p)]."""
    cy, cx = cell_of(*p)
    k = math.cos(math.radians(p[0]))
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for a, b, wi in grid.get((cy + dy, cx + dx), ()):
                if roads.ways[wi][0] not in classes:
                    continue
                (la, oa), (lb, ob) = roads.coords[a], roads.coords[b]
                ax, ay = (oa - p[1]) * 111_320 * k, (la - p[0]) * 110_540
                bx, by = (ob - p[1]) * 111_320 * k, (lb - p[0]) * 110_540
                vx, vy = bx - ax, by - ay
                ll = vx * vx + vy * vy
                t = 0.0 if ll == 0 else max(0.0, min(1.0, -(ax * vx + ay * vy) / ll))
                if math.hypot(ax + t * vx, ay + t * vy) <= radius:
                    out.append((a, b, (la + t * (lb - la), oa + t * (ob - oa))))
    return out


def between(roads, grid, ps, qs, classes, limit, radius=SNAP_M):
    """The shortest way from the road at one of the points [ps] to the road at one of [qs], on ways of [classes]:
    (metres, [(lat, lon)], [node ids]) or None."""
    starts, ends, first, last = {}, {}, {}, {}
    for p in ps:
        for a, b, x in snap(roads, grid, p, radius, classes):
            d = distance_m(x, roads.coords[b])
            if d < starts.get(b, math.inf):
                starts[b], first[b] = d, (x, a)
    for q in qs:
        for a, b, x in snap(roads, grid, q, radius, classes):
            d = distance_m(roads.coords[a], x)
            if d < ends.get(a, math.inf):
                ends[a], last[a] = d, (x, b)
    if not starts or not ends:
        return None
    found = shortest(roads, starts, ends, classes, limit)
    if not found:
        return None
    length, path = found
    (x, before), (y, after) = first[path[0]], last[path[-1]]
    # The nodes with the two segments the ends fall on, for their ways' limits; the line from the ends themselves.
    return length, [x] + [roads.coords[n] for n in path] + [y], [before] + path + [after]


def plausible(roads, found, links=False):
    """Whether a way found does not turn back, and keeps to the slip roads for a few metres when it may use them."""
    length, pts, path = found
    if length > distance_m(pts[0], pts[-1]) * DETOUR + 1000:
        return False
    return not links or links_m(roads, path) <= MAX_LINKS_M


def links_m(roads, path):
    """The metres of [path] on slip roads."""
    out = 0.0
    for a, b in zip(path, path[1:]):
        for m, d, wi in roads.edges.get(a, ()):
            if m == b:
                if roads.ways[wi][0] in LINKS:
                    out += d
                break
    return out


def limit_along(roads, path):
    """The maxspeed of OSM when the same on every way of [path], else None."""
    seen = set()
    for a, b in zip(path, path[1:]):
        for m, _, wi in roads.edges.get(a, ()):
            if m == b:
                # A slip road has its own limit, not the stretch's.
                if roads.ways[wi][0] not in LINKS:
                    seen.add(roads.ways[wi][1])
                break
    if len(seen) == 1:
        v = seen.pop()
        if v and re.fullmatch(r"\d{2,3}", v):
            return v
    return None


# ------------------------------------------------------------------------------------------------------ the line


def simplify(pts, tol=SIMPLIFY_M):
    """Douglas-Peucker on [(lat, lon)], [tol] metres."""
    if len(pts) < 3:
        return list(pts)
    k = math.cos(math.radians(pts[0][0]))
    xy = [(p[1] * 111_320 * k, p[0] * 110_540) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x0, y0), (x1, y1) = xy[i], xy[j]
        dx, dy = x1 - x0, y1 - y0
        ll = dx * dx + dy * dy
        far, at = -1.0, -1
        for m in range(i + 1, j):
            x, y = xy[m]
            if ll == 0:
                d = math.hypot(x - x0, y - y0)
            else:
                t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / ll))
                d = math.hypot(x - x0 - t * dx, y - y0 - t * dy)
            if d > far:
                far, at = d, m
        if far > tol:
            keep[at] = True
            stack += [(i, at), (at, j)]
    return [p for p, k_ in zip(pts, keep) if k_]


def encode(pts):
    """Google's encoded polyline, precision 5."""
    out = []
    plat = plon = 0
    for lat, lon in pts:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def decode(s):
    """The points of an encoded polyline, precision 5."""
    pts, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lon += vals[1]
        pts.append((lat / 1e5, lon / 1e5))
    return pts


def row(sid, name, source, roads, length, path, ref=None, pts=None):
    pts = simplify(pts or [roads.coords[n] for n in path])
    tags = {"camera:type": "average_speed", "source": source, "section:line": encode(pts), "section:m": str(round(length))}
    limit = limit_along(roads, path)
    if limit:
        tags["maxspeed"] = limit
    if ref:
        tags["ref"] = ref
    return [sid, "speed_camera", round(pts[0][0], 7), round(pts[0][1], 7), name, tags]


def slug(*parts):
    s = "-".join(norm(p).lower().replace(" ", "-") for p in parts if p)
    return s if len(s) <= 60 else s[:50] + "-" + hashlib.sha1(s.encode()).hexdigest()[:8]


# ------------------------------------------------------------------------------------------------------ the zone


def build(pbf, tutor=None, dgt=None, log=print):
    """The rows of the stretches found in [pbf] (motorways and main roads with their exits), and the DGT's fixed cameras."""
    j = Junctions()
    if tutor:
        j.apply_file(str(pbf), locations=False)
    wanted = []
    cells = set()
    missing = {}
    # The interchanges named by their roads are found where the two roads meet: their names on OSM, when they have
    # one, are not those of the list ("ALL A30 A1" would be any junction of the A30).
    pairs = {interchange(n) for r in tutor or [] for n in r[:2]} - {None}
    places = interchanges(pbf, pairs) if pairs else {}
    for da, a, d, note in tutor or []:
        # The ends by the roads of an interchange, then by its name on OSM when the first give no road between.
        tries = []
        for sa, sb in ((places.get(interchange(da)) or lookup(j.by_name, da), places.get(interchange(a)) or lookup(j.by_name, a)),
                       (lookup(j.by_name, da), lookup(j.by_name, a))):
            # "ROVIGO" found only as "Rovigo Sud", the other end: not the same exit twice.
            sa, sb = [x for x in sa if x not in sb], [y for y in sb if y not in sa]
            near = [(x, y) for x in sa for y in sb if distance_m(x[1:], y[1:]) <= MAX_SECTION_M]
            if near and (sa, sb) not in [t[:2] for t in tries]:
                tries.append((sa, sb, near))
            if not tries and (sa or sb) and not (sa and sb):
                # One end is in the zone: the name of the other is not on OSM as written.
                for name, found in ((da, sa), (a, sb)):
                    if not found:
                        missing[name] = missing.get(name, 0) + 1
                break
        if not tries:
            continue
        wanted.append(("tutor", (da, a, d, note), [([x[1:] for x in sa], [y[1:] for y in sb]) for sa, sb, _ in tries]))
        for _, _, near in tries:
            for x, y in near:
                cells |= cells_around(x[1:], y[1:])
    dgt_sections, dgt_fixed = dgt_list(dgt) if dgt else ([], [])
    for s in dgt_sections:
        cells |= cells_around(s[2], s[3], pad=0)
    if not wanted and not dgt_sections:
        return [], [(f"dgt-{i}", "speed_camera", lat, lon, None,
                     {"camera:type": "fixed", "source": DGT}) for i, _, lat, lon in dgt_fixed], missing
    roads = Roads(cells)
    roads.apply_file(str(pbf), locations=True, idx="flex_mem")
    grid = segment_grid(roads)
    out = []
    lost = []
    for _, (da, a, d, note), tries in wanted:
        found = None
        # The exit is on its carriageway, or on the slip road just off it; else on the other carriageway; else on the
        # slip roads of an interchange, for a few of the stretch's metres.
        for classes, radius in ((TUTOR_CLASSES, JUNCTION_M), (TUTOR_CLASSES, OTHER_CARRIAGEWAY_M),
                                (TUTOR_CLASSES | LINKS, JUNCTION_M)):
            for sa, sb in tries:
                found = between(roads, grid, sa, sb, classes, MAX_SECTION_M, radius=radius)
                if found and (found[0] < MIN_SECTION_M or not plausible(roads, found, bool(classes & LINKS))):
                    found = None
                if found:
                    break
            if found:
                break
        if not found:
            lost.append(f"{da} - {a} ({d})")
            continue
        length, pts, path = found
        name = f"{da.title()} - {a.title()}"
        out.append(row(f"tutor-{slug(da, a, d)}", name, POLIZIA, roads, length, path, pts=pts))
    for sid, road, p, q in dgt_sections:
        found = between(roads, grid, [p], [q], CLASSES, limit=distance_m(p, q) * 2 + 2000)
        if not found:
            if snap(roads, grid, p, SNAP_M) or snap(roads, grid, q, SNAP_M):
                lost.append(f"DGT {sid} {road}")
            continue
        length, pts, path = found
        out.append(row(f"dgt-{sid}", road or None, DGT, roads, length, path, ref=road or None, pts=pts))
    if lost:
        log(f"  tratti con le due uscite nella zona ma senza strada tra loro: {len(lost)} ({'; '.join(lost[:15])})")
    fixed = [[f"dgt-{i}", "speed_camera", lat, lon, None, {"camera:type": "fixed", "source": DGT}]
             for i, _, lat, lon in dgt_fixed]
    return out, fixed, missing


def add(points, sections):
    """[sections] into [points] (id -> row): a camera at a stretch's start is that stretch, as the MapAtlas points of
    average speed at one of its ends; returns how many were taken out."""
    ends = []
    for s in sections:
        line = decode(s[5]["section:line"])
        ends.append((s, line[0], line[-1]))
    gone = 0
    for e in list(points.values()):
        if e[1] != "speed_camera":
            continue
        p = (e[2], e[3])
        for s, a, b in ends:
            at_start = distance_m(p, a) <= SAME_M
            mci_end = e[0].startswith("mci-") and e[5].get("camera:type") == "average_speed" and distance_m(p, b) <= SAME_M
            if at_start or mci_end:
                if at_start and "maxspeed" not in s[5] and "maxspeed" in e[5]:
                    s[5]["maxspeed"] = e[5]["maxspeed"]
                del points[e[0]]
                gone += 1
                break
    for s in sections:
        points[s[0]] = s
    return gone


def main():
    """Tries the lists on an extract and writes what it found as GeoJSON, to look at: sections.py ROADS.pbf OUT.geojson
    [--tutor CSV] [--dgt XML]."""
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument("pbf")
    p.add_argument("out")
    p.add_argument("--tutor")
    p.add_argument("--dgt")
    a = p.parse_args()
    out, fixed, missing = build(a.pbf, tutor_list(a.tutor) if a.tutor else None, a.dgt)
    print(f"{len(out)} tratti, {len(fixed)} fissi DGT")
    for name, n in sorted(missing.items()):
        print(f"  uscita non trovata: {name} ({n})")
    feats = [{"type": "Feature", "properties": {"id": r[0], "name": r[4], **{k: v for k, v in r[5].items() if k != "section:line"}},
              "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in decode(r[5]["section:line"])]}}
             for r in out]
    for r in out:
        print(f"  {r[0]}: {r[4]}, {r[5]['section:m']} m, limite {r[5].get('maxspeed', '?')}")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
