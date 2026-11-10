# ⚽ Ember Football Simulator

**50 living footballers guided in real time by Muse Ember.**

For the **$1 Challenge** (OpenRouter × Meta Build Day): a simulator where every on-pitch action exists because `meta/muse-ember` decides it, motivates it, and then learns from it. Cost of a full demo: pennies.

## The idea in 20 seconds

We generate 50 random footballers (two squads of 3 GK / 8 DEF / 8 MID / 6 FWD) with FIFA-style traits — the forward shoots harder and more accurately than the defender, the goalkeeper saves with reflexes, and so on. Each player is born with a textual *knowledge* ("when you are inside the box, shoot", "separate into free zones", "support the ball carrier").

During the match, **two Muse Ember managers** watch the game in real time and choose the movement of all 11 starters plus the ball carrier's action (pass / shoot / dribble / tackle). The outcome is computed in Python from the players' abilities, so technique really matters. On a goal, the scorer's knowledge is updated **immediately** from ability + result (a 90+ shooter learns to "shoot often from outside the box"), and after each match Ember rewrites all 50 knowledges linking abilities to real stats. Play more matches → players and teams evolve.

## Why this is different

- **The LLM as a distributed brain, not a chatbot.** You don't talk to the model: you embody it into 50 bodies. Every tick is a real tactical decision, not a chat.
- **Emergent learning.** No hard-coded rule says "shoot from outside the box": it emerges from the ability → result → knowledge loop.
- **Demonstrable in 1 minute.** Live UI with field, commentary, and clickable knowledge. You watch evolution while playing.

## Demo (1 minute, for the video)

```bash
cp .env.example .env    # your OpenRouter key
python3 serve.py        # http://localhost:8000
```

1. Press **Fast demo** (heuristic) → two live matches start: goals, saves, commentary.
2. Click a scorer → see the knowledge he learned from the goal.
3. Press **Live demo with Ember** → "Ember is thinking…" appears, the LLM manager drives the match.

## How it is built

| Part | File |
|---|---|
| Engine + FIFA-style traits + probabilistic physics | `app.py` |
| Live UI (animated field, commentary, knowledge) | `index.html` |
| Demo server (stdlib only) | `serve.py` |
| Match logs | `data/match_*.log` (git-ignored) |
| Knowledge of 50 players | `knowledge/player_*.txt` (git-ignored) |

**LLM usage (showcase requirement):** every tactical decision goes through `POST https://openrouter.ai/api/v1/chat/completions` with model `meta/muse-ember`. The manager receives field state + abilities + knowledge + score and replies with JSON-only destinations for all starters. Cost-saving strategy: LLM every 3 ticks, heuristic in between → ~1/3 of the calls, same show.

**CLI (for iteration without UI):**
```bash
python3 app.py --matches 2 --ticks 20 --seed 1 --no-llm   # fast
python3 app.py --matches 2 --ticks 20 --seed 1 --llm      # guided by Ember
```

## Notes for the judges

- **≤$1:** simulations at a few ticks cost pennies; the project also runs without the LLM thanks to the heuristic fallback.
- **Honest limits:** simplified football (no fouls, offside, or persistent bench; 11 starters picked by role); probabilistic shot/pass resolution; `meta/muse-ember` consumes a lot of reasoning tokens, so `max_tokens ≥ 4000` is required (already handled).
- **Team/credits:** model `meta/muse-ember` via OpenRouter; OpenRouter user ID and demo video to be added to the Cerebral Valley submission.

## License / hackathon

Build Day: free for demonstration and educational reuse. Never include `.env` in commits (already in `.gitignore`).
