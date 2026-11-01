import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import os

import routing

# Устанавливаем широкую конфигурацию страницы, чтобы карта занимала максимум места
st.set_page_config(layout="wide", page_title="ГИС Мониторинг")

st.title("🗺️ Геоинформационная карта объектов и маршрутов")
st.caption("Карта размещения терминалов и маршрутов передвижения пунктов с поддержкой масштабирования, слоев и интерактивных подсказок")

# =============================================================================
# ЗАГРУЗКА РЕАЛЬНЫХ ДАННЫХ ИЗ ФАЙЛА
# =============================================================================
@st.cache_data
def load_terminal_data():
    file_name = "Координаты.xlsx"
    if os.path.exists(file_name):
        try:
            df = pd.read_excel(file_name)
            # Переименовываем колонки под стандарт pydeck (английские идентификаторы)
            df = df.rename(columns={"Долгота": "lon", "Широта": "lat"})
            
            # Добавляем служебные атрибуты для корректной работы всплывающих подсказок (tooltip)
            df["type"] = "Терминал"
            df["name"] = [f"Терминал №{i+1}" for i in range(len(df))]
            df["population"] = 0  # Для совместимости, если используются слои населения
            return df
        except Exception as e:
            st.error(f"Ошибка при чтении файла {file_name}: {e}")
            return pd.DataFrame(columns=["lon", "lat", "type", "name", "population"])
    else:
        st.error(f"Файл {file_name} не найден в директории приложения!")
        return pd.DataFrame(columns=["lon", "lat", "type", "name", "population"])

# =============================================================================
# ГЕНЕРАЦИЯ ВИРТУАЛЬНЫХ ДАННЫХ ДЛЯ КОНТЕКСТА (НАСЕЛЕННЫЕ ПУНКТЫ)
# =============================================================================
@st.cache_data
def generate_demo_data(center_lat, center_lon):
    np.random.seed(42)
    n_settlements = 150
    df_settlements = pd.DataFrame({
        'lat': np.random.normal(center_lat, 0.4, n_settlements),
        'lon': np.random.normal(center_lon, 0.6, n_settlements),
        'name': [f"Населенный пункт №{i}" for i in range(n_settlements)],
        'population': np.random.randint(100, 25000, n_settlements),
        'type': 'Населенный пункт'
    })
    return df_settlements

# Загружаем реальные терминалы
df_terminals = load_terminal_data()

# Определяем базовый центр карты на основе реальных данных (или дефолт, если файл пуст)
if not df_terminals.empty:
    base_lat = float(df_terminals["lat"].median())
    base_lon = float(df_terminals["lon"].median())
    default_zoom = 10.0  # Крупный масштаб для детального просмотра кластера
else:
    base_lat, base_lon = 56.0, 86.0
    default_zoom = 5.0

df_np = generate_demo_data(base_lat, base_lon)

# =============================================================================
# БОКОВАЯ ПАНЕЛЬ: УПРАВЛЕНИЕ СЛОЯМИ И СТАТИСТИКА
# =============================================================================
st.sidebar.header("🗺️ Управление слоями карты")

# Переключатели для отображения слоев на основе реальных терминалов
show_terminals = st.sidebar.checkbox("🟢 Реальные данные: Терминалы (Маркеры)", value=True)
show_method_2  = st.sidebar.checkbox("🔵 Способ 2: Радиусы доступности терминалов", value=False)
show_method_3  = st.sidebar.checkbox("🔥 Способ 3: Тепловая карта (Плотность)", value=False)
show_demo_np   = st.sidebar.checkbox("⚫ Демо-слой: Населенные пункты", value=False)

show_routes    = st.sidebar.checkbox("🛣️ Маршруты по дорогам (красная линия)", value=True)

# Слайдер для изменения радиусов (Способ 2)
radius_km = st.sidebar.slider("Настройка радиуса покрытия (км):", min_value=1, max_value=25, value=3)

# Динамический счетчик загруженных объектов
st.sidebar.write("---")
st.sidebar.metric(label="Всего терминалов загружено", value=f"{len(df_terminals)} шт.")

# =============================================================================
# НАСТРОЙКА ВИЗУАЛЬНЫХ СЛОЕВ PYDECK
# =============================================================================
map_layers = []

