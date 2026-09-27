# ADR-0002: Auto-discovery: mini-backtest por serie, cacheado en SQLite

## Contexto

Los catálogos de la ADR-0001 solo cubrían las series medidas a mano. Una
serie nueva que trajera el LLM (por ejemplo `IPG3344S`) caía al default
Holt sin haber sido medida nunca: "no escala" (mensaje del commit ffc04f3).

## Decisión

`AutoDiscoveryEngine` (`backend/services/auto_discovery.py`): para cualquier
serie fuera de los catálogos con 90 puntos o más, corre un mini-backtest
walk-forward (reusando `BacktestEngine.run_backtest` con `engine_override`,
sin reimplementarlo), compara el motor base con TimesFM y cachea la decisión
en la tabla `engine_decisions`, una fila por serie. Se eligió SQLite y no un
archivo plano porque el proyecto ya usaba SQLAlchemy/SQLite y una fila
consultable por serie encaja en ese patrón (commit ffc04f3). La decisión se
re-evalúa pasados 30 días o si la serie creció un 20% o más.

## Consecuencias

- El primer pedido de una serie nueva paga el mini-backtest (latencias
  medidas en `docs/ARCHITECTURE.md`); los siguientes, una lectura de SQLite.
- Un mini-backtest que falla no rompe el `/forecast` que lo disparó.
- La regla original (3 cutoffs, ganador por MASE medio, guard de cobertura)
  fue reemplazada por la v4 (ADR-0007), con el esquema de versiones de la
  ADR-0006.

## Estado

Aceptada; su regla de decisión evolucionó (ADR-0006, ADR-0007).

## Referencias

- PR #8, commit `ffc04f3`.
- Resultados: latencias en `docs/ARCHITECTURE.md` ("Costo medido").
