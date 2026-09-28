# ADR-0031: `CLAUDE_CLI_MODEL=sonnet` por defecto (reemplaza ADR-0016)

## Contexto

ADR-0016 eligió `haiku` por defecto para gastar menos del cupo compartido de
Claude (ventana de 5 horas y tope semanal), cambiando calidad por cupo.

La evaluación pre-registrada de 4.10 + 4.6
(`docs/results/thesis_prompt_v2_2026-09-28.md`) midió esa calidad con las
mismas 4 tesis.

**Haiku, con el prompt nuevo:**
- en T1 propuso series de FRED irrelevantes al mecanismo (INDPRO, IPC de
  alimentos) y un ID que no existe (ELECCCMI); 10 de 13 series relevantes;
- usó el campo `source` para afirmaciones en lugar de fuentes (5 de 5
  instrumentos en T1);
- cometió errores de hecho: "PSQ: inverso 3x Nasdaq-100 de Direxion" (PSQ es
  de ProShares, −1x); el ETF "IPO" usado como exposición a semiconductores.

**Sonnet, con el mismo prompt:**
- 15 de 16 series relevantes;
- sin errores de hecho de ese tipo;
- citó sus fuentes en el texto.

**Latencia:** Haiku no fue más rápido.

| Modelo | Prompt | Mediana | Máxima |
|---|---|---|---|
| Haiku | viejo | 32 s | 170 s |
| Haiku | nuevo | 89 s | 191 s |
| Sonnet | viejo | 35 s | 48 s |
| Sonnet | nuevo | 49 s | 72 s |

## Decisión

- `CLAUDE_CLI_MODEL` es `sonnet` por defecto
  (`backend/config.py: CLAUDE_CLI_DEFAULT_MODEL`).
- `haiku` sigue disponible con `CLAUDE_CLI_MODEL=haiku`.

## Consecuencias

- Cada traducción de tesis con Claude CLI gasta más del cupo compartido. El
  gasto por día y modelo queda en `claude_cli_usage`, como antes.
- Si el `.env` de una máquina fija `CLAUDE_CLI_MODEL=haiku`, sigue usando
  haiku. El `.env` de este proyecto no lo fija.

## Estado

Aceptada.

## Referencias

- Reemplaza a ADR-0016.
- Evaluación: `docs/results/thesis_prompt_v2_2026-09-28.md`.
- Test: `test_claude_cli_default_model_is_sonnet`.
