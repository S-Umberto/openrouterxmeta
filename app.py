#!/usr/bin/env python3
"""
Simulatore di calcio: 50 giocatori guidati in tempo reale da Muse Ember via OpenRouter.
Uso:
  python app.py --matches 2 --ticks 30 --llm
  python app.py --matches 1 --ticks 30 --no-llm   (solo euristica, veloce)
"""
import argparse, json, math, os, random, sys
from pathlib import Path
import urllib.request

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
KNOW_DIR = BASE / "knowledge"
KNOW_DIR.mkdir(exist_ok=True)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# carica .env se presente (senza dipendenze esterne)
_env = BASE / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
MODEL = os.environ.get("OPENROUTER_MODEL", "meta/muse-ember")
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
STATE_PATH = DATA / "live.json"

W, H = 105.0, 68.0  # campo in metri
GOAL_Y0, GOAL_Y1 = 28.0, 40.0  # palo verticale porta (centro 34)

# ---------------- modelli ----------------
class Player:
    def __init__(self, pid, name, team, role):
        self.id, self.name, self.team, self.role = pid, name, team, role
        self.x, self.y = 0.0, 0.0
        self.stats = {"goals":0,"shots":0,"passes":0,"tackles":0,"saves":0,"assists":0}
        self.total = {"goals":0,"shots":0,"passes":0,"tackles":0,"saves":0,"assists":0}
        self.attrs = gen_attrs(role)
        self.knowledge = load_knowledge(pid, role)
    def speed(self):  # m/s ~ 3..9
        return 3.0 + (self.attrs["pace"] / 100.0) * 6.0

class Team:
    def __init__(self, name, color):
        self.name, self.color = name, color
        self.players = []
        self.score = 0
    def field(self):  # 11 titolari: 1P 4D 4C 2A
        gk = [p for p in self.players if p.role=="GK"][:1]
        df = [p for p in self.players if p.role=="DEF"][:4]
        md = [p for p in self.players if p.role=="MID"][:4]
        fw = [p for p in self.players if p.role=="FWD"][:2]
        return gk+df+md+fw

def gen_attrs(role):
    # base 30-70 poi bias per ruolo (stile FIFA)
    def b(lo=30, hi=70): return random.randint(lo, hi)
    a = {"pace":b(),"stamina":b(),"strength":b(),"agility":b(),
         "passing":b(),"shooting":b(),"dribbling":b(),"tackling":b(),
         "positioning":b(),"vision":b(),"reflexes":b()}
    bias = {
        "GK":  {"reflexes":(70,95),"positioning":(60,90),"strength":(50,80)},
        "DEF": {"tackling":(65,95),"strength":(60,90),"positioning":(55,85),"pace":(45,75),"shooting":(25,55)},
        "MID": {"passing":(65,95),"vision":(60,90),"stamina":(60,90),"shooting":(50,75)},
        "FWD": {"shooting":(65,97),"pace":(60,92),"dribbling":(60,90),"agility":(60,90),"tackling":(20,45),"strength":(40,75)},
    }[role]
    for k,(lo,hi) in bias.items():
        a[k] = random.randint(lo,hi)
    for k in a: a[k] = max(1, min(99, a[k]))
    return a

NAMES = ["Rossi","Bianchi","Verdi","Conti","Marino","Greco","Fontana","Costa","Pinto","Leone",
         "Santos","Kane","Muller","Weber","Dubois","Navarro","Silva","Moreau","Fischer","Petrov"]

def make_teams(seed=0):
    random.seed(seed)
    teams = [Team("Azzurri","#3eb7ff"), Team("Rossi","#ff5a5a")]
    roles = (["GK"]*3 + ["DEF"]*8 + ["MID"]*8 + ["FWD"]*6)
    pid = 0
    for ti, t in enumerate(teams):
        for role in roles:
            name = f"{random.choice(NAMES)} #{pid}"
            t.players.append(Player(pid, name, ti, role))
            pid += 1
    return teams

def home_pos(p, xi):
    # xi: indice nella formazione 11 (0=portiere ... 10=attacco)
    # team 0 attacca a destra (+x), team 1 a sinistra
    # formazione 4-4-2
    f = [(4,34),(18,14),(14,28),(14,40),(18,54),
         (38,14),(32,28),(32,40),(38,54),(68,26),(68,42)][xi]
    if p.team == 1:
        f = (W - f[0], H - f[1])
    return f

