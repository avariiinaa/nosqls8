import streamlit as st
import folium
from streamlit_folium import st_folium
from neo4j import GraphDatabase
import json
import csv
import io

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password")


@st.cache_resource
def get_driver():
    return GraphDatabase.driver(URI, auth=AUTH)


@st.cache_data
def get_all_nodes_from_db():
    query = "MATCH (n:Intersection) RETURN n.osmid AS osmid, n.lat AS lat, n.lon AS lon, n.near_road AS near_road"
    d = get_driver()
    with d.session() as session:
        result = session.run(query)
        return [record.data() for record in result]


def get_route(driver, start_id, end_id):
    query = """
    MATCH p=shortestPath((start:Intersection {osmid: $start_id})-[:WALK*]-(end:Intersection {osmid: $end_id}))
    UNWIND nodes(p) AS n
    RETURN n.osmid AS osmid, n.lat AS lat, n.lon AS lon, n.near_road AS near_road
    """
    with driver.session() as session:
        result = session.run(query, start_id=int(start_id), end_id=int(end_id))
        return [record.data() for record in result]


def get_nearest_node(driver, lat, lon):
    query = """
    MATCH (n:Intersection)
    WITH n, (n.lat - $lat)^2 + (n.lon - $lon)^2 AS dist
    ORDER BY dist ASC
    LIMIT 1
    RETURN n.osmid AS osmid
    """
    with driver.session() as session:
        result = session.run(query, lat=lat, lon=lon)
        record = result.single()
        return record["osmid"] if record else None


# --- Функции для экспорта ---

def convert_to_csv(data):
    """Преобразует список словарей в CSV строку"""
    if not data:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()


def convert_to_json(data):
    """Преобразует список словарей в JSON строку"""
    return json.dumps(data, indent=2, ensure_ascii=False)


st.set_page_config(layout="wide")
st.title("Анализатор пешеходных маршрутов СПб")

driver = get_driver()

# Инициализация памяти (Session State)
if 'route_nodes' not in st.session_state:
    st.session_state.route_nodes = None
if 'start_input' not in st.session_state:
    st.session_state.start_input = "253160451"
if 'end_input' not in st.session_state:
    st.session_state.end_input = "26344585"

st.sidebar.header("Настройки маршрута")

# Поля ввода
start_node = st.sidebar.text_input("OSM ID старта", st.session_state.start_input)
end_node = st.sidebar.text_input("OSM ID финиша", st.session_state.end_input)

# Синхронизация
st.session_state.start_input = start_node
st.session_state.end_input = end_node

build_btn = st.sidebar.button("Построить маршрут")

st.sidebar.markdown("---")
show_all_nodes = st.sidebar.checkbox("Показать все узлы графа")

# Построение маршрута
if build_btn and start_node and end_node:
    st.session_state.route_nodes = get_route(driver, start_node, end_node)
    if not st.session_state.route_nodes:
        st.error("Маршрут не найден. Попробуйте выбрать другие узлы.")

# Рисуем карту
m = folium.Map(location=[59.9343, 30.3246], zoom_start=14, tiles="CartoDB positron")

# Отрисовка всех узлов
if show_all_nodes:
    all_nodes = get_all_nodes_from_db()
    for node in all_nodes:
        node_color = 'red' if node['near_road'] else 'green'
        folium.CircleMarker(
            location=[node['lat'], node['lon']],
            radius=1.5,
            color=node_color,
            fill=True,
            fill_color=node_color,
            fill_opacity=0.6,
            weight=0
        ).add_to(m)

# Отрисовка маршрута
if st.session_state.route_nodes:
    route_nodes = st.session_state.route_nodes
    total_nodes = len(route_nodes)
    near_road_nodes = sum(1 for n in route_nodes if n['near_road'])

    st.sidebar.markdown("### Анализ маршрута:")
    st.sidebar.write(f" Безопасные точки: {total_nodes - near_road_nodes}")
    st.sidebar.write(f" Рядом с дорогой (до 20м): {near_road_nodes}")
    if total_nodes > 0:
        st.sidebar.progress((total_nodes - near_road_nodes) / total_nodes, text="Удаленность от дорог")

    # === НОВЫЙ БЛОК: ЭКСПОРТ ===
    st.sidebar.markdown("### Экспорт маршрута")
    # Формируем данные для скачивания
    csv_data = convert_to_csv(route_nodes)
    json_data = convert_to_json(route_nodes)

    col_exp1, col_exp2 = st.sidebar.columns(2)

    col_exp1.download_button(
        label=" CSV",
        data=csv_data,
        file_name=f"route_{start_node}_{end_node}.csv",
        mime="text/csv"
    )
    col_exp2.download_button(
        label="JSON",
        data=json_data,
        file_name=f"route_{start_node}_{end_node}.json",
        mime="application/json"
    )
    # ==========================

    for i in range(len(route_nodes) - 1):
        n1 = route_nodes[i]
        n2 = route_nodes[i + 1]
        is_danger = n1['near_road'] or n2['near_road']

        folium.PolyLine(
            locations=[(n1['lat'], n1['lon']), (n2['lat'], n2['lon'])],
            color='red' if is_danger else 'green',
            weight=4 if is_danger else 3,
            opacity=0.8
        ).add_to(m)

    folium.Marker((route_nodes[0]['lat'], route_nodes[0]['lon']), popup="Старт", icon=folium.Icon(color='blue')).add_to(
        m)
    folium.Marker((route_nodes[-1]['lat'], route_nodes[-1]['lon']), popup="Финиш",
                  icon=folium.Icon(color='purple')).add_to(m)

# Вывод карты
map_data = st_folium(m, width=1200, height=600, returned_objects=["last_clicked"])

# Обработка кликов
if map_data and map_data.get("last_clicked"):
    click_lat = map_data["last_clicked"]["lat"]
    click_lon = map_data["last_clicked"]["lng"]

    nearest_osmid = get_nearest_node(driver, click_lat, click_lon)

    if nearest_osmid:
        st.sidebar.markdown("---")
        st.sidebar.success(f"Вы кликнули на карту.\n\nБлижайший узел: **{nearest_osmid}**")

        col1, col2 = st.sidebar.columns(2)
        if col1.button("Сделать СТАРТОМ"):
            st.session_state.start_input = str(nearest_osmid)
            st.rerun()
        if col2.button("Сделать ФИНИШЕМ"):
            st.session_state.end_input = str(nearest_osmid)
            st.rerun()