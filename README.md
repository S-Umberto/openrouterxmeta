# Simulatore Calcio – Muse Ember (OpenRouter) · Hackathon Demo

50 giocatori (2 squadre x 3P/8D/8C/6A) random stile FIFA (attaccanti forti nel tiro,
difensori nel placcaggio, etc.). Ogni giocatore ha `knowledge/player_XXX.txt`.
Due manager LLM (Muse Ember) muovono gli 11 titolari in real-time; la knowledge
si aggiorna LIVE al gol e dopo ogni match collegando abilità + stats reali.

## Demo d'impatto con UI (consigliata)
```bash
cp .env.example .env   # metti la tua chiave, poi:
python3 serve.py
# apri http://localhost:8000
```
- Premi **Demo veloce** (euristica, ideale per provare il projector) o **Demo Live con Ember** (finestrella "Ember sta pensando…").
- Vedi: campo 105x68 animato, cronaca live, capocannonieri, knowledge cliccando un giocatore.
- File: `data/match_*.log` (cronaca completa), `knowledge/player_*.txt` (50 file).

## CLI
```bash
python3 app.py --matches 2 --ticks 20 --seed 1 --no-llm   # veloce
python3 app.py --matches 2 --ticks 20 --seed 1 --llm      # guidata da Ember
```
Chiave: già in `app.py` (hackathon), override con `OPENROUTER_API_KEY`. Modello: `meta/muse-ember`.