# ---------------- knowledge ----------------
BASE_K = {
 "GK":"- Resta sulla linea di porta, non uscire senza motivo.\n- Se l'attaccante e' vicino, resta in piedi finche' non tira.\n- Parla con i difensori: comunica la posizione.",
 "DEF":"- Quando sei in area, resta tra pallone e porta.\n- Avvicinati al portatore avversario quando ha la palla.\n- Non fare fallo in area, cerca la scivolata solo se sicuro.",
 "MID":"- Cerca di posizionarti in zone libere del campo.\n- Avvicinati al tuo compagno quando ha la palla per dargli appoggio.\n- Controlla la partita: se il pallone e' lontano, torna al tuo posto.",
 "FWD":"- Quando sei in area tira.\n- Cerca di posizionarti in zone libere del campo.\n- Avvicinati al tuo compagno quando ha la palla.\n- Se sei senza palla, cerca la profondita' alle spalle dei difensori."}

def load_knowledge(pid, role):
    f = KNOW_DIR / f"player_{pid:03d}.txt"
    if f.exists(): return f.read_text(encoding="utf-8").strip()
    t = BASE_K[role]
    f.write_text(t, encoding="utf-8")
    return t

def save_knowledge(pid, text):
    (KNOW_DIR / f"player_{pid:03d}.txt").write_text(text.strip(), encoding="utf-8")

# ---------------- LLM (OpenRouter) ----------------
def llm_call(system, user, max_tokens=4000):
    if not API_KEY: return None
    body = json.dumps({"model":MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],
                       "temperature":0.7,"max_tokens":max_tokens}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}", "Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [LLM] errore: {e}")
        return None

def parse_json(text):
    if text is None: return None
    try:
        s = text[text.index("{"):text.rindex("}")+1]
        return json.loads(s)
    except Exception:
        return None

def llm_team_decide(team, opp, ball, tick, use_heu):
    """Un manager LLM per team: muove tutti gli 11 titolari. Ritorna dict pid->decisione."""
    xi = {p.id:i for i,p in enumerate(team.field())}
    lines = []
    for p in team.field():
        a = p.attrs
        lines.append(f"{p.id} {p.role} pos=({p.x:.0f},{p.y:.0f}) pace{a['pace']} tir{a['shooting']} pas{a['passing']} dri{a['dribbling']} tac{a['tackling']} | {p.knowledge[:120].replace(chr(10),' / ')}")
    prompt = (f"Tick {tick}. Palla ({ball['x']:.0f},{ball['y']:.0f}) owner={ball['owner']}. "
              f"Attacchi verso {'destra +x' if team.players[0].team==0 else 'sinistra -x'}. "
              f"Punteggio A {teams[0].score if 'teams' in globals() else '?'} - R {teams[1].score if 'teams' in globals() else '?'}\n"
              f"SQUADRA {team.name} (manager: dai la strategia, equilibrio attacco/difesa):\n" + "\n".join(lines) +
              f"\nRispondi SOLO JSON: {{\"balance\":0-100,\"moves\":{{\"pid\":{{\"tx\":0-105,\"ty\":0-68,\"act\":\"move|pass|shoot|dribble|tackle\"}}}}}}")
    sysp = ("Sei il manager di calcio. Muovi ogni titolare verso (tx,ty) compatibile con ruolo e "
            "abilità (gli attaccanti tirano forte e con precisione, i difensori placcano). "
            "Se un tuo giocatore ha la palla (owner=pid) usa pass/shoot/dribble.")
    raw = llm_call(sysp, prompt, max_tokens=6000)
    d = parse_json(raw)
    if d and isinstance(d.get("moves"), dict):
        return d["moves"], d.get("balance", 50)
    return heuristic_decide(team, opp, ball), 50

def heuristic_decide(team, opp, ball):
    """Fallback senza LLM: home + pressione/distanza + azione portatore."""
    moves = {}
    fld = team.field()
    for i,p in enumerate(fld):
        hx, hy = home_pos(p, i)
        # la squadra si sposta col pallone
        k = 0.5 if p.team==0 else 0.5
        tx, ty = hx + (ball["x"]-W/2)*k, hy + (ball["y"]-H/2)*k
        act = "move"
        if ball["owner"] == p.id:
            gx = W if p.team==0 else 0
            d = math.hypot(gx-p.x, 34-p.y)
            act = "shoot" if d < 30 else ("dribble" if random.random()<0.6 else "pass")
        elif p.role != "GK" and math.hypot(ball["x"]-p.x, ball["y"]-p.y) < 9:
            act = "tackle"
        moves[str(p.id)] = {"tx":max(0,min(W,tx)),"ty":max(0,min(H,ty)),"act":act}
    return moves

