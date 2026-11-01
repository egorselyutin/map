"""Построение маршрутов по дорогам общего пользования через OSRM (данные OpenStreetMap).

Модуль не зависит от Streamlit, его можно запускать и тестировать отдельно.
"""
import hashlib
import json
import os
import time

import pandas as pd
import requests

# Публичный демо-сервер OSRM: только для небольших объёмов, без гарантий доступности.
# Для постоянной работы поднимите свой OSRM (docker) и укажите адрес в переменной OSRM_URL.
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
CACHE_FILE = os.environ.get("ROUTE_CACHE", "route_cache.json")


# --------------------------------------------------------------------------- #
# Справочник населённых пунктов и разбор списка остановок
# --------------------------------------------------------------------------- #
def _norm(x) -> str:
    return str(x).strip().lower().replace("ё", "е") if pd.notna(x) else ""


def build_lookup(places: pd.DataFrame) -> dict:
    """Справочник -> словарь {ключ: (lat, lon, название)}; ключи: ОКТМО и название."""
    lookup = {}
    for r in places.itertuples(index=False):
        rec = (float(r.Широта), float(r.Долгота), str(r.Название))
        if _norm(getattr(r, "ОКТМО", None)):
            lookup[_norm(r.ОКТМО)] = rec
        lookup[_norm(r.Название)] = rec
    return lookup


def resolve_routes(routes: pd.DataFrame, lookup: dict):
    """Таблица маршрутов -> список {name, stops:[(lat, lon, title)]} и список проблем.

    Колонки таблицы: Маршрут | Порядок | Пункт (название или ОКТМО).
    Необязательно: Широта, Долгота — если заданы, имеют приоритет над справочником;
    Цвет — цвет линии маршрута в формате #RRGGBB.
    """
    result, problems = [], []
    for name, grp in routes.groupby("Маршрут", sort=False):
        grp = grp.sort_values("Порядок")
        stops = []
        for r in grp.to_dict("records"):
            lat, lon = r.get("Широта"), r.get("Долгота")
            if pd.notna(lat) and pd.notna(lon):
                stops.append((float(lat), float(lon), str(r["Пункт"])))
                continue
            rec = lookup.get(_norm(r["Пункт"]))
            if rec is None:
                problems.append(f"Маршрут «{name}»: пункт «{r['Пункт']}» не найден в справочнике")
            else:
                stops.append(rec)
        if len(stops) >= 2:
            color = grp["Цвет"].dropna().iloc[0] if "Цвет" in grp.columns and grp["Цвет"].notna().any() else None
            result.append({"name": str(name), "stops": stops, "color": color})
        else:
            problems.append(f"Маршрут «{name}»: нужно минимум 2 найденных пункта")
    return result, problems


# --------------------------------------------------------------------------- #
# Запрос к OSRM + кэш на диске
# --------------------------------------------------------------------------- #
def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _key(stops) -> str:
    s = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon, _ in stops)
    return hashlib.md5(s.encode()).hexdigest()


def fetch_route(stops, retries: int = 2):
    """stops: [(lat, lon, title)...]. Возвращает dict(path, distance_km, duration_min) или None.

    path — список [lon, lat] вдоль реальных дорог. Результат кэшируется в route_cache.json,
    поэтому каждый маршрут запрашивается у сервера только один раз.
    """
    cache = _load_cache()
    k = _key(stops)
    if k in cache:
        return cache[k]

    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon, _ in stops)
    url = f"{OSRM_URL}/route/v1/driving/{coords}"
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=20,
                                headers={"User-Agent": "gis-monitoring/1.0"})
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                return None
            rt = data["routes"][0]
            out = {
                "path": rt["geometry"]["coordinates"],
                "distance_km": round(rt["distance"] / 1000, 1),
                "duration_min": round(rt["duration"] / 60),
            }
            cache[k] = out
            _save_cache(cache)
            return out
        except Exception:
            time.sleep(1 + attempt)
    return None
