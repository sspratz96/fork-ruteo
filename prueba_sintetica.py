"""Prueba del modelo con datos sintéticos (sin llamar a Google). Coordenadas y demandas inventadas."""
import argparse
import math
import random

from modelo_vrp import Instancia, Pesos, imprimir, resolver, validar


def haversine_km(p, q):
    lat1, lon1, lat2, lon2 = map(math.radians, (*p, *q))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def instancia_sintetica(n_tiendas, camiones, capacidad, viajes, semilla=7):
    rnd = random.Random(semilla)
    cd = (-33.36, -70.73)  # zona Quilicura, aproximado
    tiendas = [(-33.40 - rnd.random() * 0.12, -70.62 + rnd.random() * 0.12) for _ in range(n_tiendas)]
    coords = [cd] + tiendas
    dist = [[haversine_km(p, q) * 1.35 for q in coords] for p in coords]   # factor de desvío vial
    tiempo = [[dk / 22 * 60 for dk in fila] for fila in dist]              # 22 km/h promedio con tráfico
    T0, Tf = 7 * 60, 13 * 60
    ini, fin = [T0], [Tf]
    for _ in tiendas:
        apertura = rnd.choice([7 * 60, 8 * 60, 9 * 60])
        ini.append(apertura)
        fin.append(apertura + rnd.choice([120, 180, 240]))
    return Instancia(
        nombres=["CD Quilicura"] + [f"Tienda {i}" for i in range(1, n_tiendas + 1)],
        demanda=[0] + [rnd.randint(4, 18) for _ in tiendas],
        ventana_ini=ini, ventana_fin=fin,
        servicio=[30] + [15] * n_tiendas,
        prioridad=[0] + [1 if rnd.random() < 0.3 else 0 for _ in tiendas],
        tiempo=tiempo, distancia=dist,
        capacidad=[capacidad] * camiones, max_viajes=viajes,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiendas", type=int, default=10)
    ap.add_argument("--camiones", type=int, default=2)
    ap.add_argument("--capacidad", type=float, default=50)
    ap.add_argument("--viajes", type=int, default=2)
    ap.add_argument("--prioridad-dura", action="store_true")
    args = ap.parse_args()

    inst = instancia_sintetica(args.tiendas, args.camiones, args.capacidad, args.viajes)
    res = resolver(inst, Pesos(), prioridad_dura=args.prioridad_dura, time_limit=60, verbose=False)
    imprimir(res)
    errores = validar(res, inst)
    print("\nValidación:", "OK" if not errores else errores)
