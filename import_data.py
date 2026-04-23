import osmnx as ox
from neo4j import GraphDatabase
import numpy as np
from scipy.spatial import cKDTree

# Настройки подключения к Neo4j
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"


def import_to_neo4j():
    print("Скачивание данных OSM (Центр СПб)...")
    point = (59.9343, 30.3246)

    # Скачиваем графы
    G_walk = ox.graph_from_point(point, dist=1500, network_type='walk')
    G_drive = ox.graph_from_point(point, dist=1500, network_type='drive')

    print("Анализ пространственной близости к автодорогам...")
    # Собираем координаты автомобильных узлов
    drive_coords = []
    for n, data in G_drive.nodes(data=True):
        # Конвертируем градусы в метры для геометрии СПб (широта ~60)
        # 1 градус широты ~ 111000 м, 1 градус долготы в СПб ~ 55500 м
        drive_coords.append([data['y'] * 111000, data['x'] * 55500])

    # Строим дерево быстрого поиска
    tree = cKDTree(drive_coords)

    near_road_set = set()
    walk_nodes_list = list(G_walk.nodes(data=True))

    walk_coords = []
    for n, data in walk_nodes_list:
        walk_coords.append([data['y'] * 111000, data['x'] * 55500])

    # Ищем ближайший автомобильный узел для каждого пешеходного
    dists, _ = tree.query(walk_coords, k=1)

    for i, (n, data) in enumerate(walk_nodes_list):
        if dists[i] < 20:  # Считаем узел "опасным", если дорога ближе 20 метров
            near_road_set.add(n)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        print("Очистка базы данных...")
        session.run("MATCH (n) DETACH DELETE n")

        print("Создание узлов (Intersection)...")
        nodes_list = []
        for node_id, data in G_walk.nodes(data=True):
            nodes_list.append({
                # Строго конвертируем типы в стандартные форматы Python!
                "osmid": int(node_id),
                "lat": float(data['y']),
                "lon": float(data['x']),
                "near_road": bool(node_id in near_road_set)
            })

        session.run("""
            UNWIND $nodes AS node
            CREATE (n:Intersection {
                osmid: node.osmid, lat: node.lat, lon: node.lon, near_road: node.near_road
            })
        """, nodes=nodes_list)

        print("Создание индексов...")
        # IF NOT EXISTS убережет от ошибок при повторном запуске
        session.run("CREATE INDEX IF NOT EXISTS FOR (n:Intersection) ON (n.osmid)")

        print("Создание связей (тропинок)...")
        edges_list = []
        for u, v, data in G_walk.edges(data=True):
            edges_list.append({
                "u": int(u), "v": int(v), "length": float(data.get('length', 0))
            })

        # Обратите внимание на стрелочку -> перед (b). Она обязательна для MERGE!
        session.run("""
            UNWIND $edges AS edge
            MATCH (a:Intersection {osmid: edge.u})
            MATCH (b:Intersection {osmid: edge.v})
            MERGE (a)-[:WALK {length: edge.length}]->(b)
        """, edges=edges_list)

    driver.close()
    print("Импорт завершен!")


if __name__ == "__main__":
    import_to_neo4j()