# ---------------- fisica / risoluzione ----------------
def move_toward(p, tx, ty, dt=2.0):
    dx, dy = tx-p.x, ty-p.y
    d = math.hypot(dx,dy)
    if d < 0.5: return
    s = min(d, p.speed()*dt*(0.7+0.3*p.attrs["stamina"]/99))
    p.x += dx/d*s; p.y += dy/d*s

def resolve(ball, allf, teams, log):
    """Risolvi pass/shoot/dribble/tackle con probabilita' basata sulle abilita'."""
    owner = next((p for p in allf if p.id==ball["owner"]), None)
    # portatore avanza
    if owner is not None:
        pass
    act = ball.get("next_act","move")
    if owner is not None and act == "shoot":
        gx = W if owner.team==0 else 0
        dist = math.hypot(gx-owner.x, 34-owner.y)
        err = (99-owner.attrs["shooting"])/99*18 + dist*0.12
        ty = 34 + random.uniform(-err,err)
        owner.stats["shots"] += 1
        log.append(f"  Tiro di {owner.name} da {dist:.0f}m")
        if GOAL_Y0 <= ty <= GOAL_Y1:
            gk = teams[1-owner.team].field()[0]
            save_p = (gk.attrs["reflexes"]/99)*0.5 + (gk.attrs["positioning"]/99)*0.3
            if random.random() < save_p*0.6 and dist < 25:
                gk.stats["saves"] += 1
                log.append(f"  PARATA di {gk.name}! (riflessi {gk.attrs['reflexes']})")
                ball["owner"] = None; ball["x"], ball["y"] = gk.x, gk.y
            else:
                teams[owner.team].score += 1
                owner.stats["goals"] += 1
                # knowledge aggiornata LIVE durante il match in base a abilita' + risultato
                if owner.attrs["shooting"] >= 70:
                    live = f"Tira spesso da fuori area: il tuo tiro e' {owner.attrs['shooting']}, hai segnato {owner.stats['goals']} goal."
                else:
                    live = f"Colpiscila vicino alla porta: il tuo tiro e' {owner.attrs['shooting']}, cerca spazi stretti."
                owner.knowledge = owner.knowledge + "\n" + live
                save_knowledge(owner.id, owner.knowledge)
                log.append(f"  GOOOL di {owner.name} ({teams[owner.team].name} {teams[0].score}-{teams[1].score} {teams[1].name})!")
                kickoff(ball, teams)
        else:
            log.append(f"  Fuori (ty={ty:.0f}).")
            ball["owner"] = None
        ball["next_act"]="move"
    elif owner is not None and act == "pass":
        mates = [p for p in allf if p.team==owner.team and p.id!=owner.id]
        ok = random.random() < owner.attrs["passing"]/100*0.8+0.2
        tgt = min(mates, key=lambda p: math.hypot(p.x-owner.x,p.y-owner.y))
        if ok:
            tgt.stats["passes"] += 1; owner.stats["passes"] += 1
            ball["owner"], ball["x"], ball["y"] = tgt.id, tgt.x, tgt.y
            log.append(f"  Passaggio {owner.name} -> {tgt.name}")
        else:
            # intercetto
            opps = [p for p in allf if p.team!=owner.team]
            tgt2 = min(opps, key=lambda p: math.hypot(p.x-owner.x,p.y-owner.y))
            tgt2.stats["tackles"] += 1
            ball["owner"], ball["x"], ball["y"] = tgt2.id, tgt2.x, tgt2.y
            log.append(f"  Intercetto! {owner.name} perde palla ({owner.attrs['passing']} passing).")
        ball["next_act"]="move"
    elif owner is not None and act == "dribble":
        opp = min([p for p in allf if p.team!=owner.team], key=lambda p: math.hypot(p.x-owner.x,p.y-owner.y))
        d = math.hypot(opp.x-owner.x, opp.y-owner.y)
        if d < 6 and random.random() > owner.attrs["dribbling"]/99*0.7:
            opp.stats["tackles"] += 1
            ball["owner"], ball["x"], ball["y"] = opp.id, opp.x, opp.y
            log.append(f"  Placcato! {opp.name} ruba a {owner.name}.")
        else:
            gx = W if owner.team==0 else 0
            owner.x += (1 if owner.team==0 else -1)*3.0
            log.append(f"  Dribbling di {owner.name}.")
        ball["next_act"]="move"
    # tackle di chi e' vicino alla palla
    for p in allf:
        if ball["owner"] is not None and p.id != ball["owner"] and p.team != (next((q.team for q in allf if q.id==ball["owner"]),None)):
            if math.hypot(ball["x"]-p.x, ball["y"]-p.y) < 3.0 and random.random() < p.attrs["tackling"]/99*0.4:
                ball["owner"] = p.id
                log.append(f"  Tackle di {p.name}!")
                break