# --- СПОСОБ №3: Тепловая карта плотности реальных терминалов ---
if show_method_3 and not df_terminals.empty:
    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=df_terminals,
        get_position=["lon", "lat"],
        radius_pixels=40,
        opacity=0.6,
    )
    map_layers.append(heatmap_layer)

# --- СПОСОБ №2: Зоны доступности в метрах для реальных терминалов ---
if show_method_2 and not df_terminals.empty:
    radius_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_terminals,
        get_position=["lon", "lat"],
        get_color=[41, 128, 185, 30],           # Полупрозрачный синий цвет зоны
        radius_units=pdk.types.String("meters"), # Расчет строго в физических метрах
        get_radius=radius_km * 1000,            # Перевод слайдера км -> метры
        pickable=False,
    )
    map_layers.append(radius_layer)

# --- ДЕМО-СЛОЙ: Населенные пункты ---
if show_demo_np:
    np_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_np,
        get_position=["lon", "lat"],
        get_color=[127, 140, 141, 160],
        radius_units=pdk.types.String("pixels"),
        get_radius=4,
        pickable=True,
    )
    map_layers.append(np_layer)

# --- СПОСОБ №1: Точечные маркеры РЕАЛЬНЫХ ТЕРМИНАЛОВ ---
if show_terminals and not df_terminals.empty:
    terminal_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_terminals,
        get_position=["lon", "lat"],
        get_color=[46, 204, 113, 230],          # Насыщенный зеленый цвет маркера
        radius_units=pdk.types.String("pixels"), # Размер зафиксирован в пикселях экрана
        get_radius=4.5,
        pickable=True,
    )
    map_layers.append(terminal_layer)


# =============================================================================
# МАРШРУТЫ ПО ДОРОГАМ ОБЩЕГО ПОЛЬЗОВАНИЯ (OSRM / OpenStreetMap)
# Входные данные: «Населенные_пункты.xlsx» (ОКТМО, Название, Широта, Долгота)
#                 «Маршруты.xlsx»           (Маршрут, Порядок, Пункт[, Широта, Долгота])
# =============================================================================
def load_routes():  # без st.cache_data: кэш ведётся на диске (route_cache.json), ошибки сети не запоминаются
    if not (os.path.exists("Населенные_пункты.xlsx") and os.path.exists("Маршруты.xlsx")):
        return [], ["Не найдены файлы «Населенные_пункты.xlsx» и/или «Маршруты.xlsx»"]
    places = pd.read_excel("Населенные_пункты.xlsx", dtype={"ОКТМО": str})
    routes_df = pd.read_excel("Маршруты.xlsx", dtype={"Пункт": str})
    resolved, problems = routing.resolve_routes(routes_df, routing.build_lookup(places))
    out = []
    for r in resolved:
        geo = routing.fetch_route(r["stops"])
        if geo is None:
            problems.append(f"Маршрут «{r['name']}»: сервер маршрутизации недоступен, линия не построена")
            continue
        out.append({**r, **geo})
    return out, problems

