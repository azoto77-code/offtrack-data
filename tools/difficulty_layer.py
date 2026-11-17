#!/usr/bin/env python3
"""Writes the unpaved roads and paths of OpenStreetMap files as GeoJSON lines, with their difficulty level, for the
OffTrack difficulty map.

Each way that is not plain asphalt becomes one feature with its level 2-5 ("lvl", the weighted mean of LevelRule), the
tag with the hardest vote ("why"), "guess" when no tag says anything about the ground, "banned" with the tag that
closes it to motorbikes, "minz" the first zoom it is drawn at (12 for paths, 11 for roads and for paths with the clues
of a road), and the OpenStreetMap tags the app shows when a road is tapped. The output is GeoJSON text sequences for
tippecanoe.

    difficulty_layer.py OUT.geojsonseq IN.osm.pbf [IN.osm.pbf ...] [--barriers BARRIERS.geojsonseq BARRIERS.osm.pbf]

With --barriers it also writes the barrier nodes on the ways of the map (from BARRIERS.osm.pbf, the roads filtered
with osmium tags-filter n/barrier) as points with "kind" chiuso/aperto/paletti and "aperta" when on an open way, for
the layer "barriere".

The levels must stay the same as Levels.kt in the app (core/.../difficulty/Levels.kt): change both together. The app
works the level out again from the tags when it draws, so "lvl" is for the files before 0.288 and for checks.
"""
import json
import re
import sys

import osmium

PAVED = {
    "asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "sett",
    "cobblestone", "unhewn_cobblestone", "chipseal", "metal", "wood",
}
EASY_UNPAVED = {"compacted", "fine_gravel", "gravel"}
MID_UNPAVED = {"unpaved", "dirt", "ground", "earth"}
HARD_SURF = {"rock", "stone", "pebblestone", "sand", "mud", "grass", "grass_paver", "shells", "snow", "ice"}
SINGLETRACK = {"path", "footway", "bridleway", "steps", "cycleway", "pedestrian"}
ROAD_DEFAULT_PAVED = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "service", "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link", "road", "busway",
}
SMOOTHNESS_MIN = {
    "intermediate": 2, "bad": 3, "very_bad": 4, "horrible": 5, "very_horrible": 5, "impassable": 5,
}
ALLOWED = {"yes", "designated", "permissive", "destination"}
BANNED = {"no", "private", "agricultural", "forestry", "delivery", "customers", "emergency"}

# Tags kept with each feature: those Levels.kt reads, the names, and what the card of a tapped road shows.
KEPT = (
    "highway", "name", "ref", "tracktype", "surface", "smoothness", "access", "motor_vehicle",
    "motorcycle", "vehicle", "sac_scale", "mtb:scale", "incline", "width", "ford", "4wd_only",
)

# Not roads, or not there yet or any more: as DifficultyFetch leaves them out.
SKIPPED_HIGHWAYS = {
    "proposed", "construction", "platform", "bus_stop", "corridor", "elevator", "abandoned", "razed", "raceway",
}
# Pavements and crossings are footways in towns: hundreds of grey lines nobody rides.
SKIPPED_FOOTWAYS = {"sidewalk", "crossing", "traffic_island", "access_aisle"}


# The weighted level (Il Maestro, 16-17 November), as LevelRule in Levels.kt: each tag votes 2-5 and weighs as
# below, the kind of way always votes with TYPE_WEIGHT. Keep the numbers the same on both sides.
WEIGHTS = (("tracktype", 3.0), ("surface", 2.0), ("smoothness", 2.0), ("mtb:scale", 1.5), ("width", 1.0))
TYPE_WEIGHT = 0.5
ROAD_CLUES = 2
ROAD_WIDTH_M = 2.5
# The paths that can turn into roads: steps, cycleways and pedestrian areas say what they are for.
PATH_MAYBE_ROAD = {"path", "footway", "bridleway"}

TRACKTYPE_VOTE = {"grade1": 2, "grade2": 2, "grade3": 3, "grade4": 4, "grade5": 5}
SMOOTHNESS_VOTE = {
    "excellent": 2, "good": 2, "intermediate": 2, "bad": 3, "very_bad": 4, "horrible": 4.5,
    "very_horrible": 5, "impassable": 5,
}
MTB_VOTE = {
    **{v: 2 for v in ("0-", "0", "0+")}, **{v: 3 for v in ("1-", "1", "1+")}, **{v: 4 for v in ("2-", "2", "2+")},
    **{v: 5 for v in ("3-", "3", "3+", "4-", "4", "4+", "5-", "5", "5+", "6")},
}

# MapLibre on Android reads the number at the start of a text and drops the rest: "3 m" is 3, "2,5" is 2.
LEADING = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def number(v):
    m = LEADING.match(v or "")
    return float(m.group(0)) if m else 0.0


def surface_vote(s):
    if s in PAVED:
        return 1
    if s in EASY_UNPAVED:
        return 2
    if s in MID_UNPAVED:
        return 3
    if s in HARD_SURF:
        return 4
    return None