def kickoff(ball, teams):
    ball["x"], ball["y"], ball["owner"] = W/2, H/2, None
    for t in teams:
        for i,p in enumerate(t.field()):
            p.x, p.y = home_pos(p, i)
    # assegna palla a un centrocampista della squadra che ha subito?
    mids = [p for t in teams for p in t.field() if p.role=="MID"]
    if mids:
        m = random.choice(mids); ball["owner"]=m.id; ball["x"],ball["y"]=m.x,m.y

# ---------------- evoluzione knowledge ----------------
def evolve_knowledge(teams, use_llm):
    for team in teams:
        for p in team.players:
            s = p.stats; a = p.attrs
            # fallback euristico (abilita' -> consiglio)
            tips = []
            if s["goals"]>=1 and a["shooting"]>=70: tips.append(f"Tira spesso da fuori area: il tuo tiro e' {a['shooting']}, hai segnato {s['goals']} goal.")
            if s["shots"]>=3 and s["goals"]==0 and a["shooting"]<60: tips.append("Devi migliorare il tiro: porta palla piu' vicino alla porta prima di tirare.")
            if s["tackles"]>=2 and a["tackling"]>=70: tips.append("Pressa forte: il tuo placcaggio funziona, vai sul portatore.")
            if s["saves"]>=1: tips.append(f"Resta sulla linea: hai gia' {s['saves']} parate.")
            if s["passes"]>=4 and a["passing"]>=70: tips.append("Dai appoggio in costruzione: il tuo passaggio e' preciso.")
            if tips:
                p.knowledge = p.knowledge + "\n" + "\n".join(tips)
                save_knowledge(p.id, p.knowledge)
            elif use_llm:
                # LLM solo per chi non ha segnali: breve arricchimento
                pass
    if use_llm:
        # un LLM batch per team per ristrutturare le knowledge
        for team in teams:
            chunks = []
            for p in team.players:
                chunks.append(f"{p.id} {p.role} tir{a_str(p)} stats={p.stats} know:{p.knowledge[:200]}")
            raw = llm_call("Sei un allenatore. Riscrivi la knowledge di ogni giocatore in 2-4 righe, collegando consigli e abilita'/stats reali.",
                           f"Squadra {team.name}:\n" + "\n".join(chunks) +
                           "\nRispondi SOLO JSON: {\"k\":{\"pid\":\"testo knowledge\"}}", max_tokens=8000)
            d = parse_json(raw)
            if d and isinstance(d.get("k"), dict):
                pm = {p.id:p for p in team.players}
                for k,v in d["k"].items():
                    try: pm[int(k)].knowledge = str(v)[:600]; save_knowledge(int(k), str(v)[:600])
                    except Exception: pass

def a_str(p): return f"tir{p.attrs['shooting']} pas{p.attrs['passing']} pace{p.attrs['pace']}"

# ---------------- match ----------------
def snapshot(teams, ball, tick, events, mnum, think=False):
    """Stato per la UI: posizioni + punteggio + knowledge titolari."""
    players = []
    for t in teams:
        for p in t.field():
            players.append({"id":p.id,"name":p.name,"team":p.team,"role":p.role,
                            "x":round(p.x,1),"y":round(p.y,1),"has":(ball.get("owner")==p.id),
                            "know":p.knowledge[:500],
                            "attrs":{"tir":p.attrs["shooting"],"pas":p.attrs["passing"],"vel":p.attrs["pace"]}})
    scorers = sorted([p for t in teams for p in t.players], key=lambda p:-p.total["goals"])[:5]
    STATE_PATH.write_text(json.dumps({
        "tick":tick,"mnum":mnum,"think":think,"score":[teams[0].score, teams[1].score],
        "teams":[teams[0].name, teams[1].name],"ball":{"x":round(ball["x"],1),"y":round(ball["y"],1),"owner":ball.get("owner")},
        "players":players,"events":events[-14:],
        "scorers":[{"name":p.name,"role":p.role,"goals":p.total["goals"]} for p in scorers],
    }, ensure_ascii=False), encoding="utf-8")

