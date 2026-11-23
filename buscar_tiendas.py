"""Busca las tiendas Fork en Google Maps (Places API New, Text Search) y arma tiendas.csv.

Corre una sola vez y luego completa a mano prioridad, demanda, ventanas de recepción y servicio.
El horario de Google es el de atención a público, NO necesariamente el de recepción de carga.
Uso: GOOGLE_MAPS_API_KEY=... python buscar_tiendas.py --salida tiendas.csv
"""
import argparse
import csv
import os

import requests

URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ("places.id,places.displayName,places.formattedAddress,places.location,"
              "places.regularOpeningHours.weekdayDescriptions,nextPageToken")
COLUMNAS = ["id", "nombre", "direccion", "lat", "lng", "horario_google", "prioridad", "servicio_min",
            "demanda_manana", "recep_ini_manana", "recep_fin_manana",
            "demanda_tarde", "recep_ini_tarde", "recep_fin_tarde"]


def buscar(api_key: str, consulta: str) -> list[dict]:
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    body = {
        "textQuery": consulta,
        "languageCode": "es",
        "pageSize": 20,
        "locationBias": {"circle": {"center": {"latitude": -33.44, "longitude": -70.62}, "radius": 30000.0}},
    }
    lugares = []
    while True:
        resp = requests.post(URL, json=body, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Places API {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        lugares += data.get("places", [])
        token = data.get("nextPageToken")
        if not token:
            return lugares
        body["pageToken"] = token


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--consulta", default="Fork tienda de comida Santiago")
    ap.add_argument("--salida", default="tiendas.csv")
    args = ap.parse_args()

    filas = []
    for p in buscar(os.environ["GOOGLE_MAPS_API_KEY"], args.consulta):
        nombre = p.get("displayName", {}).get("text", "")
        if not nombre.lower().startswith("fork"):   # descarta homónimos y restaurantes ajenos
            continue
        horario = " | ".join(p.get("regularOpeningHours", {}).get("weekdayDescriptions", []))
        filas.append({"id": p["id"], "nombre": nombre, "direccion": p.get("formattedAddress", ""),
                      "lat": p["location"]["latitude"], "lng": p["location"]["longitude"],
                      "horario_google": horario, "prioridad": 0, "servicio_min": 15,
                      "demanda_manana": "", "recep_ini_manana": "", "recep_fin_manana": "",
                      "demanda_tarde": "", "recep_ini_tarde": "", "recep_fin_tarde": ""})

    with open(args.salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} tiendas escritas en {args.salida}. Revisa que estén todas y que no haya duplicados.")