def width_vote(w):
    n = number(w)
    if n >= 4:
        return 2
    if n >= 3:
        return 2.5
    if n >= 2:
        return 3
    if n > 0:
        return 4
    return None


def votes(t):
    """[(tag=value, vote)] of the tags that say something, in the order of WEIGHTS."""
    found = (
        TRACKTYPE_VOTE.get(t.get("tracktype")),
        surface_vote(t.get("surface")),
        SMOOTHNESS_VOTE.get(t.get("smoothness")),
        MTB_VOTE.get(t.get("mtb:scale")),
        width_vote(t.get("width")),
    )
    return [(f"{k}={t[k]}", v, w) for (k, w), v in zip(WEIGHTS, found) if v is not None]


def road_like(t):
    """A path with at least ROAD_CLUES clues of a road: tracktype up to grade3, width, motor vehicles on it."""
    if t.get("highway") not in PATH_MAYBE_ROAD:
        return False
    motor = any(t.get(k, "no") not in ("", "no") for k in ("motor_vehicle", "motorcycle"))
    clues = (t.get("tracktype") in ("grade1", "grade2", "grade3")) + (number(t.get("width")) >= ROAD_WIDTH_M) + motor
    return clues >= ROAD_CLUES


def is_path(t):
    """Drawn as a path (dashed, from zoom 12): a path, footway, cycleway... that is not road_like."""
    return t.get("highway") in SINGLETRACK and not road_like(t)


def paved(t):
    """Asphalt, as before the weights: only these stay level 1 and off the map (Levels.paved in the app)."""
    h = t.get("highway", "")
    s = t.get("surface")
    tt = t.get("tracktype")
    smooth_ok = SMOOTHNESS_MIN.get(t.get("smoothness"), 0) <= 2
    if h in SINGLETRACK:
        return s in PAVED and smooth_ok
    if s in PAVED and tt not in ("grade3", "grade4", "grade5"):
        return smooth_ok
    if tt is not None or s is not None:
        return False
    return h in ROAD_DEFAULT_PAVED and smooth_ok


def value(t):
    """The weighted mean of the votes, 2.0-5.0, as LevelRule.value."""
    if t.get("highway") in SINGLETRACK and not road_like(t):
        kind = 5
    elif road_like(t) or t.get("highway") == "track":
        kind = 3
    else:
        kind = 2
    vs = votes(t)
    top = sum(v * w for _, v, w in vs) + kind * TYPE_WEIGHT
    bottom = sum(w for _, _, w in vs) + TYPE_WEIGHT
    return min(max(top / bottom, 2.0), 5.0)


def band(v):
    return 2 if v < 2.5 else 3 if v < 3.5 else 4 if v < 4.5 else 5


def level(t):
    """(level, reason, guess) of a way from its tags, as Levels.of in the app: 1 on asphalt, else the weighted level,
    the tag with the hardest vote, and a guess when no tag says anything about the ground."""
    h = t.get("highway", "")
    if paved(t):
        why = f"surface={t['surface']}" if t.get("surface") is not None else f"highway={h}"
        return 1, why, h in ROAD_DEFAULT_PAVED and t.get("surface") is None and t.get("tracktype") is None
    vs = votes(t)
    why = max(vs, key=lambda x: x[1])[0] if vs else f"highway={h}"
    guess = not any(k in t for k in ("tracktype", "surface", "smoothness", "mtb:scale"))
    return band(value(t)), why, guess


def prohibited(t):
    """The tag that closes the way to a motorbike, or None when it is open, as Levels.prohibited in the app."""
    explicit_ok = t.get("motorcycle") in ALLOWED or t.get("motor_vehicle") in ALLOWED
    for k in ("motorcycle", "motor_vehicle", "vehicle", "access"):
        v = t.get(k)
        if v is None:
            continue
        if v in BANNED:
            if k in ("vehicle", "access") and explicit_ok:
                continue
            return f"{k}={v}"
    h = t.get("highway")
    if h in SINGLETRACK and not explicit_ok:
        return f"highway={h}"
    return None


# The barriers on the roads of the map (Il Maestro, 17 November): "chiuso" a closed lock, "aperto" an open one (a
# gate not known to be closed, not one sure to be open), "paletti" the bollards.
BARRIER_CLOSED = {
    "chain", "block", "jersey_barrier", "log", "rope", "stile", "turnstile", "full-height_turnstile",
    "kissing_gate", "wicket_gate", "motorcycle_barrier", "debris",
}
BARRIER_GATES = {"gate", "lift_gate", "swing_gate", "sliding_gate", "hampshire_gate"}
BARRIER_BOLLARDS = {"bollard", "cycle_barrier"}
BARRIER_KEPT = (
    "barrier", "locked", "access", "motor_vehicle", "motorcycle", "vehicle", "maxwidth:physical", "opening_hours",
)


