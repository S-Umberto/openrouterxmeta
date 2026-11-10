#!/usr/bin/env python3
"""
Simulatore di calcio: 50 giocatori guidati in tempo reale da Muse Ember via OpenRouter.
Uso:
  python app.py --matches 2 --ticks 30 --llm
  python app.py --matches 1 --ticks 30 --no-llm   (solo euristica, veloce)
"""
import argparse, json, math, os, random, sys, time
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
        # evidenze per la memoria (tentativi + esiti, mai percentuali su zero tentativi)
        self.ev = {"long_att":0,"long_scored":0,"close_att":0,"close_scored":0,
                   "pass_att":0,"pass_ok":0,"last_dist":0}
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
    # memoria persistita per roster: se cambia il seed, i vecchi consigli non si riusano
    seed_file = KNOW_DIR / "roster_seed.txt"
    if not seed_file.exists() or seed_file.read_text(encoding="utf-8").strip() != str(seed):
        for pid, role in enumerate(roles*2):
            save_knowledge(pid, BASE_K[role])
        seed_file.write_text(str(seed), encoding="utf-8")
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

def add_tip(player, tip, source="evidence"):
    """Memoria compatta: max 3 consigli attivi, etichettati per fonte."""
    lines = [t.strip() for t in player.knowledge.splitlines() if t.strip()]
    # rimuovi duplicati esatti, tieni gli ultimi 3
    if tip not in lines:
        lines.append(f"[{source}] {tip}")
    player.knowledge = "\n".join(lines[-3:])
    save_knowledge(player.id, player.knowledge)

# ---------------- LLM (OpenRouter) ----------------
# contatore API: la chiamata costa anche se il JSON non viene parsato
API_STATS = {"calls":0,"succeeded":0,"failed":0,"cost_usd":0.0,"cost_partial":False,
             "prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"latency_s":0.0}
RUN_ID = 0
PHASE = "idle"
MODE = "fast"
LAST_ERROR = ""
LAST_STRATEGIES = {}
LAST_SOURCES = {}
CURRENT_RUN = [0]

def record_llm(res):
    API_STATS["calls"] += 1
    API_STATS["latency_s"] += res.get("latency_s", 0.0)
    usage = res.get("usage") or {}
    for k in ("prompt_tokens","completion_tokens","total_tokens"):
        if isinstance(usage.get(k), (int, float)):
            API_STATS[k] += int(usage[k])
    if usage.get("cost") is not None and isinstance(usage.get("cost"), (int, float)):
        API_STATS["cost_usd"] += float(usage["cost"])
    else:
        API_STATS["cost_partial"] = True
    if res.get("error"):
        API_STATS["failed"] += 1
    if res.get("parsed_ok"):
        API_STATS["succeeded"] += 1

def llm_call(system, user, max_tokens=4000, cancel=None):
    """Ritorna dict {text, usage, id, latency_s, error, parsed_ok}."""
    if not API_KEY:
        return {"text":None,"error":"missing API key","latency_s":0.0}
    body = json.dumps({"model":MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],
                       "temperature":0.7,"max_tokens":max_tokens}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}", "Content-Type":"application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode())
        text = payload["choices"][0]["message"].get("content")
        return {"text":text,"usage":payload.get("usage"),"id":payload.get("id"),
                "latency_s":time.time()-t0,"error":"" if text else "empty content"}
    except Exception as e:
        return {"text":None,"error":f"{type(e).__name__}: {e}"[:200],"latency_s":time.time()-t0}

def parse_json(text):
    if text is None: return None
    try:
        s = text[text.index("{"):text.rindex("}")+1]
        return json.loads(s)
    except Exception:
        return None

ALLOWED_ACTS = ("move","pass","shoot","dribble","tackle")

