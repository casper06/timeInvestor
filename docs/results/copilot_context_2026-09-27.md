# Copiloto: antes y después del contexto nuevo (2026-09-27)

Rama `fix/copilot-context`. Misma tesis y mismos números en las dos corridas.
Lo único que cambia es cómo se arma el contexto del copiloto y qué reglas
recibe.

## Montaje

- **Servidores:**
  - "antes": código de `main` (61d7348), en un worktree temporal;
  - "después": esta rama;
  - cada uno sobre su propia copia de la DB, nunca sobre `time_investor.db`.
- **Proveedor:** Gemini API (`gemini-3.6-flash`), el configurado en la app.
- **Tesis:** "Demanda eléctrica por centros de datos de IA", analizada una
  sola vez; se usa ese resultado en las dos corridas.
  - Tickers: CEG, VST, GEV, ETN, EQIX.
  - Series FRED: IPG2211S, PCU3353133531, DGS10.
- **Serie activa:** CEG. Último dato 263,27 (2026-09-25).
- **Pronóstico:** 270,25 a 60 días hábiles (2026-12-18), banda 95% [166,29 –
  415,85], CAGR 12,1%.
- **Contexto de cada corrida:**
  - "antes": el de `ThesisCopilot.tsx` de `main` (`capex_summary`);
  - "después": el de la rama (fechas, fundamentales con su ejercicio; la
    evidencia de FRED la agrega el servidor).
- **Intentos del "después":** el primero cayó al mock por el límite gratuito
  de Gemini (429, 5 pedidos por minuto) y el segundo por 503 ("high demand").
  El tercero, 3 minutos después, respondió Gemini, y es el que se muestra.
  Los números de entrada son los mismos: el script comprueba que el último
  precio no cambió.

## Antes (main)

> **Qué dicen los datos:** La proyección a 60 días muestra una trayectoria
> alcista moderada hacia $270.25 (CAGR del 12.1%), respaldada por una
> aceleración continua en el Capex proyectado para 2025 ($2.95B). Sin
> embargo, la dispersión en las bandas del 95% ($166.29 - $415.85) evidencia
> una alta asimetría y volatilidad, reflejando riesgos de ejecución e
> incertidumbre regulatoria en contratos de energía nuclear/térmica para
> datacenters.
>
> **Alineación:** Tesis Confirmada. La aceleración del Capex en todo el
> ecosistema (CEG, VST, EQIX, ETN, GEV) valida fundamentalmente que la
> demanda de infraestructura energética para IA es estructural. La
> telemetría cuantitativa apoya la hipótesis de revalorización, aunque el
> precio proyectado sugiere una etapa de consolidación a corto plazo dentro
> de la tendencia mayor.
>
> **Qué mirar:** Supervisar el índice de precios a la producción de equipos
> de distribución y transformadores eléctricos… (PCU3353133531)

Problemas:
- "Tesis Confirmada" con el capex de las empresas que eligió el mismo LLM.
- "Capex proyectado para 2025": en realidad es el ejercicio cerrado 2025.
- "Incertidumbre regulatoria en contratos de energía nuclear/térmica" no
  está en los datos.
- No menciona ningún indicador de FRED: no los recibía, solo sus IDs.

## Después (esta rama)

> **Qué dicen los datos:** Al 2026-09-27, el último precio real observado de
> CEG es de 263.2700 (2026-09-25). La salida del modelo estadístico (no
> observada) proyecta un valor de 270.2525 al 2026-12-18 (CAGR implícito de
> 12.1%) con un intervalo del 95% entre 166.2867 y 415.8489. En los
> indicadores del mundo (FRED), la producción industrial de energía eléctrica
> (IPG2211S) creció un 7.0% interanual al 2026-08-01 (de 105.7 a 113.1),
> mientras que los precios de equipos eléctricos (PCU3353133531) subieron un
> 9.1% interanual al 2026-08-01 (de 233.7 a 254.9). Por su parte, la tasa a
> 10 años DGS10 aumentó 1.02 puntos porcentuales al 2026-09-24, ubicándose en
> 5.18%. Finalmente, el capex y los ingresos del ejercicio cerrado 2025
> aumentaron en las empresas seleccionadas (CEG, VST, GEV, ETN, EQIX) en
> comparación con 2024.
>
> **Alineación:** La tesis encuentra evidencia de soporte en los datos
> macroeconómicos observados (series FRED): la producción de energía
> eléctrica (IPG2211S) se incrementó +7.0% y los precios de insumos de
> equipamiento eléctrico (PCU3353133531) aumentaron +9.1% interanual al
> 2026-08-01. No obstante, el alza en el rendimiento del bono a 10 años
> (DGS10) al 5.18% al 2026-09-24 representa una presión al alza en los costos
> del capital. Los datos contables de capex e ingresos de las empresas
> listadas (CEG, VST, GEV, ETN, EQIX) crecieron en el ejercicio 2025, pero al
> provenir de una muestra no representativa seleccionada manualmente, no se
> utilizan como confirmación formal de la tesis.
>
> **Qué mirar:** Se recomienda dar seguimiento continuo al índice de precios
> al productor de equipamiento eléctrico… (PCU3353133531)

**Comprobado contra los datos:**
- CEG está en 263,27 al 2026-09-25.
- DGS10 está en 5,18 al 2026-09-24.
- Capex e ingresos 2025 mayores que 2024 en las 5 empresas (10 de 10 pares).

**Imprecisión que queda:** dice "seleccionada manualmente"; las eligió el LLM.

## Fundamentales: por qué el informe traía solo CEG y ETN

- **Causa:** `exportReport.ts` hacía `data.fundamentals.slice(0, 15)`.
  - Cada empresa trae 8 filas (capex e ingresos de 4 ejercicios).
  - Con CEG, ETN, VST, GEV y PWR (40 filas, sin warnings, verificado contra
    yfinance), las primeras 15 son las 8 de CEG y 7 de ETN.
- **Arreglo:** una fila por empresa con su último ejercicio cerrado (y el
  anterior), para todas, más "Sin fundamentales: …" para las que no
  trajeron datos.
