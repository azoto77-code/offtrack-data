#!/usr/bin/env python3
"""Writes the unpaved roads and paths of OpenStreetMap files as GeoJSON lines, with their difficulty level, for the
OffTrack difficulty map.

Each way that is not plain asphalt becomes one feature with its level 1-5 ("lvl"), the tag that decided it ("why"),
"guess" when the level is a guess for lack of tags, "banned" with the tag that closes it to motorbikes, "minz" the
first zoom it is drawn at, and the OpenStreetMap tags the app shows when a road is tapped. The output is GeoJSON text sequences for tippecanoe.

    difficulty_layer.py OUT.geojsonseq IN.osm.pbf [IN.osm.pbf ...]

The levels must stay the same as Levels.kt in the app (core/.../difficulty/Levels.kt): change both together.
"""
import json
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


def level(t):
    """(level, reason, guess) of a way from its tags, as Levels.of in the app."""
    h = t.get("highway", "")
    s = t.get("surface")
    tt = t.get("tracktype")
    sm = t.get("smoothness")
    guess = False
    if h in SINGLETRACK:
        lv, why = (1 if s in PAVED else 5), f"highway={h}"
    elif s in PAVED and tt not in ("grade3", "grade4", "grade5"):
        lv, why = 1, f"surface={s}"
    elif tt is not None:
        lv = {"grade1": 1 if s in PAVED else 2, "grade2": 2, "grade3": 3, "grade4": 4, "grade5": 5}.get(tt, 3)
        why = f"tracktype={tt}"
    elif s in EASY_UNPAVED:
        lv, why = 2, f"surface={s}"
    elif s in MID_UNPAVED:
        lv, why = 3, f"surface={s}"
    elif s in HARD_SURF:
        lv, why = 4, f"surface={s}"
    elif h == "track":
        lv, why, guess = 3, "highway=track", True
    elif h in ROAD_DEFAULT_PAVED:
        lv, why, guess = 1, f"highway={h}", s is None
    else:
        lv, why, guess = 3, f"highway={h}", True
    if s in HARD_SURF and lv < 4:
        lv, why = 4, f"surface={s}"
    sm_min = SMOOTHNESS_MIN.get(sm)
    if sm_min is not None and sm_min > lv and not (lv == 1 and sm == "intermediate"):
        lv, why = sm_min, f"smoothness={sm}"
    return lv, why, guess


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
    # Paths appear one zoom later than tracks: at zoom 11 they would only crowd the valleys. The tippecanoe filter
    # reads it (its own "tippecanoe": {"minzoom"} drops most lines in tippecanoe 2.49).
    props["minz"] = 12 if h in SINGLETRACK else 11
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


class Ways(osmium.SimpleHandler):
    def __init__(self, out, seen):
        super().__init__()
        self.out = out
        self.seen = seen
        self.count = 0

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
        self.out.write("\x1e" + json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.count += 1


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    seen = set()
    with open(argv[1], "w", encoding="utf-8") as out:
        for path in argv[2:]:
            h = Ways(out, seen)
            h.apply_file(path, locations=True, idx="flex_mem")
            print(f"{path}: {h.count} vie", flush=True)
    print(f"totale: {len(seen)} vie")


if __name__ == "__main__":
    main(sys.argv)
