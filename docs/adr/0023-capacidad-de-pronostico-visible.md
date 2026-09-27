# ADR-0023: Capacidad de pronóstico visible por serie (4.13, criterio v9)

## Contexto

La app mostraba siempre un pronóstico puntual como dato principal, aunque en
muchas series no le gana al naive: 3.5 lo midió por categoría, y las
financieras diarias no le ganan al random walk.

## Decisión

Cada `ForecastResponse` trae `skill`, con uno de tres estados:
- "aporta sobre el naive";
- "no aporta más que el naive";
- "no evaluado", con el motivo.

El criterio se pre-registró antes de implementar (`docs/PLAN.md` 4.13,
commit `4c94bea`).
- **Naive:** el estacional si el detector de 3.0a marca la serie completa
  como estacional; si no, el random walk.
- **Evidencia:**
  - los cutoffs del mini-backtest de la decisión (MAE del motor elegido
    contra el MAE del naive);
  - en el catálogo estacional, los 24 cutoffs de 3.0d (constantes en
    `forecast_skill.py`, con un test que las recalcula del JSON
    versionado).
- **Regla:** con al menos 7 pares, "aporta" si el motor gana la mayoría y su
  error medio es al menos un 10% menor.
- **Almacenamiento:** la decisión guarda el MAE por cutoff del motor base,
  de TimesFM y del naive (`engine_decisions.cutoff_errors_json`, con
  migración). Se subió el criterio a **v9** para que las decisiones se
  re-evalúen y lo completen.
- **UI:** el dashboard muestra el estado con su explicación. Cuando "no
  aporta", la tarjeta de objetivo pasa a mostrar el rango como dato
  principal y el punto central como secundario, con el aviso "el pronóstico
  puntual no supera a 'igual que el último dato'" (o 'igual que el mismo
  período del ciclo anterior').

## Consecuencias

Verificado sobre una copia de la DB. Coincide con lo esperable; no se ajustó
nada:

| Serie | Estado | Evidencia |
|---|---|---|
| NVDA | no aporta | 6 de 8 contra el random walk, pero solo un 7% menos de error |
| IPG2211A2N | aporta | 18 de 24 contra el naive estacional, 17% menos (3.0d) |
| DGS10 | no aporta | 5 de 8, 0,6% |
| POPTHM | aporta | 8 de 8 contra el naive estacional, 91% menos |

Quedan sin evidencia contra el naive, y se muestran como "no evaluado" con
el motivo:
- el catálogo de ETFs;
- el camino por defecto;
- los pedidos que respondió el plan B.

## Estado

Aceptada.

## Referencias

- Rama `feat/forecast-skill-badge` (sobre la de 2.11).
- Pre-registro: commit `4c94bea`.
- Tests: `tests/test_forecast_skill.py` y `MetricCards.test.tsx`.
