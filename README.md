# Iloilo Route Optimizer

A Streamlit app for route optimization in Iloilo City. It compares four search
algorithms (BFS, Greedy best-first, Dijkstra, A*), implemented from scratch,
against Mapbox routing on the OpenStreetMap road network.

Case study for ITPD 6 - Artificial Intelligence 1 (Search Algorithms: route optimization).

Live demo: https://iloilo-route-optimizer.streamlit.app/

## What it does

- Search any place in Iloilo City (about 4,500 places from OpenStreetMap, with fuzzy type-ahead) or click the map to set a start and drop-off.
- Shows the Mapbox route, alternatives and turn-by-turn directions on the map.
- Runs our own BFS, Greedy, Dijkstra and A* on the real road graph and compares distance, time, nodes expanded and runtime, with Mapbox as the baseline.
- `benchmark.py` repeats the comparison on many random start/drop-off pairs and saves CSV tables and a chart for the paper.

## Run locally

1. Install Python 3.10+ and the app dependencies:

       pip install -r requirements.txt

2. Add your Mapbox public token (starts with `pk.`). Create `.streamlit/secrets.toml`:

       MAPBOX_TOKEN = "pk.your_token_here"

   (Or set the `MAPBOX_TOKEN` environment variable. Never commit the token.)

3. The data files `iloilo_places.json` and `iloilo_graph_*.json` are included in the repository. To rebuild them (needs internet):

       pip install -r requirements-dev.txt
       python build_places_dataset.py     # search suggestions
       python build_graph.py              # road graphs (drive, bike, walk)

   Optional: add your own places in `manual_places.csv` (columns: name,lat,lon,category,aliases) before running `build_places_dataset.py`.

4. Start the app:

       streamlit run app.py

## Run the benchmark

    pip install -r requirements-dev.txt
    python benchmark.py                       # 40 random pairs, shortest distance, drive graph
    python benchmark.py --pairs 50 --weight time
    python benchmark.py --kind walk
    python benchmark.py --mapbox              # also compare with Mapbox (needs MAPBOX_TOKEN env var)

Outputs: `benchmark_results.csv`, `benchmark_summary.csv`, `benchmark_chart.png`.

## Deploy (Streamlit Community Cloud)

1. Push this repository to GitHub (the token file `.streamlit/secrets.toml` is ignored by `.gitignore`).
2. Go to https://share.streamlit.io, sign in with GitHub, choose **Create app**, and select this repository, branch `main`, main file `app.py`.
3. Under **Advanced settings**, pick Python 3.12 and paste your token into **Secrets**:

       MAPBOX_TOKEN = "pk.your_token_here"

4. Deploy. In your Mapbox account, restrict the token to the app's URL.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit app (search, map, Mapbox routes, algorithm comparison panel) |
| `algorithms.py` | Own implementations of BFS, Greedy best-first, Dijkstra and A* with node counters |
| `build_graph.py` | Downloads the Iloilo road network (OSMnx) and saves it as JSON graphs |
| `build_places_dataset.py` | Downloads named places from OpenStreetMap for search suggestions |
| `benchmark.py` | Runs the algorithms on many random pairs and saves results for the paper |
| `.streamlit/config.toml` | Streamlit theme (white and #023e8a) |
| `requirements.txt` | Packages needed to run the app |
| `requirements-dev.txt` | Extra packages to rebuild data and run the benchmark |

## Notes and limitations

- Map data from OpenStreetMap contributors; map tiles and routing baseline from Mapbox.
- Mapbox uses live traffic and turn restrictions; the graph searches do not, so small differences are expected.
- Dijkstra and A* are optimal for the chosen cost (distance or time). BFS minimizes road segments and Greedy follows the heuristic only, so neither guarantees the best route.