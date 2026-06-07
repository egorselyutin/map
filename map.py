import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import os

# Устанавливаем широкую конфигурацию страницы, чтобы карта занимала максимум места
st.set_page_config(layout="wide", page_title="ГИС Мониторинг")

st.title("🗺️ Геоинформационный модуль мониторинга доступности услуг")
st.caption("Карта размещения терминалов с поддержкой масштабирования, слоев и интерактивных подсказок")

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
# ИНИЦИАЛЬНОЕ ПОЗИЦИОНИРОВАНИЕ КАМЕРЫ (АВТОЦЕНТРИРОВАНИЕ)
# =============================================================================
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
        """
    )
    st.write("---")
    st.info("💡 **Подсказка:** Используйте скролл мыши для изменения масштаба. Зажмите ЛКМ для перемещения. Наведите курсор на зеленую точку для просмотра точных координат объекта.")