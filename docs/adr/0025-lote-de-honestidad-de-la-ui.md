# ADR-0025: Lote de honestidad de la UI

## Contexto

Revisando la UI con NVDA e IPG2211A2N aparecieron varios problemas:
- **Indicador de capacidad (4.13).** Estaba entre las tarjetas, lejos de la
  serie a la que se refiere.
- **Reality Check:**
  - la leyenda decía "95% CI" fijo, aunque TimesFM solo da una banda del 80%;
  - el veredicto empezaba siempre por el random walk, aunque en una serie
    estacional el naive estacional puede ser el rival más exigente.
- **Series macro.** Tarjetas, telemetría, banner e informe hablaban de
  "precio", "cierre" y "$" en series que no son precios, como un índice de
  producción.
- **"No aporta".** El punto central ya pasaba a segundo plano, pero el CAGR,
  que sale de ese punto, seguía en verde y destacado. En "aporta", un CAGR
  negativo también se mostraba en verde.
- **"Estado de la inercia".** Mira la pendiente de los últimos 20 registros.
  En una serie estacional mensual, esa pendiente depende de en qué parte del
  ciclo está la serie (invierno contra verano), no de una tendencia.

## Decisión

- **Indicador de capacidad.** Pasa al panel del gráfico, junto a "Serie
  activa" (`SkillBadge.tsx`), con el ID de la serie en el título. Cambia con
  la serie seleccionada; las cargas ya no se mezclan desde 4.16.
- **Nivel real de la banda.**
  - Reality Check: toma el nivel que informa el motor (`interval_level`),
    igual que `ForecastChart`; si no hay, el pedido.
  - Banner de alerta: su nivel real, sin "95%" fijo.
  - Los "95%" que quedan son VaR/CVaR al 95%, un nivel elegido a propósito.
- **Veredicto.** Primero el naive más exigente en ese corte, el de menor
  error, con el criterio de 3.5 (`capability()` en
  `scripts/fred_category_benchmark.py`). El otro va después, como "Dato
  secundario".
- **Macro.** "$", "Precio" y "cierre" quedan solo para acciones
  (`utils/valueFormat.ts`). En las series macro se usa "Último valor" y la
  unidad de la serie.
  - El backtest informa su unidad (`BacktestResponse.unit`).
  - El informe nombra la serie del Reality Check: puede no ser la que está
    en pantalla, y su MAE no se muestra en la unidad de otra serie. Verificar
    en el navegador encontró ese error: el MAE de NVDA salía en "Index
    2017=100".
- **"No aporta".**
  - El CAGR se muestra en gris y chico, con la aclaración "Sale del punto
    central, que no supera al naive".
  - En "aporta", el color sigue el signo.
  - La "tendencia central" de la telemetría pierde el color.
- **Inercia en series estacionales: se oculta, no se aclara.** Una
  aclaración al lado de una etiqueta como "Aceleración negativa" en rojo
  deja igual la etiqueta equivocada como dato principal. Mostrar la fase
  del ciclo con nombre de tendencia es justo lo que hay que evitar. La
  tarjeta queda con el motivo: "No se muestra en series estacionales…".
  Para eso, el pronóstico ahora incluye `seasonality`, el detector de 3.0a
  sobre los puntos pronosticados.

## Consecuencias

- Verificado en el navegador sobre una copia de la DB:
  - **NVDA:** no aporta, CAGR en segundo plano, inercia visible;
  - **IPG2211A2N:** aporta, CAGR negativo en rojo, inercia oculta, sin "$";
  - leyenda del Reality Check con TimesFM: 80%;
  - informe con la unidad y la serie correctas.
- **Hallazgo:** en el corte por defecto de IPG2211A2N (2025-08-01, 12
  meses), TimesFM **no** supera al naive estacional (MAE 3,00 contra 2,67).
  El veredicto lo dice primero. Es un solo corte; la evidencia de 3.0d (24
  cortes) sigue siendo la del indicador.

## Estado

Aceptada.

## Referencias

- Rama `fix/ui-honesty-batch`.
- Tests: `tests/test_backtest_verdict.py` y
  `tests/test_forecast_seasonality.py`; en el front, `ForecastChart`,
  `MetricCards`, `BacktestPanel`, `StatisticalTelemetry` y `exportReport`.