def validate_moves(team, raw_moves, ball):
    """Valida le mosse LLM: None se inutilizzabile, altrimenti moves complete per gli 11 titolari."""
    if not isinstance(raw_moves, dict):
        return None
    own_ids = {p.id for p in team.field()}
    heuristics = heuristic_decide(team, None, ball)
    clean = {}
    for k, v in raw_moves.items():
        try:
            pid = int(k)
        except (TypeError, ValueError):
            continue
        if pid not in own_ids or not isinstance(v, dict):
            continue
        try:
            tx, ty = float(v.get("tx")), float(v.get("ty"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(tx) and math.isfinite(ty)):
            continue
        act = v.get("act", "move")
        if act not in ALLOWED_ACTS:
            continue
        entry = {"tx":max(0.0,min(W,tx)), "ty":max(0.0,min(H,ty)), "act":act}
        if act == "pass":
            try:
                tid = int(v.get("target_id"))
            except (TypeError, ValueError):
                tid = None
            if tid is not None and tid in own_ids and tid != ball.get("owner"):
                entry["target_id"] = tid
        clean[pid] = entry
    if not clean:
        return None
    merged = {}
    for pid in sorted(own_ids):
        merged[str(pid)] = clean.get(pid, heuristics[str(pid)])
    return merged, len(clean)

def llm_team_decide(team, opp, ball, tick, state):
    """Un manager LLM per team: contesto completo, risposta validata. Ritorna (moves, strategy, source)."""
    global LAST_ERROR
    score = state.get("score", [0,0]) if isinstance(state, dict) else [0,0]
    team_lines = []
    for p in team.field():
        a = p.attrs
        mem = p.knowledge.replace("\n", " / ")  # max 3 consigli salvati, inviati per intero
        team_lines.append(f"{p.id} {p.role} pos=({p.x:.0f},{p.y:.0f}) tir{a['shooting']} pas{a['passing']} dri{a['dribbling']} tac{a['tackling']} vel{a['pace']} | {mem}")
    opp_lines = [f"{p.id} {p.role} pos=({p.x:.0f},{p.y:.0f})" for p in opp.field()]
    ex = '{"strategy":"one short tactical line","moves":{"pid":{"tx":50,"ty":34,"act":"move","target_id":0}}}'
    prompt = (f"Tick {tick}. Field 105x68. Ball ({ball['x']:.0f},{ball['y']:.0f}) owner={ball['owner']}. "
              f"Score {score[0]}-{score[1]}. You attack {'right (+x)' if team.players[0].team==0 else 'left (-x)'}.\n"
              f"YOUR TEAM {team.name} (11 starters, id role pos tir pas dri tac vel | memory):\n" + "\n".join(team_lines) +
              f"\nOPPONENTS (11):\n" + "\n".join(opp_lines) +
              f"\nReply ONLY JSON exactly like: {ex} "
              "One move for every starter ID above. act must be move|pass|shoot|dribble|tackle. Use target_id (teammate) only for pass.")
    sysp = ("You are a football manager. Move each of your 11 starters to (tx,ty) compatible with role and abilities "
            "(forwards shoot strongly and accurately, defenders tackle). If one of your players has the ball (owner=pid) "
            "use pass with target_id (a teammate, not yourself), shoot or dribble.")
    res = llm_call(sysp, prompt, max_tokens=6000)
    d = parse_json(res.get("text"))
    res["parsed_ok"] = d is not None and isinstance(d.get("moves"), dict)
    record_llm(res)
    if res.get("error"):
        LAST_ERROR = res["error"][:120]
    if d and isinstance(d.get("moves"), dict):
        validated = validate_moves(team, d["moves"], ball)
        if validated is not None:
            merged, n_valid = validated
            strategy = str(d.get("strategy", ""))[:140]
            total = len(team.field())
            if n_valid == total:
                LAST_STRATEGIES[team.name] = strategy
                LAST_SOURCES[team.name] = "Ember"
                return merged, strategy, "Ember"
            LAST_STRATEGIES[team.name] = "(partial Ember: " + str(n_valid) + "/" + str(total) + " valid, rest heuristic) " + strategy
            LAST_SOURCES[team.name] = "Mixed"
            return merged, LAST_STRATEGIES[team.name], "Mixed"
    # fallback esplicito, mai spacciato per Ember
    LAST_STRATEGIES[team.name] = "Fallback heuristic (Ember error or invalid JSON)"
    LAST_SOURCES[team.name] = "Fallback"
    return heuristic_decide(team, opp, ball), LAST_STRATEGIES[team.name], "Fallback"

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
        entry = {"tx":max(0,min(W,tx)),"ty":max(0,min(H,ty)),"act":act}
        if act == "pass":  # euristico: compagno vicino come target
            mates = [q for q in fld if q.id != p.id]
            nearest = min(mates, key=lambda q: math.hypot(q.x-p.x,q.y-p.y))
            entry["target_id"] = nearest.id
        moves[str(p.id)] = entry
    return moves

# ---------------- fisica / risoluzione ----------------
def move_toward(p, tx, ty, dt=2.0):
    dx, dy = tx-p.x, ty-p.y
    d = math.hypot(dx,dy)
    if d < 0.5: return
    s = min(d, p.speed()*dt*(0.7+0.3*p.attrs["stamina"]/99))
    p.x += dx/d*s; p.y += dy/d*s

def resolve(ball, allf, teams, log, moves=None, was_goal=None):
    """Risolvi pass/shoot/dribble con probabilita' basata sulle abilita'. Ritorna True se gol."""
    owner = next((p for p in allf if p.id==ball["owner"]), None)
    act = ball.get("next_act","move")
    moves = moves or {}
    def clamp_ball():
        for p in allf:
            p.x = max(0.0, min(W, p.x)); p.y = max(0.0, min(H, p.y))
        ball["x"] = max(0.0, min(W, ball["x"])); ball["y"] = max(0.0, min(H, ball["y"]))
        cur = next((p for p in allf if p.id==ball.get("owner")), None)
        if cur is not None:
            ball["x"], ball["y"] = cur.x, cur.y
    if owner is not None and act == "shoot":
        gx = W if owner.team==0 else 0
        dist = math.hypot(gx-owner.x, 34-owner.y)
        owner.stats["shots"] += 1
        owner.ev["last_dist"] = int(dist)
        long_shot = dist >= 20
        (owner.ev.__setitem__("long_att", owner.ev["long_att"]+1) if long_shot
         else owner.ev.__setitem__("close_att", owner.ev["close_att"]+1))
        # on target decresce con la distanza (anche oltre 20m); la parata dipende solo da portiere e tiro, non dalla distanza
        p_on = max(0.05, min(0.9, owner.attrs["shooting"]/100*0.75 + max(0, 20-dist)/100*0.25 - max(0, dist-20)*0.004))
        on_target = random.random() < p_on
        log.append(f"  Shot by {owner.name} from {dist:.0f}m (shooting {owner.attrs['shooting']}), on target: {'yes' if on_target else 'no'}")
        if on_target:
            gk = teams[1-owner.team].field()[0]
            difficulty = owner.attrs["shooting"]/99*0.3  # qualità del tiro, mai distanza
            save_p = max(0.05, min(0.75, (gk.attrs["reflexes"]/99)*0.45 + (gk.attrs["positioning"]/99)*0.3 - difficulty*0.3))
            if random.random() < save_p:
                gk.stats["saves"] += 1
                log.append(f"  SAVE by {gk.name}! (reflexes {gk.attrs['reflexes']}, save chance {save_p:.2f})")
                ball["owner"] = gk.id; ball["x"], ball["y"] = gk.x, gk.y
            else:
                teams[owner.team].score += 1
                owner.stats["goals"] += 1
                (owner.ev.__setitem__("long_scored", owner.ev["long_scored"]+1) if long_shot
                 else owner.ev.__setitem__("close_scored", owner.ev["close_scored"]+1))
                # evidenza live immediata (non un giudizio di strategia)
                side = "from distance" if long_shot else "close to goal"
                add_tip(owner, f"evidence: scored {side} from {dist:.0f}m (shots {owner.stats['shots']}, goals {owner.stats['goals']})", source="evidence")
                log.append(f"  GOAL by {owner.name} ({teams[owner.team].name} {teams[0].score}-{teams[1].score} {teams[1].name})! Memory updated.")
                kickoff(ball, teams, conceding_team=1-owner.team)
        else:
            log.append("  Off target.")
            ball["owner"] = None
        ball["next_act"]="move"
        clamp_ball()
        return True if ball.get("owner") is not None and ball["x"] == W/2 else False
    elif owner is not None and act == "pass":
        owner.ev["pass_att"] += 1
        mates = {p.id:p for p in allf if p.team==owner.team and p.id!=owner.id}
        mv = moves.get(str(owner.id), {})
        try:
            tid = int(mv.get("target_id"))
        except (TypeError, ValueError):
            tid = None
        if tid in mates:
            tgt = mates[tid]
        else:
            tgt = min(mates.values(), key=lambda p: math.hypot(p.x-owner.x,p.y-owner.y))
        d = math.hypot(tgt.x-owner.x, tgt.y-owner.y)
        p_ok = max(0.1, min(0.95, owner.attrs["passing"]/100*0.8 + 0.2 - d*0.004))
        if random.random() < p_ok:
            owner.stats["passes"] += 1; owner.ev["pass_ok"] += 1
            ball["owner"], ball["x"], ball["y"] = tgt.id, tgt.x, tgt.y
            log.append(f"  Pass {owner.name} -> {tgt.name} ({d:.0f}m)")
        else:
            opps = [p for p in allf if p.team!=owner.team]
            tgt2 = min(opps, key=lambda p: math.hypot(p.x-tgt.x,p.y-tgt.y))
            tgt2.stats["tackles"] += 1
            ball["owner"], ball["x"], ball["y"] = tgt2.id, tgt2.x, tgt2.y
            log.append(f"  Interception! {owner.name} loses the ball to {tgt2.name} (passing {owner.attrs['passing']}).")
        ball["next_act"]="move"
        clamp_ball()
    elif owner is not None and act == "dribble":
        opp = min([p for p in allf if p.team!=owner.team], key=lambda p: math.hypot(p.x-owner.x,p.y-owner.y))
        d = math.hypot(opp.x-owner.x, opp.y-owner.y)
        if d < 6 and random.random() > owner.attrs["dribbling"]/99*0.7:
            opp.stats["tackles"] += 1
            ball["owner"], ball["x"], ball["y"] = opp.id, opp.x, opp.y
            log.append(f"  Tackled! {opp.name} steals from {owner.name}.")
        else:
            owner.x += (1 if owner.team==0 else -1)*3.0
            log.append(f"  Dribble by {owner.name}.")
        ball["next_act"]="move"
        clamp_ball()
    # contrasto dichiarato: solo chi ha dichiarato "tackle" puo' placcare
    cur = next((p for p in allf if p.id==ball.get("owner")), None)
    if cur is not None:
        cands = [p for p in allf if p.team!=cur.team and moves.get(str(p.id), {}).get("act")=="tackle"]
        if cands:
            p = min(cands, key=lambda q: math.hypot(q.x-cur.x,q.y-cur.y))
            if math.hypot(ball["x"]-p.x, ball["y"]-p.y) < 3.0 and random.random() < p.attrs["tackling"]/99*0.4:
                ball["owner"] = p.id; p.stats["tackles"] += 1
                log.append(f"  Tackle by {p.name}!")
                clamp_ball()
        else:
            clamp_ball()

def kickoff(ball, teams, conceding_team=None):
    ball["x"], ball["y"], ball["owner"] = W/2, H/2, None
    for t in teams:
        for i,p in enumerate(t.field()):
            p.x, p.y = home_pos(p, i)
    # il possesso va alla squadra che ha subito (se noto), altrimenti al centro
    if conceding_team in (0, 1):
        mids = [p for p in teams[conceding_team].field() if p.role=="MID"]
        if mids:
            m = mids[0]; ball["owner"]=m.id; ball["x"],ball["y"]=m.x,m.y
    else:
        mids = [p for t in teams for p in t.field() if p.role=="MID"]
        if mids:
            m = mids[0]; ball["owner"]=m.id; ball["x"],ball["y"]=m.x,m.y

# ---------------- evoluzione knowledge ----------------
def evolve_knowledge(teams, use_llm, cancel=None):
    global LAST_ERROR
    # 1) evidenze euristiche (etichettate) per i titolari, max 3 consigli
    for team in teams:
        for p in team.field():
            s, a, e = p.stats, p.attrs, p.ev
            if e["long_att"] >= 2 and e["long_scored"] == 0 and a["shooting"] < 55:
                add_tip(p, "evidence: 0 long-range goals from {n} attempts, close the distance first".format(n=e["long_att"]), source="heuristic")
            if s["tackles"] >= 2 and a["tackling"] >= 70:
                add_tip(p, "evidence: {n} tackles this match, press the carrier".format(n=s["tackles"]), source="heuristic")
            if s["saves"] >= 1:
                add_tip(p, "evidence: {n} saves this match, stay on goal line".format(n=s["saves"]), source="heuristic")
            if e["pass_att"] >= 3 and e["pass_ok"] >= 3 and a["passing"] >= 70:
                add_tip(p, "evidence: {a}/{b} passes completed, support in build-up".format(a=e["pass_ok"], b=e["pass_att"]), source="heuristic")
    # 2) riflessione Ember: una chiamata per squadra, max 3 consigli brevi per titolare
    if use_llm:
        for team in teams:
            if cancel and cancel.is_set(): break
            chunks = []
            for p in team.field():
                chunks.append(f"{p.id} {p.role} tir{p.attrs['shooting']} pas{p.attrs['passing']} tac{p.attrs['tackling']} stats={p.stats} ev={p.ev} memory:{p.knowledge}")
            res = llm_call("You are a coach. Give each starter at most 3 short tips linked to their evidence. One match does not prove an optimal strategy. Bench players are excluded.",
                           f"Team {team.name}:\n" + "\n".join(chunks) +
                           "\nReply ONLY JSON: {\"k\":{\"pid\":\"tip1\\ntip2\"}}", max_tokens=8000, cancel=cancel)
            d = parse_json(res.get("text"))
            res["parsed_ok"] = d is not None and isinstance(d.get("k"), dict)
            record_llm(res)
            if res.get("error"):
                LAST_ERROR = res["error"][:120]
            if d and isinstance(d.get("k"), dict):
                pm = {p.id:p for p in team.field()}  # riserve: memoria precedente conservata
                for k, v in d["k"].items():
                    try:
                        pid = int(k)
                    except (TypeError, ValueError):
                        continue
                    if pid not in pm:
                        continue
                    tips = [t.strip() for t in str(v).splitlines() if t.strip()][:3]
                    if tips:
                        pm[pid].knowledge = "\n".join("[" + "Ember" + "] " + t for t in tips)
                        save_knowledge(pid, pm[pid].knowledge)

def a_str(p): return f"tir{p.attrs['shooting']} pas{p.attrs['passing']} pace{p.attrs['pace']}"

# ---------------- match ----------------
def snapshot(teams, ball, tick, events, mnum, think=False):
    """Stato per la UI: posizioni + punteggio + knowledge titolari. Scrittura atomica."""
    players = []
    for t in teams:
        for p in t.field():
            players.append({"id":p.id,"name":p.name,"team":p.team,"role":p.role,
                            "x":round(p.x,1),"y":round(p.y,1),"has":(ball.get("owner")==p.id),
                            "know":p.knowledge,
                            "attrs":{"tir":p.attrs["shooting"],"pas":p.attrs["passing"],"vel":p.attrs["pace"]}})
    scorers = sorted([p for t in teams for p in t.players], key=lambda p:-p.total["goals"])[:5]
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "tick":tick,"mnum":mnum,"think":think,"run_id":CURRENT_RUN[0],"phase":PHASE,"mode":MODE,
        "last_error":LAST_ERROR,"strategies":dict(LAST_STRATEGIES),"sources":dict(LAST_SOURCES),
        "api":dict(API_STATS),
        "score":[teams[0].score, teams[1].score],
        "teams":[teams[0].name, teams[1].name],"ball":{"x":round(ball["x"],1),"y":round(ball["y"],1),"owner":ball.get("owner")},
        "players":players,"events":events[-14:],
        "scorers":[{"name":p.name,"role":p.role,"goals":p.total["goals"]} for p in scorers],
    }, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)

