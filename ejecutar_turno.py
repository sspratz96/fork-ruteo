"""Planifica un turno (mañana o tarde). Correrlo poco antes de la salida para capturar el tráfico.

Ejemplo:
  GOOGLE_MAPS_API_KEY=... python ejecutar_turno.py --fecha 2026-11-24 --turno manana \
      --salida 07:30 --fin 13:00 --camiones 3 --capacidad 60 --max-viajes 3 --offsets 0 120
"""
import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

from matriz_maps import matriz_conservadora
from modelo_vrp import Instancia, Pesos, hhmm, imprimir, resolver, validar

CD_NOMBRE = "CD Quilicura"


def cd_coords() -> tuple[float, float]:
    valor = os.environ.get("CD_COORDS")  # formato "lat,lng"
    if not valor:
        raise SystemExit('Define CD_COORDS="lat,lng" con la ubicación del CD (ver .env.example).')
    lat, lng = (float(v) for v in valor.split(","))
    return lat, lng


def a_minutos(hh_mm: str) -> int:
    h, m = hh_mm.strip().split(":")
    return int(h) * 60 + int(m)


def leer_tiendas(ruta: str, turno: str) -> list[dict]:
    tiendas = []
    with open(ruta, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            dem = fila[f"demanda_{turno}"].strip()
            if not dem or float(dem) <= 0:
                continue  # sin pedido en este turno
            tiendas.append({
                "nombre": fila["nombre"], "lat": float(fila["lat"]), "lng": float(fila["lng"]),
                "demanda": float(dem), "prioridad": int(fila["prioridad"] or 0),
                "servicio": float(fila["servicio_min"] or 15),
                "ini": a_minutos(fila[f"recep_ini_{turno}"]), "fin": a_minutos(fila[f"recep_fin_{turno}"]),
            })
    return tiendas


def exportar(res: dict, ruta: Path) -> None:
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["camion", "viaje", "orden", "tienda", "prioridad", "llegada", "inicio_descarga",
                    "demanda", "salida_cd", "regreso_cd"])
        for r in res["rutas"]:
            for n, pa in enumerate(r["paradas"], 1):
                w.writerow([r["camion"], r["viaje"], n, pa["tienda"], pa["prioridad"], hhmm(pa["llegada"]),
                            hhmm(pa["inicio"]), pa["demanda"], hhmm(r["salida"]), hhmm(r["regreso"])])
        for t in res["no_atendidas"]:
            w.writerow(["", "", "", t, "", "", "", "", "", "NO ATENDIDA"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", required=True, help="YYYY-MM-DD")
    ap.add_argument("--turno", choices=["manana", "tarde"], required=True)
    ap.add_argument("--salida", required=True, help="HH:MM en que los camiones pueden salir cargados")
    ap.add_argument("--fin", required=True, help="HH:MM límite de regreso al CD")
    ap.add_argument("--camiones", type=int, required=True)
    ap.add_argument("--capacidad", type=float, nargs="+", required=True,
                    help="una capacidad (todos iguales) o una por camión")
    ap.add_argument("--max-viajes", type=int, default=3)
    ap.add_argument("--recarga", type=float, default=30, help="min de recarga en el CD entre viajes")
    ap.add_argument("--tiendas", default="tiendas.csv")
    ap.add_argument("--offsets", type=int, nargs="+", default=[0], help="min tras la salida para pedir matrices")
    ap.add_argument("--preferencia", default="TRAFFIC_AWARE",
                    choices=["TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"])
    ap.add_argument("--prioridad-dura", action="store_true", help="prioritarias solo en el primer viaje")
    ap.add_argument("--time-limit", type=int, default=120)
    args = ap.parse_args()

    CD_COORDS = cd_coords()
    capacidades = args.capacidad * args.camiones if len(args.capacidad) == 1 else args.capacidad
    if len(capacidades) != args.camiones:
        raise SystemExit("--capacidad debe tener 1 valor o uno por camión")

    tiendas = leer_tiendas(args.tiendas, args.turno)
    if not tiendas:
        raise SystemExit("Ninguna tienda con demanda en este turno.")
    coords = [CD_COORDS] + [(t["lat"], t["lng"]) for t in tiendas]
    T0, Tf = a_minutos(args.salida), a_minutos(args.fin)
    salida_dt = datetime.fromisoformat(f"{args.fecha}T{args.salida}")

    n_elem = len(coords) ** 2 * len(args.offsets)
    print(f"{len(tiendas)} tiendas en el turno; se pedirán {n_elem} elementos a Routes API.")
    cache = Path(f"matriz_{args.fecha}_{args.turno}.json")
    minutos, km = matriz_conservadora(coords, salida_dt, os.environ["GOOGLE_MAPS_API_KEY"],
                                      tuple(args.offsets), args.preferencia, cache)

    inst = Instancia(
        nombres=[CD_NOMBRE] + [t["nombre"] for t in tiendas],
        demanda=[0] + [t["demanda"] for t in tiendas],
        ventana_ini=[T0] + [t["ini"] for t in tiendas],
        ventana_fin=[Tf] + [t["fin"] for t in tiendas],
        servicio=[args.recarga] + [t["servicio"] for t in tiendas],
        prioridad=[0] + [t["prioridad"] for t in tiendas],
        tiempo=minutos, distancia=km, capacidad=capacidades, max_viajes=args.max_viajes,
    )
    res = resolver(inst, Pesos(), prioridad_dura=args.prioridad_dura, time_limit=args.time_limit)
    imprimir(res)
    errores = validar(res, inst)
    if errores:
        raise SystemExit(f"La solución no pasó la validación: {errores}")
    salida_csv = Path(f"plan_{args.fecha}_{args.turno}.csv")
    exportar(res, salida_csv)
    print(f"\nPlan escrito en {salida_csv}")
