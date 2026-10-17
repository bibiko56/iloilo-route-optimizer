import heapq
import time
import folium

class Node:
    def __init__(self, x, y, cost=0, heuristic=0, parent=None):
        self.x = x
        self.y = y
        self.cost = cost
        self.heuristic = heuristic
        self.total_cost = cost + heuristic
        self.parent = parent

    def __lt__(self, other):
        return self.total_cost < other.total_cost

def manhattan_distance(x1, y1, x2, y2):
    return abs(x1 - x2) + abs(y1 - y2)

def a_star_search(grid, start, goal):
    start_time = time.time()
    rows, cols = len(grid), len(grid[0])
    start_node = Node(start[0], start[1], 0, manhattan_distance(start[0], start[1], goal[0], goal[1]))
    
    open_set = []
    heapq.heappush(open_set, start_node)
    g_costs = {start: 0}
    closed_set = set()
    nodes_explored = 0

    while open_set:
        current = heapq.heappop(open_set)
        current_pos = (current.x, current.y)

        if current_pos == goal:
            path = []
            temp = current
            while temp:
                path.append((temp.x, temp.y))
                temp = temp.parent
            end_time = time.time()
            return path[::-1], nodes_explored, (end_time - start_time) * 1000, current.cost

        if current_pos in closed_set:
            continue
        closed_set.add(current_pos)
        nodes_explored += 1

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = current.x + dx, current.y + dy
            neighbor_pos = (nx, ny)

            if 0 <= nx < rows and 0 <= ny < cols and grid[nx][ny] == 1:
                continue

            if 0 <= nx < rows and 0 <= ny < cols:
                new_cost = current.cost + 1
                if neighbor_pos not in g_costs or new_cost < g_costs[neighbor_pos]:
                    g_costs[neighbor_pos] = new_cost
                    h = manhattan_distance(nx, ny, goal[0], goal[1])
                    neighbor_node = Node(nx, ny, new_cost, h, current)
                    heapq.heappush(open_set, neighbor_node)

    return None, nodes_explored, 0, 0

# 10x10 grid representing a mapped zone in Iloilo City
grid = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 0, 1, 1, 0, 1, 1, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
    [0, 1, 1, 1, 0, 1, 0, 1, 1, 0],
    [0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
    [1, 1, 0, 1, 1, 1, 0, 1, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
]

start_depot = (0, 0)
delivery_goal = (9, 9)

path, nodes_explored, exec_time, total_distance = a_star_search(grid, start_depot, delivery_goal)

print(f"Path Found! Nodes Explored: {nodes_explored}, Execution Time: {exec_time:.2f} ms")

# --- GENERATE INTERACTIVE ILOILO MAP ---
# Center of Iloilo City coordinates
iloilo_center = [10.6928, 122.5644]
m = folium.Map(location=iloilo_center, zoom_start=14, tiles="OpenStreetMap")

# Base geographic anchor in Iloilo (e.g., near SM City Iloilo / Mandurriao area)
base_lat, base_lon = 10.7100, 122.5400
lat_step = 0.0015
lon_step = 0.0015

# Convert grid path to real GPS coordinates for the map
latlon_path = []
if path:
    for px, py in path:
        lat = base_lat - (px * lat_step)
        lon = base_lon + (py * lon_step)
        latlon_path.append([lat, lon])

    # Draw the optimized path on the actual map
    folium.PolyLine(latlon_path, color="blue", weight=5, opacity=0.8, popup="Optimized Delivery Route").add_to(m)
    
    # Add Start Marker (Depot)
    folium.Marker(
        location=latlon_path[0],
        popup="Depot: SM City Iloilo Hub",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(m)

    # Add End Marker (Drop-off)
    folium.Marker(
        location=latlon_path[-1],
        popup="Drop-off: Jaro Delivery Point",
        icon=folium.Icon(color="red", icon="stop")
    ).add_to(m)

# Save map as an interactive HTML file
map_filename = "iloilo_delivery_map.html"
m.save(map_filename)
print(f"Interactive map successfully generated and saved as '{map_filename}'!")