route_layers = []
zoom_to_routes = False
route_view = None
if show_routes:
    with st.spinner("Строю маршруты по дорогам..."):
        route_list, route_problems = load_routes()
    for p in route_problems:
        st.sidebar.warning(p)
    if route_list:
        names = [r["name"] for r in route_list]
        chosen = st.sidebar.multiselect("Показать маршруты:", names, default=names)
        route_list = [r for r in route_list if r["name"] in chosen]

        # цвет каждого маршрута: из колонки «Цвет» таблицы, иначе из палитры; можно менять здесь
        PALETTE = ["#E53935", "#1E88E5", "#43A047", "#FB8C00", "#8E24AA", "#00ACC1", "#6D4C41", "#D81B60"]
        with st.sidebar.expander("🎨 Цвета маршрутов", expanded=True):
            for i, r in enumerate(route_list):
                default = str(r.get("color") or "").strip()
                if not (len(default) == 7 and default.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in default[1:])):
                    default = PALETTE[names.index(r["name"]) % len(PALETTE)]  # нет цвета или формат не #RRGGBB
                r["color"] = st.color_picker(r["name"], value=str(default), key=f"color_{r['name']}")

        def hex_to_rgba(h, a=255):
            h = h.lstrip("#")
            return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [a]

        zoom_to_routes = st.sidebar.checkbox("🔍 Приблизить карту к выбранным маршрутам", value=False)

        # поля lat/lon/type/name нужны, чтобы общий tooltip не показывал пустоты
        df_paths = pd.DataFrame([{
            "path": r["path"], "type": "Маршрут по дорогам", "name": r["name"],
            "lat": f"{r['distance_km']} км", "lon": f"{r['duration_min']} мин",
            "color": hex_to_rgba(r["color"]),
        } for r in route_list])
        df_stops = pd.DataFrame([{
            "lat": lat, "lon": lon, "type": "Остановка маршрута", "name": title,
            "color": hex_to_rgba(r["color"]),
        } for r in route_list for lat, lon, title in r["stops"]])

        if not df_paths.empty:
            route_layers.append(pdk.Layer(
                "PathLayer", data=df_paths, get_path="path",
                get_color="color", width_units=pdk.types.String("pixels"),
                get_width=4, width_min_pixels=3, pickable=True,
                cap_rounded=True, joint_rounded=True,
            ))
            route_layers.append(pdk.Layer(
                "ScatterplotLayer", data=df_stops, get_position=["lon", "lat"],
                get_fill_color=[255, 255, 255, 255], get_line_color="color",
                stroked=True, line_width_units=pdk.types.String("pixels"), get_line_width=3,
                radius_units=pdk.types.String("pixels"), get_radius=6, pickable=True,
            ))
            if zoom_to_routes:
                import math
                pts = [p for r in route_list for p in r["path"]]
                lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
                span = max(max(lons) - min(lons), (max(lats) - min(lats)) * 1.6, 0.01)
                route_view = ((max(lats) + min(lats)) / 2,
                              (max(lons) + min(lons)) / 2,
                              max(3.0, min(14.0, math.log2(360 / span) - 1.2)))
            st.sidebar.write("---")
            for r in route_list:
                st.sidebar.metric(r["name"], f"{r['distance_km']} км", f"≈ {r['duration_min']} мин в пути", delta_color="off")

map_layers.extend(route_layers)   # маршруты поверх остальных слоёв

# =============================================================================
# ИНИЦИАЛЬНОЕ ПОЗИЦИОНИРОВАНИЕ КАМЕРЫ (АВТОЦЕНТРИРОВАНИЕ)
# =============================================================================
if route_view:
    base_lat, base_lon, default_zoom = route_view
initial_camera = pdk.ViewState(
    latitude=base_lat,
    longitude=base_lon,
    zoom=default_zoom,
    pitch=0,
    bearing=0
)

# Интерактивный шаблон всплывающего окна
tooltip_template = {
    "html": """
        <div style="font-family: sans-serif; padding: 6px;">
            <b>Тип объекта:</b> {type}<br>
            <b>Идентификатор:</b> {name}<br>
            <b>Широта:</b> {lat}<br>
            <b>Долгота:</b> {lon}
        </div>
    """,
    "style": {
        "backgroundColor": "#2c3e50",
        "color": "white",
        "borderRadius": "5px",
        "fontSize": "12px"
    }
}

# =============================================================================
# РЕНДЕРИНГ КАРТЫ В ИНТЕРФЕЙСЕ STREAMLIT
# =============================================================================
col_map, col_legend = st.columns([4, 1])

with col_map:
    st.pydeck_chart(
        pdk.Deck(
            layers=map_layers,
            initial_view_state=initial_camera,
            tooltip=tooltip_template,
            map_style=pdk.map_styles.CARTO_LIGHT, 
        )
    )

with col_legend:
    st.markdown("### 📊 Легенда интерфейса")
    st.markdown(
        f"""
        * 🟢 **Зеленые точки** — Терминалы (Реальные данные из файла)
        * ⚫ **Серые точки** — Населенные пункты (Демо-контекст)
        * 🔵 **Синие круги ({radius_km} км)** — Зоны пешей/транспортной доступности
        * 🔥 **Тепловые зоны** — Плотность концентрации терминалов
        * 🛣️ **Цветные линии** — Маршруты по дорогам общего пользования (цвет задаётся в боковой панели)
        """
    )
    st.write("---")
    st.info("💡 **Подсказка:** Используйте скролл мыши для изменения масштаба. Зажмите ЛКМ для перемещения. Наведите курсор на зеленую точку для просмотра точных координат объекта.")