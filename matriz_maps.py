"""Matriz de tiempos/distancias con tráfico usando Routes API (computeRouteMatrix).

Cada par origen-destino es un "elemento" facturable. n nodos => n^2 elementos por matriz
(incluida la diagonal, que la API también calcula).
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
FIELD_MASK = "originIndex,destinationIndex,status,condition,distanceMeters,duration"
TZ = ZoneInfo("America/Santiago")
# Límites documentados: 625 elementos por request; 100 con TRAFFIC_AWARE_OPTIMAL.
MAX_ELEMENTOS = {"TRAFFIC_UNAWARE": 625, "TRAFFIC_AWARE": 625, "TRAFFIC_AWARE_OPTIMAL": 100}


def _waypoint(lat: float, lng: float) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lng}}}}


def _bloques(n: int, max_elementos: int) -> list[list[int]]:
    lado = max(1, math.isqrt(max_elementos))
    return [list(range(i, min(i + lado, n))) for i in range(0, n, lado)]


def matriz(coords: list[tuple[float, float]], salida: datetime, api_key: str,
           preferencia: str = "TRAFFIC_AWARE") -> tuple[list[list[float]], list[list[float]]]:
    """Devuelve (minutos, km) para todos los pares. `salida` naive se interpreta en hora de Chile."""
    if salida.tzinfo is None:
        salida = salida.replace(tzinfo=TZ)
    if salida <= datetime.now(timezone.utc):
        # La API rechaza departureTime en el pasado.
        raise ValueError(f"departureTime {salida.isoformat()} ya pasó; la API solo acepta horas futuras.")
    dep_utc = salida.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    n = len(coords)
    minutos = [[0.0] * n for _ in range(n)]
    km = [[0.0] * n for _ in range(n)]
    pendientes = {(i, j) for i in range(n) for j in range(n) if i != j}
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}

    bloques = _bloques(n, MAX_ELEMENTOS[preferencia])
    for bo in bloques:
        for bd in bloques:
            body = {
                "origins": [_waypoint(*coords[i]) for i in bo],
                "destinations": [_waypoint(*coords[j]) for j in bd],
                "travelMode": "DRIVE",
                "routingPreference": preferencia,
                "departureTime": dep_utc,
            }
            resp = requests.post(URL, json=body, headers=headers, timeout=90)
            if resp.status_code != 200:
                raise RuntimeError(f"Routes API {resp.status_code}: {resp.text[:500]}")
            for el in resp.json():
                # proto3 JSON omite campos con valor por defecto (índice 0, status OK vacío).
                i, j = bo[el.get("originIndex", 0)], bd[el.get("destinationIndex", 0)]
                if i == j:
                    continue
                if el.get("status", {}).get("code", 0) != 0 or el.get("condition") != "ROUTE_EXISTS":
                    raise RuntimeError(f"Sin ruta {i}->{j}: {el.get('status')} {el.get('condition')}")
                minutos[i][j] = float(el["duration"].rstrip("s")) / 60
                km[i][j] = el.get("distanceMeters", 0) / 1000
                pendientes.discard((i, j))
            time.sleep(0.2)

    if pendientes:
        raise RuntimeError(f"Faltan {len(pendientes)} pares en la respuesta, ej: {sorted(pendientes)[:5]}")
    return minutos, km


def matriz_conservadora(coords, salida: datetime, api_key: str, offsets_min=(0,),
                        preferencia: str = "TRAFFIC_AWARE", cache: Path | None = None):
    """Máximo elemento a elemento de matrices tomadas a salida + cada offset.

    Mitiga que el MILP usa tiempos estáticos: con offsets (0, 120) un viaje de las 10:00 no
    queda subestimado con el tráfico de las 08:00. Costo = len(offsets) matrices.
    """
    if cache and cache.exists():
        datos = json.loads(cache.read_text())
        if datos["coords"] == [list(c) for c in coords]:
            return datos["minutos"], datos["km"]
        raise ValueError(f"La caché {cache} es de otro conjunto de nodos; bórrala o cambia el nombre.")

    mats = [matriz(coords, salida + timedelta(minutes=o), api_key, preferencia) for o in offsets_min]
    n = len(coords)
    minutos = [[max(mt[0][i][j] for mt in mats) for j in range(n)] for i in range(n)]
    km = [[max(mt[1][i][j] for mt in mats) for j in range(n)] for i in range(n)]

    if cache:
        cache.write_text(json.dumps({"coords": [list(c) for c in coords], "salida": salida.isoformat(),
                                     "offsets": list(offsets_min), "preferencia": preferencia,
                                     "minutos": minutos, "km": km}))
    return minutos, km
