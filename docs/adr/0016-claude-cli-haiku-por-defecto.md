# ADR-0016: `CLAUDE_CLI_MODEL=haiku` por defecto

## Contexto

`ClaudeCliLLMClient` usa `claude -p` con la suscripción del usuario. Ese
cupo (ventana de 5 horas + tope semanal) es **compartido** con todo el
resto del uso de Claude: Claude Code interactivo, claude.ai (mensaje del
commit 0cc8720; README).

## Decisión

`CLAUDE_CLI_MODEL` es `haiku` por defecto, configurable a `sonnet`. Motivo
documentado: "cheapest default to minimize consumption of the shared quota"
(commit 0cc8720) y, en `.env.example`, "para minimizar el consumo del cupo
compartido de 5h/semanal; sonnet da mejor calidad a costa de gastar más de
ese mismo cupo por llamada".

## Consecuencias

- Cambia calidad por cupo.
- El costo equivalente por día y modelo queda en la tabla
  `claude_cli_usage`, la única forma de ver cuánto cupo gasta esta función.

## Estado

Aceptada.

## Referencias

- PR #10, commit `0cc8720`.
