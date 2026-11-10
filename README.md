# ⚽ Ember Football Simulator

**50 footballers, two Muse Ember managers, memory that carries over.**

Hybrid demo for the **$1 Challenge** (OpenRouter × Meta Build Day): two squads of 25 (3 GK / 8 DEF / 8 MID / 6 FWD), 11 starters per side. Ember decides every 3 ticks (and on tick 1); heuristic fills in between. Outcomes are resolved in Python from FIFA-style attributes, and memory updates feed the next decisions.

## Demo (1 minute)

```bash
cp .env.example .env    # your OpenRouter key
python3 serve.py        # http://localhost:8000
```

1. **Practice without AI** (heuristic) → live match with commentary.
2. Click a scorer → see memory updated from match evidence.
3. **Run with Ember** → "Thinking (waiting for API)…" and the manager strategy appears in the side panel.

CLI:
```bash
python3 app.py --matches 2 --ticks 20 --seed 1 --no-llm
python3 app.py --matches 2 --ticks 20 --seed 1 --llm
```

## How it works

- **Decision:** each manager sees all 22 starters (id, squad, role, position), possession, attack direction, score and compact memory (max 3 tips, fully included). Schema: one move per starter + short strategy line. Invalid IDs/coords/actions are dropped and replaced safely (visible as Fallback).
- **Engine:** moves → ball sync → one carrier action → declared tackle only. Shots/passes use attribute+distance probabilities; saves possible at any distance. Evidence tracked per player (long/close shots attempted/scored, passes attempted/completed).
- **Memory:** immediate evidence entry after a goal; post-match reflection (one call per squad) returns ≤3 short tips per starter. Bench players keep previous memory. Changing seed resets memories to avoid stale tips.
- **Costs:** measured from OpenRouter usage (example: 2,998 tokens ≈ $0.0011 for one manager call). UI shows measured cost, successes/failures, tokens, latency; total is indicative because an in-flight request can overshoot any threshold.

## Files

| Part | File |
|---|---|
| Engine, validation, memory, API accounting | `app.py` |
| Live UI (Canvas + interpolation, EN) | `index.html` |
| Single-worker local server | `serve.py` |
| Logs / knowledge | `data/` / `knowledge/` (git-ignored) |

## Honest limits

Simplified football: no fouls, offside, or persistent bench rotation; 11 starters picked by role; probabilistic resolution (no ballistics). Adaptation is memory updates given to the model, not weight training. `meta/muse-ember` needs `max_tokens ≥ 4000` (already set). `.env` and local guidance notes are never committed.
