# Ruteo de despachos Fork (MT-VRPTW en Gurobi)

> Proyecto personal. No está afiliado a Betterfood SpA ni a Fork y no usa datos internos de la empresa.

Pipeline por turno: `buscar_tiendas.py` (una vez) → `ejecutar_turno.py` (cada turno: matriz con tráfico vía Routes API → MILP → validación → `plan_<fecha>_<turno>.csv`).

## Formulación (un turno)

**Conjuntos**: nodo 0 = CD; S = tiendas con demanda en el turno; K = camiones; R = viajes por camión; A = arcos factibles tras poda por ventana y capacidad.

**Parámetros**: demanda dᵢ, capacidad Q_k, ventana [aᵢ, bᵢ], descarga sᵢ, prioridad pᵢ ∈ {0,1}, tiempo τᵢⱼ y distancia cᵢⱼ con tráfico, turno [T₀, T_f], recarga s₀.

**Variables**: xᵢⱼₖᵣ ∈ {0,1} (arco en el viaje r del camión k), uₖᵣ ∈ {0,1} (viaje usado), zᵢ ∈ {0,1} (tienda no atendida), tᵢ ∈ [aᵢ, bᵢ] (inicio de descarga), iniₖᵣ, finₖᵣ ∈ [T₀, T_f].

**Objetivo**

min Σ τᵢⱼ·xᵢⱼₖᵣ + w_km Σ cᵢⱼ·xᵢⱼₖᵣ + w_viaje Σ uₖᵣ + w_prio Σ pᵢ(tᵢ − T₀) + Σ w_no(1 + pᵢ) zᵢ

**Restricciones**

1. Visita: Σₖᵣ Σⱼ xᵢⱼₖᵣ + zᵢ = 1, ∀i ∈ S
2. Flujo: Σⱼ xᵢⱼₖᵣ = Σⱼ xⱼᵢₖᵣ, ∀i ∈ S, k, r
3. CD: Σⱼ x₀ⱼₖᵣ = Σᵢ xᵢ₀ₖᵣ = uₖᵣ
4. Capacidad: Σᵢ dᵢ Σⱼ xᵢⱼₖᵣ ≤ Q_k·uₖᵣ
5. Tiempo entre tiendas (también elimina subtours): tⱼ ≥ tᵢ + sᵢ + τᵢⱼ − Mᵢⱼ(1 − Σₖᵣ xᵢⱼₖᵣ)
6. Salida y regreso: tⱼ ≥ iniₖᵣ + τ₀ⱼ − M(1 − x₀ⱼₖᵣ); finₖᵣ ≥ tᵢ + sᵢ + τᵢ₀ − M(1 − xᵢ₀ₖᵣ)
7. Multi-viaje: iniₖ,ᵣ ≥ finₖ,ᵣ₋₁ + s₀ − M(1 − uₖᵣ); uₖᵣ ≤ uₖ,ᵣ₋₁
8. Simetría entre camiones idénticos: uₖ,₁ ≥ uₖ₊₁,₁
9. Opcional `--prioridad-dura`: tiendas con pᵢ = 1 solo en el viaje r = 1

Big-M ajustados por arco (Mᵢⱼ = bᵢ + sᵢ + τᵢⱼ − aⱼ). Una sola tᵢ por tienda basta porque cada tienda la visita un único viaje.

## Estructura

| Archivo | Rol |
|---|---|
| `modelo_vrp.py` | MILP en Gurobi, extracción de rutas y validación independiente |
| `matriz_maps.py` | Routes API `computeRouteMatrix` con tráfico, en bloques y con caché |
| `buscar_tiendas.py` | Places API Text Search → `tiendas.csv` (se corre una vez) |
| `ejecutar_turno.py` | Orquestador por turno → `plan_<fecha>_<turno>.csv` |
| `prueba_sintetica.py` | Prueba sin llamadas a Google |
| `tiendas.example.csv` | Formato esperado de `tiendas.csv` (datos ficticios) |

`tiendas.csv`, `matriz_*.json`, `plan_*.csv` y `.env` están en `.gitignore`: los datos reales no se versionan.

## Uso

Requiere Python ≥ 3.10.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python prueba_sintetica.py                     # sin API, valida el modelo

cp .env.example .env                           # completar API key y coordenadas del CD
set -a; source .env; set +a

python buscar_tiendas.py --salida tiendas.csv  # gasta cuota de Places API
# completar tiendas.csv (prioridad, demandas, ventanas de recepción HH:MM, servicio_min)
python ejecutar_turno.py --fecha 2026-11-24 --turno manana \
  --salida 07:30 --fin 13:00 --camiones 3 --capacidad 60 --max-viajes 3 --offsets 0 120
```

## Limitaciones conocidas

- Tiempos estáticos por turno: el tráfico se fija al momento de salida. `--offsets` toma el máximo de varias matrices como cota conservadora.
- Routes API no tiene modo camión (se usa DRIVE); restricciones de tránsito de camiones en comunas no se modelan.
- Sin split delivery: si una tienda pide más que un camión, el modelo lo rechaza.
- La licencia de gurobipy de pip limita a 2.000 variables y es no comercial.