def play_match(teams, ticks, use_llm, mnum):
    for t in teams: t.score = 0
    ball = {"x":W/2, "y":H/2, "owner":None, "next_act":"move"}
    for t in teams:
        for i,p in enumerate(t.field()):
            p.x, p.y = home_pos(p, i)
    for t in teams:
        for p in t.players: p.stats = {"goals":0,"shots":0,"passes":0,"tackles":0,"saves":0,"assists":0}
    kickoff(ball, teams)
    log = [f"=== Match {mnum}: {teams[0].name} vs {teams[1].name} (LLM={'sì' if use_llm else 'no'}, tick={ticks}) ==="]
    allf = teams[0].field() + teams[1].field()
    for tick in range(1, ticks+1):
        snapshot(teams, ball, tick, log, mnum, think=(use_llm and tick % 3 == 0))
        if use_llm and tick % 3 == 0:  # LLM ogni 3 tick, euristica negli altri: piu' veloce ed economico
            m0,_ = llm_team_decide(teams[0], teams[1], ball, tick, True)
            m1,_ = llm_team_decide(teams[1], teams[0], ball, tick, True)
            moves = {**m0, **m1}
        else:
            moves = {**heuristic_decide(teams[0], teams[1], ball), **heuristic_decide(teams[1], teams[0], ball)}
        # palla libera (rimessa laterale / rinvio semplificati): il più vicino la raccoglie
        if ball["owner"] is None:
            nearest = min(allf, key=lambda p: math.hypot(p.x-ball["x"], p.y-ball["y"]))
            ball["owner"], ball["x"], ball["y"] = nearest.id, nearest.x, nearest.y
            ball["next_act"] = "dribble" if nearest.role != "GK" else "pass"
            log.append(f"  Rimessa/riconquista: la raccoglie {nearest.name}")
        for p in allf:
            mv = moves.get(str(p.id), {})
            move_toward(p, float(mv.get("tx", p.x)), float(mv.get("ty", p.y)))
            if ball["owner"] == p.id:
                ball["next_act"] = mv.get("act","move")
                ball["x"], ball["y"] = p.x, p.y
        # fuori campo laterale -> torna dentro (fallo laterale semplificato)
        if ball["y"] < 0 or ball["y"] > H:
            ball["y"] = max(0.0, min(float(H), ball["y"]))
            log.append("  Fallo laterale (palla rimessa in campo).")
        resolve(ball, allf, teams, log)
        log.append(f"tick {tick}: palla ({ball['x']:.0f},{ball['y']:.0f}) owner={ball['owner']} | {teams[0].score}-{teams[1].score}")
        snapshot(teams, ball, tick, log, mnum, think=False)
    log.append(f"FINALE Match {mnum}: {teams[0].name} {teams[0].score} - {teams[1].score} {teams[1].name}")
    for t in teams:  # cumulativo tra match
        for p in t.players:
            for k in p.total: p.total[k] += p.stats.get(k, 0)
    return "\n".join(log)

def main():
    global teams
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=2)
    ap.add_argument("--ticks", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--llm", action="store_true", default=True)
    ap.add_argument("--no-llm", dest="llm", action="store_false")
    args = ap.parse_args()
    if args.llm and not API_KEY:
        print("OPENROUTER_API_KEY mancante: settala con export OPENROUTER_API_KEY=sk-or-... (oppure usa --no-llm)")
        sys.exit(1)
    teams = make_teams(args.seed)
    print(f"50 giocatori creati (2x 3P/8D/8C/6A). Knowledge in {KNOW_DIR}")
    for p in teams[0].players[:3]+teams[1].players[:3]:
        print(f"  {p.name} {p.role} {p.attrs}")
    full = []
    for m in range(1, args.matches+1):
        out = play_match(teams, args.ticks, args.llm, m)
        print(out); full.append(out)
        DATA.joinpath(f"match_{m}.log").write_text(out, encoding="utf-8")
        evolve_knowledge(teams, args.llm)
        print("--- Knowledge aggiornata (emergono abilita': fuori area, pressione, appoggio...) ---")
    # riepilogo marcatori
    print("=== Classifica marcatori (tutti i match) ===")
    allp = sorted(teams[0].players+teams[1].players, key=lambda p: -p.total["goals"])
    for p in allp[:10]: print(f"  {p.name} {p.role} goals={p.total['goals']} shots={p.total['shots']} passes={p.total['passes']} tackles={p.total['tackles']} saves={p.total['saves']}")

if __name__ == "__main__":
    main()
