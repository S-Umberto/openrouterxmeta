# ⚽ Ember Football Simulator

**50 giocatori di calcio vivi, guidati in tempo reale da Muse Ember.**

Per il **$1 Challenge** (OpenRouter × Meta Build Day): un simulatore dove ogni azione sul campo esiste solo perché `meta/muse-ember` la decide, la motiva e poi la impara. Costo di una demo completa: centesimi.

## L'idea in 20 secondi

Generiamo 50 calciatori random (2 rose da 3P/8D/8C/6A) con tratti in stile FIFA — l'attaccante tira più forte e più preciso del difensore, il portiere para con i riflessi, ecc. Ogni giocatore nasce con una *knowledge* testuale ("quando sei in area tira", "cerca zone libere", "dai appoggio al portatore").

Durante la partita **due manager Muse Ember** vedono la partita in real-time e decidono i movimenti di tutti gli 11 titolari + l'azione del portatore (passo / tiro / dribbling / placcaggio). L'esito è calcolato in Python dalle abilità, così la tecnica conta davvero. Al gol la knowledge del marcatore si aggiorna **subito** in base ad abilità + risultato (chi ha tiro 90+ impara a "tirare spesso da fuori area"), e dopo ogni match Ember riscrive le 50 knowledge collegando abilità e stats reali. Giochi più match → i giocatori e le squadre evolvono.

## Perché è diverso

- **LLM come cervello distribuito, non come chatbot.** Non parli con il modello: lo incarni in 50 corpi. Ogni tick è una decisione tattica reale, il resto è una chat.
- **Apprendimento emergente.** Nessuna regola hard-coded dice "tira da fuori area": emerge dal loop abilità → risultato → knowledge.
- **Interamente dimostrabile in 1 minuto.** UI live con campo, cronaca e knowledge cliccabile. Vedi l'evoluzione mentre giochi.

## Demo (1 minuto, per il video)

```bash
cp .env.example .env    # la tua OpenRouter key
python3 serve.py        # http://localhost:8000
```

1. Premi **Demo veloce** (euristica) → partono 2 match live: gol, parate, cronaca.
2. Clicca un marcatore → vedi la knowledge che ha imparato dal gol.
3. Premi **Demo Live con Ember** → compare "Ember sta pensando…", il manager LLM guida il match.

## Come è fatto

| Parte | File |
|---|---|
| Motore + tratti FIFA-style + fisica probabilistica | `app.py` |
| UI live (campo animato, cronaca, knowledge) | `index.html` |
| Server demo (solo stdlib) | `serve.py` |
| Log match | `data/match_*.log` (git-ignorati) |
| Knowledge 50 giocatori | `knowledge/player_*.txt` (git-ignorati) |

**Uso dell'LLM (requisito showcase):** ogni decisione tattica passa da `POST https://openrouter.ai/api/v1/chat/completions` con modello `meta/muse-ember`. Il manager riceve stato campo + abilità + knowledge + punteggio e risponde solo JSON con le destinazioni di tutti i titolari. Strategia economica: LLM ogni 3 tick, euristica nei tick intermedi → ~1/3 delle chiamate, stesso spettacolo.

**CLI (per iterare senza UI):**
```bash
python3 app.py --matches 2 --ticks 20 --seed 1 --no-llm   # veloce
python3 app.py --matches 2 --ticks 20 --seed 1 --llm      # guidata da Ember
```

## Note per la giuria

- **≤$1:** simulazioni a pochi tick costano pochi centesimi; il progetto gira anche senza LLM grazie all'euristica di fallback.
- **Limiti onesti:** calcio semplificato (niente falli, fuori gioco o panchina persistente; 11 titolari scelti per ruolo); risoluzione tiri/passaggi probabilistica; `meta/muse-ember` usa molto reasoning, servono `max_tokens ≥ 4000` (già gestito).
- **Team/credits:** modello `meta/muse-ember` via OpenRouter; OpenRouter user ID e demo video da aggiungere alla submission su Cerebral Valley.

## Licenza / hackathon

Build Day: libero per dimostrazione e riuso didattico. Non includere mai `.env` nei commit (già in `.gitignore`).