def play_match(teams, ticks, use_llm, mnum, cancel=None, delay=0.0):
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
        if cancel and cancel.is_set():
            log.append(f"Stopped at tick {tick}")
            break
        thinking = use_llm and (tick == 1 or tick % 3 == 0)  # prima decisione live al tick 1
        snapshot(teams, ball, tick, log, mnum, think=thinking)
        state = {"score":[teams[0].score, teams[1].score]}
        if thinking:  # due manager sullo stesso snapshot, prima di muovere chiunque
            m0,_,s0 = llm_team_decide(teams[0], teams[1], ball, tick, state)
            m1,_,s1 = llm_team_decide(teams[1], teams[0], ball, tick, state)
            moves = {**m0, **m1}
            log.append(f"  Manager {teams[0].name}: {s0}")
            log.append(f"  Manager {teams[1].name}: {s1}")
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
            try:
                tx, ty = float(mv.get("tx", p.x)), float(mv.get("ty", p.y))
                if not (math.isfinite(tx) and math.isfinite(ty)):
                    tx, ty = p.x, p.y
            except (TypeError, ValueError):
                tx, ty = p.x, p.y
            move_toward(p, max(0.0, min(W, tx)), max(0.0, min(H, ty)))
            p.x = max(0.0, min(W, p.x)); p.y = max(0.0, min(H, p.y))
        # sincronizza la palla con il possessore (invariante di fine tick)
        cur = next((p for p in allf if p.id==ball.get("owner")), None)
        if cur is not None:
            ball["next_act"] = moves.get(str(cur.id), {}).get("act","move")
            ball["x"], ball["y"] = cur.x, cur.y
            if ball["next_act"] not in ALLOWED_ACTS:
                ball["next_act"] = "move"
        resolve(ball, allf, teams, log, moves=moves)
        log.append(f"tick {tick}: palla ({ball['x']:.0f},{ball['y']:.0f}) owner={ball['owner']} | {teams[0].score}-{teams[1].score}")
        snapshot(teams, ball, tick, log, mnum, think=False)
        if delay and not (cancel and cancel.is_set()):
            time.sleep(delay)
    log.append(f"FINALE Match {mnum}: {teams[0].name} {teams[0].score} - {teams[1].score} {teams[1].name}")
    for t in teams:  # cumulativo tra match
        for p in t.players:
            for k in p.total: p.total[k] += p.stats.get(k, 0)
    snapshot(teams, ball, ticks, log, mnum, think=False)
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
