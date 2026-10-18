import json
import math
import os
from pathlib import Path

import folium
import requests
import streamlit as st
from folium import DivIcon
from rapidfuzz import fuzz, process
from streamlit_folium import st_folium
from streamlit_searchbox import st_searchbox
import pandas as pd

from algorithms import compare_all, load_graph

st.set_page_config(page_title="Iloilo Route Optimizer", layout="wide")

NAVY = "#023e8a"
WHITE = "#ffffff"
TINT = "#E6EEF9"  # pale tint of the navy, used as the background of the input boxes

HERE = Path(__file__).parent
PLACES_FILE = HERE / "iloilo_places.json"

DEFAULT_START = (10.7202, 122.5621)  # Near Jaro Plaza
DEFAULT_GOAL = (10.6977, 122.5458)   # Near SM City Iloilo
ILOILO_BBOX = "122.49,10.65,122.62,10.77"  # west,south,east,north (Mapbox order)
ILOILO_CENTER = "122.5621,10.7020"         # lon,lat used to rank nearby results

MODES = {
    "Car": "mapbox/driving",
    "Motorbike": "mapbox/driving",
    "Bicycle": "mapbox/cycling",
    "Walking": "mapbox/walking",
}

# ---------------------------------------------------------------------------
# Styling: white + navy (map is NOT restyled)
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    html, body, .stApp, [data-testid="stHeader"] {{ background: {WHITE}; }}
    .stApp, .stApp p, .stApp label, .stApp span, .stApp li,
    .stApp h1, .stApp h2, .stApp h3, .stApp h4,
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"],
    [data-testid="stCaptionContainer"] {{ color: {NAVY}; }}
    .stApp h1 {{ font-weight: 800; letter-spacing: -0.5px; }}
    .stApp .stButton > button, .stApp [data-testid^="stBaseButton"] {{
        background-color: {NAVY} !important; color: {WHITE} !important;
        border: 1px solid {NAVY} !important; border-radius: 8px !important;
        width: 100%; outline: none !important; box-shadow: none !important;
        transition: background-color 0.15s, color 0.15s;
    }}
    .stApp .stButton > button *, .stApp [data-testid^="stBaseButton"] * {{
        color: inherit !important;
    }}
    .stApp .stButton > button:hover, .stApp .stButton > button:active,
    .stApp [data-testid^="stBaseButton"]:hover, .stApp [data-testid^="stBaseButton"]:active {{
        background-color: {WHITE} !important; color: {NAVY} !important;
        border: 1px solid {NAVY} !important;
    }}
    [data-testid="stMetric"] {{
        border: 1px solid {NAVY}; border-radius: 10px; padding: 10px 16px;
    }}
    [data-testid="stExpander"] {{ border: 1px solid {NAVY}; border-radius: 10px; }}
    [data-baseweb="select"] > div {{
        background-color: {TINT}; border: 1px solid {NAVY}; border-radius: 8px;
    }}
    div[role="radiogroup"] {{
        background-color: {TINT}; border: 1px solid {NAVY}; border-radius: 8px;
        padding: 8px 14px; width: fit-content;
    }}
    .route-box {{
        border: 1px solid {NAVY}; border-radius: 10px; padding: 10px 16px;
        color: {NAVY}; font-size: 0.95rem; line-height: 1.35;
    }}
    .route-box b {{ font-size: 0.75rem; letter-spacing: 1px; text-transform: uppercase; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Mapbox token: read from Streamlit secrets or an environment variable.
# NEVER paste the token directly into this file.
# ---------------------------------------------------------------------------
def get_mapbox_token():
    try:
        token = st.secrets["MAPBOX_TOKEN"]
        if token:
            return token
    except Exception:
        pass
    return os.environ.get("MAPBOX_TOKEN", "")


MAPBOX_TOKEN = get_mapbox_token()
if not MAPBOX_TOKEN:
    st.error(
        "Mapbox token not found. Create `.streamlit/secrets.toml` with a line like "
        "`MAPBOX_TOKEN = \"pk.your_new_token\"` (or set the MAPBOX_TOKEN environment variable)."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Local places dataset (built by build_places_dataset.py)
# ---------------------------------------------------------------------------
FALLBACK_PLACES = [
    {"name": n, "label": "", "category": "landmark", "lat": la, "lon": lo, "aliases": []}
    for n, la, lo in [
        ("Jaro Plaza / Jaro Cathedral", 10.7202, 122.5621),
        ("SM City Iloilo, Mandurriao", 10.7133, 122.5454),
        ("Iloilo City Proper (Plaza Libertad)", 10.6967, 122.5681),
        ("Molo Church / Plaza Molo", 10.6970, 122.5426),
        ("La Paz Public Market", 10.7123, 122.5731),
    ]
]


@st.cache_data
def load_places():
    if PLACES_FILE.exists():
        with open(PLACES_FILE, encoding="utf-8") as f:
            return json.load(f), True
    return FALLBACK_PLACES, False


PLACES, DATASET_OK = load_places()


@st.cache_data
def build_index():
    """One searchable string per place: name + aliases + address label."""
    texts = []
    for p in PLACES:
        parts = [p["name"]] + p.get("aliases", []) + [p.get("label", "")]
        texts.append(" ".join(x for x in parts if x).lower())
    return texts


SEARCH_TEXTS = build_index()


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_local_place(lat, lon, max_m=120):
    best, best_d = None, max_m
    for p in PLACES:
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if d < best_d:
            best, best_d = p, d
    return best


# ---------------------------------------------------------------------------
# Online fallbacks (only used when the local dataset has no good match)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def mapbox_geocode(query, token):
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{requests.utils.quote(query)}.json"
    params = {
        "access_token": token,
        "country": "ph",
        "bbox": ILOILO_BBOX,
        "proximity": ILOILO_CENTER,
        "autocomplete": "true",
        "limit": 5,
    }
    try:
        data = requests.get(url, params=params, timeout=4).json()
        return [
            (f["place_name"], f["center"][1], f["center"][0])  # name, lat, lon
            for f in data.get("features", [])
        ]
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def reverse_geocode(lat, lon):
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    )
    headers = {"User-Agent": "IloiloRouteOptimizerCaseStudy/1.0"}
    try:
        data = requests.get(url, headers=headers, timeout=3).json()
        if "display_name" in data:
            return data["display_name"]
    except Exception:
        pass
    return "Exact street coordinate (no named place at this point)"


def name_for_point(lat, lon):
    place = nearest_local_place(lat, lon)
    if place:
        return place["name"]
    return reverse_geocode(round(lat, 5), round(lon, 5))


# ---------------------------------------------------------------------------
# Type-ahead search function used by the search boxes
# ---------------------------------------------------------------------------
def search_places(term):
    term = (term or "").strip().lower()
    if len(term) < 2:
        return []

    options = []

    # 1) local dataset, fuzzy matched (instant, offline)
    matches = process.extract(
        term, SEARCH_TEXTS, scorer=fuzz.WRatio, limit=8, score_cutoff=62
    )
    for _text, _score, idx in matches:
        p = PLACES[idx]
        label = p["name"]
        extra = " · ".join(x for x in (p.get("category", "").replace("_", " "), p.get("label", "")) if x)
        if extra:
            label = f"{label}  ({extra})"
        options.append((label, f"L|{idx}"))

    # 2) online fallback if the local data barely matches
    if len(options) < 3 and len(term) >= 3:
        for name, lat, lon in mapbox_geocode(term, MAPBOX_TOKEN):
            options.append((f"Online: {name}", f"M|{lat}|{lon}|{name}"))

    return options


def resolve_pick(value):
    """Turn a search-box value back into (lat, lon, name)."""
    if value.startswith("L|"):
        p = PLACES[int(value.split("|", 1)[1])]
        return p["lat"], p["lon"], p["name"]
    if value.startswith("M|"):
        _, lat, lon, name = value.split("|", 3)
        return float(lat), float(lon), name
    return None


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
defaults = {
    "start_coords": DEFAULT_START,
    "goal_coords": DEFAULT_GOAL,
    "start_name": "Jaro District Area",
    "goal_name": "Mandurriao / SM City Area",
    "last_start_pick": None,
    "last_goal_pick": None,
    "last_click": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Styling for the two search boxes (they render inside their own frame, so page CSS cannot reach them)
SEARCHBOX_STYLE = {
    "searchbox": {
        "control": {
            "backgroundColor": TINT,
            "border": f"1px solid {NAVY}",
            "borderRadius": "8px",
            "&:hover": {"border": f"1px solid {NAVY}"},
        },
    }
}

st.title("Iloilo Route Optimizer")
st.caption("Search a place or click the map to set the start and drop-off.")

# ---------------------------------------------------------------------------
# Controls (centre of the page)
# ---------------------------------------------------------------------------
s_col, g_col = st.columns(2)

with s_col:
    start_pick = st_searchbox(
        search_places, label="Start", placeholder="Type a place, e.g. Jaro, SM, CPU",
        key="start_searchbox", style_overrides=SEARCHBOX_STYLE,
    )
# Only apply a pick when it is NEW, so it never overwrites later map clicks.
if start_pick and start_pick != st.session_state.last_start_pick:
    st.session_state.last_start_pick = start_pick
    resolved = resolve_pick(start_pick)
    if resolved:
        st.session_state.start_coords = (resolved[0], resolved[1])
        st.session_state.start_name = resolved[2]
        st.rerun()

with g_col:
    goal_pick = st_searchbox(
        search_places, label="Drop-off", placeholder="Type a place, e.g. Megaworld, UPV",
        key="goal_searchbox", style_overrides=SEARCHBOX_STYLE,
    )
if goal_pick and goal_pick != st.session_state.last_goal_pick:
    st.session_state.last_goal_pick = goal_pick
    resolved = resolve_pick(goal_pick)
    if resolved:
        st.session_state.goal_coords = (resolved[0], resolved[1])
        st.session_state.goal_name = resolved[2]
        st.rerun()

o1, o2, o3 = st.columns(3)
mode = o1.selectbox("Transport", list(MODES.keys()))
mapbox_profile = MODES[mode]
click_mode = o2.radio("Map click sets", ["Start", "Drop-off"], horizontal=True)
o3.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
if o3.button("Reset"):
    st.session_state.start_coords = DEFAULT_START
    st.session_state.goal_coords = DEFAULT_GOAL
    st.session_state.start_name = "Jaro District Area"
    st.session_state.goal_name = "Mandurriao / SM City Area"
    st.rerun()

if DATASET_OK:
    st.caption(f"{len(PLACES):,} places in local search")
else:
    st.caption("iloilo_places.json not found. Run build_places_dataset.py for the full place list.")


# ---------------------------------------------------------------------------
# Routing (cached so reruns don't re-hit Mapbox every time)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_mapbox_alternative_routes(start, goal, mode, profile, token):
    exclude_param = "&exclude=ferry" if mode == "Car" else ""
    url = (
        f"https://api.mapbox.com/directions/v5/{profile}/"
        f"{start[1]},{start[0]};{goal[1]},{goal[0]}"
        f"?access_token={token}&geometries=geojson&steps=true&alternatives=true{exclude_param}"
    )

    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if data.get("code") != "Ok":
            return []

        routes_processed = []
        for idx, route in enumerate(data["routes"]):
            path_coords = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
            distance_km = route["distance"] / 1000.0
            base_duration_min = route["duration"] / 60.0

            if mode == "Walking":
                duration_min = (distance_km / 4.5) * 60
            elif mode == "Bicycle":
                duration_min = (distance_km / 15.0) * 60
            elif mode == "Motorbike":
                duration_min = base_duration_min * 0.85
            else:
                duration_min = base_duration_min

            steps_list, step_coords = [], []
            if idx == 0:
                legs = route.get("legs", [])
                if legs:
                    for step in legs[0].get("steps", []):
                        maneuver = step.get("maneuver", {})
                        m_loc = maneuver.get("location")
                        if m_loc:
                            step_coords.append([m_loc[1], m_loc[0]])

                        m_type = maneuver.get("type", "proceed")
                        modifier = maneuver.get("modifier", "")
                        street_name = step.get("name", "")
                        distance = step.get("distance", 0)

                        action = f"{m_type.capitalize()} {modifier}".strip()
                        if street_name:
                            steps_list.append(f"{action} onto **{street_name}** ({distance:.0f}m)")
                        else:
                            steps_list.append(f"{action} ({distance:.0f}m)")

            routes_processed.append({
                "path": path_coords,
                "distance": distance_km,
                "duration": duration_min,
                "steps": steps_list,
                "step_coords": step_coords,
            })
        return routes_processed
    except Exception:
        return []


all_routes = get_mapbox_alternative_routes(
    st.session_state.start_coords,
    st.session_state.goal_coords,
    mode,
    mapbox_profile,
    MAPBOX_TOKEN,
)

primary_distance = all_routes[0]["distance"] if all_routes else 0
primary_duration = all_routes[0]["duration"] if all_routes else 0
primary_steps = all_routes[0]["steps"] if all_routes else []
primary_step_coords = all_routes[0]["step_coords"] if all_routes else []

# ---------------------------------------------------------------------------
# Summary row
# ---------------------------------------------------------------------------
a_col, b_col = st.columns(2)
a_col.markdown(f'<div class="route-box"><b>Start</b><br>{st.session_state.start_name}</div>', unsafe_allow_html=True)
b_col.markdown(f'<div class="route-box"><b>Drop-off</b><br>{st.session_state.goal_name}</div>', unsafe_allow_html=True)

st.write("")
col1, col2, col3 = st.columns(3)
col1.metric("Distance", f"{primary_distance:.2f} km" if primary_distance else "N/A")
col2.metric("Time", f"{primary_duration:.0f} min" if primary_duration else "N/A")
col3.metric("Route options", f"{len(all_routes)}")

if not all_routes:
    st.markdown(
        '<div class="route-box">Could not compute a route between these two points.</div>',
        unsafe_allow_html=True,
    )

if primary_steps:
    with st.expander("Directions", expanded=False):
        for i, step in enumerate(primary_steps, 1):
            st.markdown(f"{i}. {step}")

# ---------------------------------------------------------------------------
# Map (unchanged from the original)
# ---------------------------------------------------------------------------
mapbox_style = "mapbox/streets-v12"
tile_url = f"https://api.mapbox.com/styles/v1/{mapbox_style}/tiles/256/{{z}}/{{x}}/{{y}}@2x?access_token={MAPBOX_TOKEN}"
mapbox_attr = '&copy; <a href="https://www.mapbox.com/">Mapbox</a>'

m = folium.Map(
    location=st.session_state.start_coords,
    zoom_start=13,
    tiles=tile_url,
    attr=mapbox_attr
)

# Add Start and Goal Markers
folium.Marker(
    st.session_state.start_coords,
    popup=f"Start Depot: {st.session_state.start_name}",
    icon=folium.Icon(color="green", icon="play")
).add_to(m)

folium.Marker(
    st.session_state.goal_coords,
    popup=f"Drop-off: {st.session_state.goal_name}",
    icon=folium.Icon(color="red", icon="stop")
).add_to(m)

# Draw ALL alternative routes on the map
if all_routes:
    for idx, r in enumerate(all_routes):
        if idx == 0:
            folium.PolyLine(
                r["path"],
                color="#2563eb",
                weight=7,
                opacity=0.9,
                tooltip=f"Primary Route: {r['distance']:.2f} km ({r['duration']:.1f} mins)"
            ).add_to(m)
        else:
            folium.PolyLine(
                r["path"],
                color="#64748b",
                weight=4,
                opacity=0.6,
                dash_array="5, 5",
                tooltip=f"Alternative Route {idx}: {r['distance']:.2f} km ({r['duration']:.1f} mins)"
            ).add_to(m)

    # Add Numbered Turn Markers along the primary route
    for i, coord in enumerate(primary_step_coords, 1):
        step_text = primary_steps[i-1] if i-1 < len(primary_steps) else f"Step {i}"

        numbered_icon = DivIcon(
            icon_size=(24, 24),
            icon_anchor=(12, 12),
            html=f'<div style="background-color: #2563eb; color: white; border-radius: 50%; text-align: center; font-weight: bold; font-size: 11px; line-height: 24px; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">{i}</div>'
        )

        folium.Marker(
            location=coord,
            icon=numbered_icon,
            popup=f"<b>Turn {i}</b><br>{step_text}"
        ).add_to(m)

# Render Map and capture clicks
map_data = st_folium(m, width=1100, height=520, returned_objects=["last_clicked"], key="iloilo_mapbox_map")

# Handle map clicks. Only act on a NEW click (stops loops / overwriting search picks).
if map_data and map_data.get("last_clicked"):
    clicked_lat = map_data["last_clicked"]["lat"]
    clicked_lon = map_data["last_clicked"]["lng"]
    click_id = (round(clicked_lat, 6), round(clicked_lon, 6))

    if click_id != st.session_state.last_click:
        st.session_state.last_click = click_id
        place_name = name_for_point(clicked_lat, clicked_lon)

        if click_mode == "Start":
            st.session_state.start_coords = (clicked_lat, clicked_lon)
            st.session_state.start_name = place_name
        else:
            st.session_state.goal_coords = (clicked_lat, clicked_lon)
            st.session_state.goal_name = place_name
        st.rerun()


# ---------------------------------------------------------------------------
# Algorithm comparison: our own BFS / Greedy / Dijkstra / A* on the OSM road graph
# (placed after the map, so the map itself is unchanged)
# ---------------------------------------------------------------------------
GRAPH_KIND = {"Car": "drive", "Motorbike": "drive", "Bicycle": "bike", "Walking": "walk"}
TIME_FACTOR = {"Motorbike": 0.85}  # same adjustment used for the Mapbox time above


@st.cache_resource(show_spinner=False)
def get_graph(kind):
    path = HERE / f"iloilo_graph_{kind}.json"
    return load_graph(path) if path.exists() else None


@st.cache_data(show_spinner=False)
def run_comparison(start, goal, kind, weight):
    g = get_graph(kind)
    s_node, s_off = g.nearest_node(*start)
    t_node, t_off = g.nearest_node(*goal)
    results = compare_all(g, s_node, t_node, weight)
    return {name: r.as_dict() for name, r in results.items()}, s_off, t_off


st.markdown("---")
st.subheader("Algorithm comparison")
st.caption(
    "BFS, Greedy best-first, Dijkstra and A* are our own implementations, run on the OpenStreetMap "
    "road graph. Mapbox is shown only as the baseline."
)

weight_label = st.radio("Optimize for", ["Shortest distance", "Fastest time"], horizontal=True, key="cmp_weight")
weight_key = "distance" if weight_label == "Shortest distance" else "time"
graph_kind = GRAPH_KIND[mode]

if get_graph(graph_kind) is None:
    st.caption(
        f"Road graph not found. Run `python build_graph.py {graph_kind}` once to create "
        f"iloilo_graph_{graph_kind}.json."
    )
else:
    with st.spinner("Running search algorithms..."):
        res, s_off, t_off = run_comparison(
            st.session_state.start_coords, st.session_state.goal_coords, graph_kind, weight_key
        )

    factor = TIME_FACTOR.get(mode, 1.0)
    rows, node_counts = [], {}
    for name in ("BFS", "Greedy best-first", "Dijkstra", "A*"):
        r = res[name]
        if not r["found"]:
            rows.append({"Algorithm": name, "Distance (km)": "no path", "Time (min)": "n/a",
                         "Nodes expanded": f"{r['expanded']:,}", "Runtime (ms)": f"{r['runtime_ms']:.1f}",
                         "Distance gap vs Mapbox": "n/a"})
            continue
        km = r["distance_m"] / 1000.0
        gap = f"{(km - primary_distance) / primary_distance * 100:+.1f}%" if primary_distance else "n/a"
        rows.append({
            "Algorithm": name,
            "Distance (km)": f"{km:.2f}",
            "Time (min)": f"{r['time_s'] / 60.0 * factor:.1f}",
            "Nodes expanded": f"{r['expanded']:,}",
            "Runtime (ms)": f"{r['runtime_ms']:.1f}",
            "Distance gap vs Mapbox": gap,
        })
        node_counts[name] = r["expanded"]
    if primary_distance:
        rows.append({
            "Algorithm": "Mapbox (baseline)",
            "Distance (km)": f"{primary_distance:.2f}",
            "Time (min)": f"{primary_duration:.1f}",
            "Nodes expanded": "n/a",
            "Runtime (ms)": "n/a",
            "Distance gap vs Mapbox": "n/a",
        })

    st.table(pd.DataFrame(rows).set_index("Algorithm"))
    if node_counts:
        st.bar_chart(pd.DataFrame({"Nodes expanded": node_counts}), color=NAVY)
    st.caption(
        f"Start and drop-off were snapped to the nearest road node ({s_off:.0f} m and {t_off:.0f} m away). "
        "Dijkstra and A* always find the best route for the chosen goal; BFS and Greedy do not. "
        "Mapbox uses live traffic and turn rules that these graph searches do not, so small gaps are expected."
    )