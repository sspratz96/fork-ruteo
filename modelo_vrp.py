"""MILP de ruteo multi-viaje con ventanas de tiempo (MT-VRPTW) para UN turno de despacho.

Convenciones:
- Nodo 0 = CD Quilicura; nodos 1..n = tiendas con demanda en el turno.
- Tiempos en minutos desde medianoche (hora local). Distancias en km.
- Cada tienda se atiende completa en una sola visita (sin split delivery).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import gurobipy as gp
from gurobipy import GRB

TOL = 1e-4


@dataclass
class Instancia:
    nombres: list[str]            # [0] = CD
    demanda: list[float]          # [0] = 0; misma unidad que capacidad
    ventana_ini: list[float]      # [0] = hora en que los camiones pueden salir cargados
    ventana_fin: list[float]      # [0] = hora límite de regreso al CD
    servicio: list[float]         # min de descarga; [0] = recarga en CD entre viajes
    prioridad: list[int]          # 1 = abastecer primero
    tiempo: list[list[float]]     # min de viaje i->j (con tráfico)
    distancia: list[list[float]]  # km i->j
    capacidad: list[float]        # una entrada por camión
    max_viajes: int = 3


@dataclass
class Pesos:
    minuto_viaje: float = 1.0
    km: float = 0.0
    viaje_fijo: float = 20.0        # evita abrir viajes casi vacíos
    prioridad: float = 2.0          # costo por minuto desde la salida hasta atender una tienda prioritaria
    no_atendida: float = 10_000.0   # se duplica si la tienda es prioritaria


def hhmm(minutos: float) -> str:
    m = int(round(minutos))
    return f"{m // 60:02d}:{m % 60:02d}"


def resolver(inst: Instancia, pesos: Pesos = Pesos(), prioridad_dura: bool = False,
             time_limit: int = 120, mip_gap: float = 0.01, verbose: bool = True) -> dict:
    n = len(inst.nombres) - 1
    V, S = range(n + 1), range(1, n + 1)
    K, R = range(len(inst.capacidad)), range(inst.max_viajes)
    KR = [(k, r) for k in K for r in R]
    a, b, s, d, p, tau = (inst.ventana_ini, inst.ventana_fin, inst.servicio,
                          inst.demanda, inst.prioridad, inst.tiempo)
    T0, Tf, recarga = a[0], b[0], s[0]
    qmax = max(inst.capacidad)

    excede = [inst.nombres[i] for i in S if d[i] > qmax]
    if excede:
        raise ValueError(f"Demanda mayor a la capacidad de cualquier camión (requiere split): {excede}")
    if any(s[i] <= 0 for i in S):
        raise ValueError("servicio_min debe ser > 0 en todas las tiendas (lo usa la eliminación de subtours)")

    # Poda de arcos imposibles por ventana o capacidad: reduce mucho el número de binarias.
    def factible(i, j):
        if i == j:
            return False
        if i == 0:
            return T0 + tau[0][j] <= b[j]
        if j == 0:
            return a[i] + s[i] + tau[i][0] <= Tf
        return a[i] + s[i] + tau[i][j] <= b[j] and d[i] + d[j] <= qmax

    A = [(i, j) for i in V for j in V if factible(i, j)]
    sale, entra = defaultdict(list), defaultdict(list)
    for i, j in A:
        sale[i].append(j)
        entra[j].append(i)

    m = gp.Model("fork_mtvrptw")
    m.Params.OutputFlag = int(verbose)
    m.Params.TimeLimit = time_limit
    m.Params.MIPGap = mip_gap

    x = m.addVars([(i, j, k, r) for (i, j) in A for (k, r) in KR], vtype=GRB.BINARY, name="x")
    u = m.addVars(KR, vtype=GRB.BINARY, name="u")          # viaje (k,r) usado
    z = m.addVars(S, vtype=GRB.BINARY, name="z")           # tienda no atendida
    t = m.addVars(S, name="t")                             # inicio de descarga
    ini = m.addVars(KR, lb=T0, ub=Tf, name="ini")          # salida del CD
    fin = m.addVars(KR, lb=T0, ub=Tf, name="fin")          # regreso al CD
    for i in S:
        t[i].LB, t[i].UB = a[i], b[i]

    def sal(i, k, r):
        return gp.quicksum(x[i, j, k, r] for j in sale[i])

    def ent(j, k, r):
        return gp.quicksum(x[i, j, k, r] for i in entra[j])

    m.addConstrs((gp.quicksum(sal(i, k, r) for (k, r) in KR) + z[i] == 1 for i in S), "visita")
    m.addConstrs((sal(i, k, r) == ent(i, k, r) for i in S for (k, r) in KR), "flujo")
    m.addConstrs((sal(0, k, r) == u[k, r] for (k, r) in KR), "sale_cd")
    m.addConstrs((ent(0, k, r) == u[k, r] for (k, r) in KR), "vuelve_cd")
    m.addConstrs((gp.quicksum(d[i] * sal(i, k, r) for i in S) <= inst.capacidad[k] * u[k, r]
                  for (k, r) in KR), "capacidad")

    # Tiempos entre tiendas: una sola t_i por tienda basta porque cada tienda la visita un solo viaje.
    # También elimina subtours (s_i + tau_ij > 0).
    for i, j in A:
        if i == 0 or j == 0:
            continue
        M = b[i] + s[i] + tau[i][j] - a[j]
        if M > 0:
            usa = gp.quicksum(x[i, j, k, r] for (k, r) in KR)
            m.addConstr(t[j] >= t[i] + s[i] + tau[i][j] - M * (1 - usa), f"tt[{i},{j}]")

    for (k, r) in KR:
        for j in sale[0]:
            M = Tf + tau[0][j] - a[j]
            if M > 0:
                m.addConstr(t[j] >= ini[k, r] + tau[0][j] - M * (1 - x[0, j, k, r]))
        for i in entra[0]:
            M = b[i] + s[i] + tau[i][0] - T0
            m.addConstr(fin[k, r] >= t[i] + s[i] + tau[i][0] - M * (1 - x[i, 0, k, r]))
        m.addConstr(fin[k, r] >= ini[k, r])
        if r > 0:
            # El viaje r sale después de volver del r-1 y recargar; también rompe simetría entre viajes.
            m.addConstr(ini[k, r] >= fin[k, r - 1] + recarga - (Tf - T0 + recarga) * (1 - u[k, r]))
            m.addConstr(u[k, r] <= u[k, r - 1])

    # Simetría entre camiones idénticos.
    for k in K[:-1]:
        if inst.capacidad[k] == inst.capacidad[k + 1]:
            m.addConstr(u[k, 0] >= u[k + 1, 0])

    if prioridad_dura:  # tiendas prioritarias solo en el primer viaje de cada camión
        for i in S:
            if p[i]:
                for (k, r) in KR:
                    if r > 0:
                        for j in sale[i]:
                            x[i, j, k, r].UB = 0

    m.setObjective(
        gp.quicksum((pesos.minuto_viaje * tau[i][j] + pesos.km * inst.distancia[i][j]) * x[i, j, k, r]
                    for (i, j) in A for (k, r) in KR)
        + pesos.viaje_fijo * u.sum()
        + pesos.prioridad * gp.quicksum(t[i] - T0 for i in S if p[i])
        + gp.quicksum(pesos.no_atendida * (1 + p[i]) * z[i] for i in S),
        GRB.MINIMIZE,
    )
    m.optimize()

    if m.SolCount == 0:
        raise RuntimeError(f"Sin solución factible (status Gurobi {m.Status}). Revisa ventanas y fin de turno.")

    siguiente = defaultdict(dict)
    for (i, j, k, r), var in x.items():
        if var.X > 0.5:
            siguiente[k, r][i] = j

    rutas = []
    for (k, r) in KR:
        if u[k, r].X < 0.5:
            continue
        paradas, nodo, reloj, carga, km, min_viaje = [], 0, ini[k, r].X, 0.0, 0.0, 0.0
        while True:
            j = siguiente[k, r][nodo]
            llegada = reloj + tau[nodo][j]
            km += inst.distancia[nodo][j]
            min_viaje += tau[nodo][j]
            if j == 0:
                break
            inicio = max(t[j].X, llegada)
            paradas.append({"tienda": inst.nombres[j], "idx": j, "llegada": llegada, "inicio": inicio,
                            "espera": inicio - llegada, "demanda": d[j], "prioridad": p[j]})
            carga += d[j]
            reloj, nodo = inicio + s[j], j
        rutas.append({"camion": k + 1, "viaje": r + 1, "salida": ini[k, r].X, "regreso": llegada,
                      "carga": carga, "capacidad": inst.capacidad[k], "km": km,
                      "min_viaje": min_viaje, "paradas": paradas})

    return {
        "estado": m.Status, "objetivo": m.ObjVal, "gap": m.MIPGap, "segundos": m.Runtime,
        "n_binarias": m.NumBinVars, "n_restricciones": m.NumConstrs,
        "rutas": rutas, "no_atendidas": [inst.nombres[i] for i in S if z[i].X > 0.5],
    }


def validar(res: dict, inst: Instancia) -> list[str]:
    """Chequeo independiente del MILP: devuelve lista de violaciones (vacía = OK)."""
    errores, vistas = [], []
    a, b, s, T0, Tf = inst.ventana_ini, inst.ventana_fin, inst.servicio, inst.ventana_ini[0], inst.ventana_fin[0]
    por_camion = defaultdict(list)
    for ruta in res["rutas"]:
        if ruta["carga"] > ruta["capacidad"] + TOL:
            errores.append(f"Camión {ruta['camion']} viaje {ruta['viaje']}: sobrecarga {ruta['carga']}")
        if ruta["salida"] < T0 - TOL or ruta["regreso"] > Tf + TOL:
            errores.append(f"Camión {ruta['camion']} viaje {ruta['viaje']}: fuera del turno")
        for pa in ruta["paradas"]:
            i = pa["idx"]
            vistas.append(i)
            if pa["inicio"] < a[i] - TOL or pa["inicio"] > b[i] + TOL:
                errores.append(f"{pa['tienda']}: descarga a las {hhmm(pa['inicio'])} fuera de ventana")
        por_camion[ruta["camion"]].append(ruta)
    for k, viajes in por_camion.items():
        viajes.sort(key=lambda v: v["viaje"])
        for v1, v2 in zip(viajes, viajes[1:]):
            if v2["salida"] < v1["regreso"] + s[0] - TOL:
                errores.append(f"Camión {k}: viaje {v2['viaje']} sale antes de terminar la recarga")
    n = len(inst.nombres) - 1
    atendidas = set(vistas)
    if len(vistas) != len(atendidas):
        errores.append("Hay tiendas visitadas más de una vez")
    faltan = {inst.nombres[i] for i in range(1, n + 1) if i not in atendidas}
    if faltan != set(res["no_atendidas"]):
        errores.append(f"Inconsistencia en tiendas no atendidas: {faltan}")
    return errores


def imprimir(res: dict) -> None:
    print(f"\nObjetivo {res['objetivo']:.1f} | gap {res['gap']:.2%} | {res['segundos']:.1f}s | "
          f"{res['n_binarias']} binarias")
    for ruta in res["rutas"]:
        print(f"\nCamión {ruta['camion']} · viaje {ruta['viaje']} | sale {hhmm(ruta['salida'])} "
              f"→ vuelve {hhmm(ruta['regreso'])} | carga {ruta['carga']:.0f}/{ruta['capacidad']:.0f} "
              f"| {ruta['km']:.1f} km, {ruta['min_viaje']:.0f} min en ruta")
        for pa in ruta["paradas"]:
            marca = " [P]" if pa["prioridad"] else ""
            espera = f" (espera {pa['espera']:.0f} min)" if pa["espera"] > 0.5 else ""
            print(f"   {hhmm(pa['inicio'])}  {pa['tienda']}{marca}  dem {pa['demanda']:.0f}{espera}")
    if res["no_atendidas"]:
        print(f"\nNO ATENDIDAS: {', '.join(res['no_atendidas'])}")