def barrier_kind(t):
    """"chiuso", "aperto" or "paletti" for a barrier node, None for the barriers left off the map (kerbs, cattle grids,
    toll booths...)."""
    b = t.get("barrier")
    if b in BARRIER_CLOSED:
        return "aperto" if t.get("motorcycle") in ALLOWED else "chiuso"
    if b in BARRIER_GATES:
        return "chiuso" if t.get("locked") == "yes" or prohibited(t) else "aperto"
    if b in BARRIER_BOLLARDS:
        return "chiuso" if t.get("motorcycle") in BANNED else "paletti"
    return None


def barrier_feature(node_id, t, lon, lat):
    """The GeoJSON point of a barrier node, or None when it is not one the map shows."""
    kind = barrier_kind(t)
    if kind is None:
        return None
    props = {k: t[k] for k in BARRIER_KEPT if k in t}
    props["id"] = node_id
    props["kind"] = kind
    # Closed above open above bollards when they overlap, as the symbol-sort-key of the app.
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
    }


class Barriers(osmium.SimpleHandler):
    """The barrier nodes of a file (osmium tags-filter n/barrier of the roads), by id."""

    def __init__(self, found):
        super().__init__()
        self.found = found

    def node(self, n):
        if n.id in self.found or not n.location.valid():
            return
        f = barrier_feature(n.id, {tag.k: tag.v for tag in n.tags}, n.location.lon, n.location.lat)
        if f is not None:
            self.found[n.id] = f


def feature(way_id, t, coords):
    """The GeoJSON feature of a way, or None when it stays off the map (asphalt, not a road, too short)."""
    h = t.get("highway")
    if h is None or h in SKIPPED_HIGHWAYS or len(coords) < 2:
        return None
    if t.get("footway") in SKIPPED_FOOTWAYS or t.get("area") == "yes":
        return None
    lv, why, guess = level(t)
    if lv < 2:
        return None
    props = {k: t[k] for k in KEPT if k in t}
    props["id"] = way_id
    props["lvl"] = lv
    props["why"] = why
    if guess:
        props["guess"] = 1
    banned = prohibited(t)
    if banned:
        props["banned"] = banned
    # Paths appear one zoom later than tracks (a path with the clues of a road is a road): at zoom 11 they would only crowd the valleys. The tippecanoe filter
    # reads it (its own "tippecanoe": {"minzoom"} drops most lines in tippecanoe 2.49).
    props["minz"] = 12 if is_path(t) else 11
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


class Ways(osmium.SimpleHandler):
    def __init__(self, out, seen, barriers=None):
        super().__init__()
        self.out = out
        self.seen = seen
        self.count = 0
        # The barriers found by Barriers: those on a way of the map are kept, with "aperta" when the way is open.
        self.barriers = barriers or {}
        self.on_map = {}

    def way(self, w):
        # Neighbouring extracts overlap at their borders: a way is written once.
        if w.id in self.seen or "highway" not in w.tags:
            return
        t = {tag.k: tag.v for tag in w.tags}
        try:
            coords = [[round(n.lon, 6), round(n.lat, 6)] for n in w.nodes]
        except osmium.InvalidLocationError:
            coords = [[round(n.lon, 6), round(n.lat, 6)] for n in w.nodes if n.location.valid()]
        f = feature(w.id, t, coords)
        if f is None:
            return
        self.seen.add(w.id)
        if self.barriers:
            open_way = "banned" not in f["properties"]
            for n in w.nodes:
                if n.ref in self.barriers:
                    self.on_map[n.ref] = self.on_map.get(n.ref, False) or open_way
        self.out.write("\x1e" + json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.count += 1


def write_barriers(path, barriers, on_map):
    """The barriers on the ways of the map, "aperta": 1 on those on an open way (the app draws only these)."""
    count = 0
    with open(path, "w", encoding="utf-8") as out:
        for node_id, open_way in on_map.items():
            f = barriers[node_id]
            if open_way:
                f["properties"]["aperta"] = 1
            out.write("\x1e" + json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def main(argv):
    argv = list(argv)
    barriers_out = barriers_in = None
    if "--barriers" in argv:
        i = argv.index("--barriers")
        if len(argv) < i + 3:
            sys.exit(__doc__)
        barriers_out, barriers_in = argv[i + 1], argv[i + 2]
        del argv[i:i + 3]
    if len(argv) < 3:
        sys.exit(__doc__)
    barriers = {}
    if barriers_in:
        Barriers(barriers).apply_file(barriers_in)
        print(f"{barriers_in}: {len(barriers)} sbarre", flush=True)
    seen = set()
    on_map = {}
    with open(argv[1], "w", encoding="utf-8") as out:
        for path in argv[2:]:
            h = Ways(out, seen, barriers)
            h.apply_file(path, locations=True, idx="flex_mem")
            for k, v in h.on_map.items():
                on_map[k] = on_map.get(k, False) or v
            print(f"{path}: {h.count} vie", flush=True)
    print(f"totale: {len(seen)} vie")
    if barriers_out:
        n = write_barriers(barriers_out, barriers, on_map)
        print(f"sbarre sulle vie della mappa: {n}, aperte {sum(on_map.values())}")


if __name__ == "__main__":
    main(sys.argv)
