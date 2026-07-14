"""Génère le notebook NanoGPT."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "JENNY_NanoGPT_FromScratch.ipynb"

# une cellule = (type, source)
CELLS: list[tuple[str, str]] = []
def md(s: str) -> None: CELLS.append(("md", s.strip("\n")))
def code(s: str) -> None: CELLS.append(("code", s.strip("\n")))


md(r"""
# 🤖 JENNY — LLM « maison » entraîné **DE ZÉRO** (from scratch)

Un **seul notebook** qui fait tout :
**collecte FR** (scraping + datasets HuggingFace) → **tokenizer BPE maison** → **modèle GPT** (PyTorch) →
**entraînement from scratch** (GPU **Tesla T4**, mixed-precision) → **courbes** → **génération** → **comparaison** des modèles.

> ⚠️ **Aucun fine-tune** : les poids partent du hasard. Un petit modèle sur laptop/T4 restera bien plus faible
> que Groq-70B / Ollama-7B — l'intérêt est la **démarche** (données → entraînement → courbes → comparaison),
> parfait pour montrer à un jury/prof.

**Mode d'emploi :** GPU activé (Colab : *Exécution → Modifier le type d'exécution → T4*), puis *Tout exécuter*.
La collecte a besoin d'internet ; l'entraînement tourne sur le GPU.
""")

code(r"""
# ── Dépendances ── (sur Colab/Kaggle, torch+CUDA est déjà installé)
!pip -q install datasets tokenizers requests matplotlib
import torch
print("torch", torch.__version__, "| CUDA dispo:", torch.cuda.is_available(),
      "|", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU (active un GPU T4 !)")
""")

md("## ⚙️ 0 · Réglages\nAjuste selon le temps GPU dont tu disposes. Plus de données + de steps = meilleure courbe.")

code(r"""
from dataclasses import dataclass

TARGET_MB  = 1500     # taille du corpus FR à collecter (Mo). T4 : 1000–3000.
VOCAB_SIZE = 32000    # vocabulaire BPE (entraîné de zéro)
VAL_FRAC   = 0.02     # part de validation

@dataclass
class Cfg:
    block_size: int = 512     # contexte
    n_layer: int = 8
    n_head: int = 8
    n_embd: int = 512
    dropout: float = 0.1
    batch_size: int = 32
    grad_accum: int = 4       # batch effectif = batch_size * grad_accum
    lr: float = 6e-4
    weight_decay: float = 0.1
    warmup: int = 800
    max_steps: int = 40000
    eval_interval: int = 500
    eval_iters: int = 100
    seed: int = 42

cfg = Cfg()
device = ("cuda" if torch.cuda.is_available()
          else "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
          else "cpu")
torch.manual_seed(cfg.seed)
print(f"device={device} | batch effectif={cfg.batch_size * cfg.grad_accum} | block={cfg.block_size}")
if device == "cpu":
    print("⚠ Pas de GPU détecté — l'entraînement sera TRÈS lent. Active un T4.")
""")

md(r"""
## 📚 1 · Collecte du corpus FR

Trois sources cumulées jusqu'à `TARGET_MB` :
1. **Données salon** (use case Jenny — FAQ coiffure, sur-échantillonnées pour la saveur métier).
2. **Scraping** de pages Wikipédia FR ciblées (coiffure, beauté, relation/service client, RDV, paiement…).
3. **Datasets HuggingFace** en streaming : FineWeb-2 FR, Wikipédia FR, C4 FR (+ OSCAR/CulturaX si token HF) pour la langue,
   et **PIAF / newsquadfr** (Q&R FR) pour la saveur « questions client ».

*OSCAR/CulturaX sont gated → ignorés sans `huggingface-cli login`. Internet requis ici uniquement.*
""")

code(r"""
import re, time
from html.parser import HTMLParser
from urllib.request import Request, urlopen

# 1) Données salon (use case) — petites mais sur-échantillonnées pour la saveur métier.
SALON_SEED = [
    "Question : Quels sont vos horaires ? Réponse : Le salon est ouvert du mardi au samedi de 9h à 19h, fermé dimanche et lundi.",
    "Question : Combien coûte une coupe femme ? Réponse : La coupe femme est à 35€, brushing inclus.",
    "Question : Combien coûte une coupe homme ? Réponse : La coupe homme est à 22€.",
    "Question : Quel est le prix d'une coloration ? Réponse : La coloration commence à 60€ selon la longueur.",
    "Question : Faites-vous des balayages ? Réponse : Oui, le balayage est à 90€, mèches comprises.",
    "Question : Comment prendre rendez-vous ? Réponse : Vous pouvez réserver en ligne, par téléphone ou directement par message.",
    "Question : Acceptez-vous les paiements par carte ? Réponse : Oui, carte, espèces et paiement sans contact.",
    "Question : Faut-il un acompte pour réserver ? Réponse : Un acompte peut être demandé pour les prestations longues comme le balayage.",
    "Question : Proposez-vous des soins ? Réponse : Oui, soins profonds, masques et rituels du cuir chevelu.",
    "Question : Où se trouve le salon ? Réponse : Le salon est situé à Bordeaux, en centre-ville.",
    "Question : Puis-je annuler mon rendez-vous ? Réponse : Bien sûr, prévenez-nous au moins 24h à l'avance.",
    "Question : Faites-vous les enfants ? Réponse : Oui, coupe enfant à 15€ jusqu'à 10 ans.",
    "Bonjour ! Je suis Jenny, l'assistante du salon. Comment puis-je vous aider aujourd'hui ?",
    "Avec plaisir ! Souhaitez-vous une coupe, une couleur, ou un soin ? Je peux vous proposer un créneau.",
]

SCRAPE_URLS = [
    "https://fr.wikipedia.org/wiki/Coiffure", "https://fr.wikipedia.org/wiki/Salon_de_coiffure",
    "https://fr.wikipedia.org/wiki/Coloration_capillaire", "https://fr.wikipedia.org/wiki/Coupe_de_cheveux",
    "https://fr.wikipedia.org/wiki/Soin_capillaire", "https://fr.wikipedia.org/wiki/Coiffeur",
    "https://fr.wikipedia.org/wiki/Barbier", "https://fr.wikipedia.org/wiki/Esth%C3%A9tique",
    "https://fr.wikipedia.org/wiki/Manucure", "https://fr.wikipedia.org/wiki/Maquillage",
    "https://fr.wikipedia.org/wiki/Service_client", "https://fr.wikipedia.org/wiki/Relation_client",
    "https://fr.wikipedia.org/wiki/Exp%C3%A9rience_client", "https://fr.wikipedia.org/wiki/Satisfaction_du_client",
    "https://fr.wikipedia.org/wiki/Fid%C3%A9lisation", "https://fr.wikipedia.org/wiki/R%C3%A9clamation",
    "https://fr.wikipedia.org/wiki/Rendez-vous", "https://fr.wikipedia.org/wiki/Paiement",
]

class _Strip(HTMLParser):
    def __init__(self): super().__init__(); self.skip=0; self.parts=[]
    def handle_starttag(self,t,a):
        if t in ("script","style","noscript"): self.skip+=1
    def handle_endtag(self,t):
        if t in ("script","style","noscript") and self.skip: self.skip-=1
    def handle_data(self,d):
        if not self.skip and d.strip(): self.parts.append(d.strip())

def scrape(urls, budget):
    out, tot = [], 0
    for u in urls:
        if tot >= budget: break
        try:
            req = Request(u, headers={"User-Agent":"JennyResearchBot/1.0 (educational)"})
            html = urlopen(req, timeout=15).read().decode("utf-8","ignore")
            s = _Strip(); s.feed(html); txt = re.sub(r"\n{3,}","\n\n","\n".join(s.parts))
            out.append(txt); tot += len(txt); print("  scrape OK", u.split("/")[-1], f"(+{len(txt)} car.)")
            time.sleep(0.8)
        except Exception as e:
            print("  scrape ignoré", u, str(e)[:60])
    return out

def hf_stream(target_chars):
    out, tot = [], 0
    try:
        from datasets import load_dataset
    except Exception as e:
        print("datasets indispo:", e); return out
    SOURCES = [
        ("HuggingFaceFW/fineweb-2","fra_Latn","text","text"),
        ("wikimedia/wikipedia","20231101.fr","text","text"),
        ("allenai/c4","fr","text","text"),
        ("uonlp/CulturaX","fr","text","text"),          # gated
        ("oscar-corpus/OSCAR-2301","fr","text","text"), # gated
        ("etalab-ia/piaf",None,None,"qa"),
        ("lincoln/newsquadfr",None,None,"qa"),
    ]
    def extract(row, field, kind):
        if kind=="qa":
            q,ctx,ans = row.get("question"), row.get("context"), row.get("answers")
            a=None
            if isinstance(ans,dict):
                t=ans.get("text"); a=(t[0] if isinstance(t,list) and t else t) if t else None
            elif isinstance(ans,str): a=ans
            p=[x for x in (ctx, f"Question : {q}" if q else None, f"Réponse : {a}" if a else None) if x]
            return "\n".join(map(str,p)) if p else None
        return row.get(field) if field else None
    for repo,cfgname,field,kind in SOURCES:
        if tot>=target_chars: break
        try:
            print(f"HF stream {repo} ({cfgname or '-'}, {kind})…")
            ds = load_dataset(repo, cfgname, split="train", streaming=True)
            n0=tot
            for i,row in enumerate(ds):
                if not isinstance(row,dict): continue
                txt=extract(row,field,kind)
                if not txt: continue
                out.append(str(txt)); tot+=len(txt)
                if tot>=target_chars: break
                if i%5000==0: print(f"  …{tot/1e6:.1f} Mo")
            print(f"  {repo}: +{(tot-n0)/1e6:.1f} Mo (cumulé {tot/1e6:.1f} Mo)")
        except Exception as e:
            print(f"  {repo} ignoré:", str(e)[:80])
    return out

target_chars = int(TARGET_MB*1e6)
chunks  = SALON_SEED*80                                      # saveur métier (sur-échantillonnée)
chunks += scrape(SCRAPE_URLS, budget=min(target_chars//10, 1_500_000))
used = sum(len(c) for c in chunks)
if used < target_chars:
    chunks += hf_stream(target_chars - used)

corpus = "\n\n".join(c.strip() for c in chunks if c and c.strip())
corpus = re.sub(r"[ \t]+"," ",corpus); corpus = re.sub(r"\n{3,}","\n\n",corpus).strip()
print(f"\n✓ corpus : {len(corpus)/1e6:.1f} Mo ({len(corpus):,} car.)")
""")

md("## 🔤 2 · Tokenizer BPE — entraîné **de zéro** sur le corpus\nLe tokenizer n'apporte aucune connaissance : il ne fait que découper le texte.")

code(r"""
import numpy as np
from tokenizers import Tokenizer
from tokenizers.models import BPE
from tokenizers.pre_tokenizers import ByteLevel
from tokenizers.decoders import ByteLevel as ByteLevelDecoder
from tokenizers.trainers import BpeTrainer

with open("corpus.txt","w",encoding="utf-8") as f: f.write(corpus)
tok = Tokenizer(BPE(unk_token="<unk>"))
tok.pre_tokenizer = ByteLevel(add_prefix_space=False)
tok.decoder = ByteLevelDecoder()
tok.train(["corpus.txt"], BpeTrainer(vocab_size=VOCAB_SIZE,
          special_tokens=["<unk>","<bos>","<eos>","<pad>"], show_progress=True))
tok.save("tokenizer.json")
VOCAB = tok.get_vocab_size()

ids = np.array(tok.encode(corpus).ids, dtype=np.uint16)
n = len(ids); split = int(n*(1-VAL_FRAC))
train_ids, val_ids = ids[:split], ids[split:]
print(f"✓ {n:,} tokens | vocab {VOCAB} | train {len(train_ids):,} / val {len(val_ids):,}")
""")

md("## 🧠 3 · Le modèle GPT (decoder-only, from scratch)\nArchitecture type *nanoGPT* : embeddings + N blocs (attention causale multi-tête + MLP) + tête de sortie (poids liés).")

code(r"""
import math
import torch.nn as nn
import torch.nn.functional as F

class CausalSelfAttention(nn.Module):
    def __init__(self, c):
        super().__init__(); assert c.n_embd % c.n_head == 0
        self.c_attn = nn.Linear(c.n_embd, 3*c.n_embd); self.c_proj = nn.Linear(c.n_embd, c.n_embd)
        self.drop = nn.Dropout(c.dropout); self.n_head = c.n_head; self.n_embd = c.n_embd
        self.register_buffer("mask", torch.tril(torch.ones(c.block_size, c.block_size)).view(1,1,c.block_size,c.block_size))
    def forward(self, x):
        B,T,C = x.size(); q,k,v = self.c_attn(x).split(self.n_embd, dim=2); hd = C//self.n_head
        q=q.view(B,T,self.n_head,hd).transpose(1,2); k=k.view(B,T,self.n_head,hd).transpose(1,2); v=v.view(B,T,self.n_head,hd).transpose(1,2)
        att = (q @ k.transpose(-2,-1)) / math.sqrt(hd)
        att = att.masked_fill(self.mask[:,:,:T,:T]==0, float("-inf"))
        att = self.drop(F.softmax(att, dim=-1))
        y = (att @ v).transpose(1,2).contiguous().view(B,T,C)
        return self.c_proj(y)

class Block(nn.Module):
    def __init__(self, c):
        super().__init__(); self.ln1=nn.LayerNorm(c.n_embd); self.attn=CausalSelfAttention(c)
        self.ln2=nn.LayerNorm(c.n_embd)
        self.mlp=nn.Sequential(nn.Linear(c.n_embd,4*c.n_embd), nn.GELU(), nn.Linear(4*c.n_embd,c.n_embd), nn.Dropout(c.dropout))
    def forward(self,x): x=x+self.attn(self.ln1(x)); return x+self.mlp(self.ln2(x))

class GPT(nn.Module):
    def __init__(self, c, vocab):
        super().__init__(); self.c=c
        self.tok=nn.Embedding(vocab,c.n_embd); self.pos=nn.Embedding(c.block_size,c.n_embd); self.drop=nn.Dropout(c.dropout)
        self.blocks=nn.ModuleList([Block(c) for _ in range(c.n_layer)]); self.lnf=nn.LayerNorm(c.n_embd)
        self.head=nn.Linear(c.n_embd,vocab,bias=False); self.tok.weight=self.head.weight
        self.apply(self._init)
    def _init(self,m):
        if isinstance(m,nn.Linear):
            nn.init.normal_(m.weight,0,0.02);  m.bias is not None and nn.init.zeros_(m.bias)
        elif isinstance(m,nn.Embedding): nn.init.normal_(m.weight,0,0.02)
    def forward(self, idx, targets=None):
        B,T = idx.size(); pos = torch.arange(T, device=idx.device)
        x = self.drop(self.tok(idx) + self.pos(pos))
        for b in self.blocks: x = b(x)
        logits = self.head(self.lnf(x))
        loss = None if targets is None else F.cross_entropy(logits.view(-1,logits.size(-1)), targets.view(-1))
        return logits, loss

model = GPT(cfg, VOCAB).to(device)
n_params = sum(p.numel() for p in model.parameters())
print(f"✓ modèle : {n_params/1e6:.1f} M paramètres")
""")

md("## 🏋️ 4 · Entraînement **from scratch** (AMP + accumulation de gradient)\nLa loss part de ≈ln(vocab) (hasard) et doit descendre. La courbe est journalisée pour le graphe.")

code(r"""
import time
train_t = torch.from_numpy(train_ids.astype(np.int64))
val_t   = torch.from_numpy(val_ids.astype(np.int64))

def get_batch(data):
    ix = torch.randint(len(data)-cfg.block_size-1, (cfg.batch_size,))
    x = torch.stack([data[i:i+cfg.block_size] for i in ix])
    y = torch.stack([data[i+1:i+1+cfg.block_size] for i in ix])
    return x.to(device), y.to(device)

@torch.no_grad()
def estimate_loss():
    model.eval(); out={}
    for name,data in (("train",train_t),("val",val_t)):
        L=torch.zeros(cfg.eval_iters)
        for k in range(cfg.eval_iters):
            x,y=get_batch(data); _,l=model(x,y); L[k]=l.item()
        out[name]=L.mean().item()
    model.train(); return out

def get_lr(step):
    if step < cfg.warmup: return cfg.lr*(step+1)/cfg.warmup
    r=(step-cfg.warmup)/max(cfg.max_steps-cfg.warmup,1)
    return cfg.lr*max(0.1, 0.5*(1+math.cos(math.pi*r)))

opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay, betas=(0.9,0.95))
use_amp = device=="cuda"
scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
def amp_ctx():
    from contextlib import nullcontext
    return torch.amp.autocast("cuda", dtype=torch.float16) if use_amp else nullcontext()

history=[]; best=float("inf"); t0=time.time(); model.train()
for step in range(cfg.max_steps+1):
    for g in opt.param_groups: g["lr"]=get_lr(step)
    if step % cfg.eval_interval == 0 or step == cfg.max_steps:
        L=estimate_loss(); history.append({"step":step, **L, "t":time.time()-t0})
        print(f"step {step:>6} | train {L['train']:.3f} | val {L['val']:.3f} | {time.time()-t0:.0f}s")
        if L["val"]<best:
            best=L["val"]; torch.save({"model":model.state_dict(),"cfg":cfg.__dict__,"vocab":VOCAB,"step":step,"val":best}, "best_model.pt")
    if step==cfg.max_steps: break
    opt.zero_grad(set_to_none=True)
    for _ in range(cfg.grad_accum):
        x,y=get_batch(train_t)
        with amp_ctx():
            _,loss=model(x,y); loss=loss/cfg.grad_accum
        scaler.scale(loss).backward()
    scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
    scaler.step(opt); scaler.update()
print(f"\n✓ terminé. meilleure val loss = {best:.3f}  → best_model.pt")
""")

md("## 📈 5 · Courbe d'entraînement (pour le rapport / la prof)")

code(r"""
import matplotlib.pyplot as plt
steps=[h["step"] for h in history]; tr=[h["train"] for h in history]; va=[h["val"] for h in history]
plt.figure(figsize=(9,5.2))
plt.plot(steps,tr,label="train loss",color="#FF7F6A",lw=2.2)
plt.plot(steps,va,label="val loss",color="#7284A8",lw=2.2)
plt.title("NanoGPT — entraînement from scratch"); plt.xlabel("étape"); plt.ylabel("cross-entropy loss")
plt.grid(alpha=.18); plt.legend(frameon=False); plt.tight_layout()
plt.savefig("training_curve.png", dpi=120); plt.show()
print("✓ training_curve.png enregistré")
""")

md("## 💬 6 · Génération — le modèle maison répond")

code(r"""
@torch.no_grad()
def generate(prompt, max_new=120, temperature=0.8, top_k=40):
    model.eval()
    ids = tok.encode(prompt).ids[-(cfg.block_size-1):]
    idx = torch.tensor([ids or [0]], dtype=torch.long, device=device)
    for _ in range(max_new):
        logits,_ = model(idx[:,-cfg.block_size:]); logits=logits[:,-1,:]/temperature
        if top_k:
            v,_=torch.topk(logits, min(top_k,logits.size(-1))); logits[logits<v[:,[-1]]]=float("-inf")
        probs=torch.softmax(logits,dim=-1); nxt=torch.multinomial(probs,1); idx=torch.cat([idx,nxt],dim=1)
    return tok.decode(idx[0].tolist()[len(ids):])

for p in ["Bonjour, quels sont vos horaires ?", "Je voudrais une coloration,", "Question : Comment prendre rendez-vous ? Réponse :"]:
    print("➤", p, "\n  ", repr(generate(p, max_new=60)), "\n")
""")

md(r"""
## 🆚 7 · Comparaison des modèles (optionnel)

Même contexte salon + mêmes questions → **efficacité** (bonne info ?) et **latence**.
- **NanoGPT (maison)** : toujours testé.
- **Groq** : colle ta clé dans `GROQ_API_KEY` ci-dessous.
- **Ollama** : testé si un serveur tourne sur `localhost:11434`.
""")

code(r"""
import time, json as _json, urllib.request
GROQ_API_KEY = ""   # ← (optionnel) colle ta clé Groq ici pour comparer

SYSTEM = ("Tu es Jenny, assistante du salon « Studio Lila » à Bordeaux. Horaires : mardi-samedi 9h-19h, "
          "fermé dim/lun. Tarifs : coupe femme 35€, homme 22€, coloration 60€, balayage 90€. Réponds en une phrase.")
PROMPTS = [("Vous êtes ouverts le dimanche ?",["non","fermé","ferme"]), ("Prix d'une coupe homme ?",["22"]),
           ("Horaires le samedi ?",["9","19"]), ("Le balayage coûte combien ?",["90"]),
           ("Vous êtes dans quelle ville ?",["bordeaux"]), ("Prix d'une coloration ?",["60"])]

def bench(fn, label):
    ok=0; lat=[]
    for q,exp in PROMPTS:
        t=time.time()
        try: a=fn(q)
        except Exception as e: print(f"  {label}: {str(e)[:70]}"); return None
        lat.append((time.time()-t)*1000); ok += any(k in (a or "").lower() for k in exp)
    return {"label":label, "score_pct":round(100*ok/len(PROMPTS),1), "latence_ms":round(sum(lat)/len(lat),1)}

def groq_fn(q):
    body=_json.dumps({"model":"llama-3.3-70b-versatile","messages":[{"role":"system","content":SYSTEM},{"role":"user","content":q}],"temperature":0.3}).encode()
    r=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", body,
        {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"})
    return _json.loads(urllib.request.urlopen(r,timeout=30).read())["choices"][0]["message"]["content"]

def ollama_fn(q):
    body=_json.dumps({"model":"qwen2.5:7b-instruct","stream":False,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":q}]}).encode()
    r=urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type":"application/json"})
    return _json.loads(urllib.request.urlopen(r,timeout=60).read())["message"]["content"]

results=[]
r=bench(lambda q: generate(f"{SYSTEM}\n{q}\n", max_new=60, temperature=0.3), "NanoGPT (maison)");  results.append(r) if r else None
if GROQ_API_KEY.strip():
    r=bench(groq_fn, "Groq 70B"); results.append(r) if r else None
try:
    urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
    r=bench(ollama_fn, "Ollama 7B"); results.append(r) if r else None
except Exception:
    print("Ollama non joignable — ignoré.")

print(_json.dumps(results, indent=2, ensure_ascii=False))
if results:
    import matplotlib.pyplot as plt
    labels=[r["label"] for r in results]
    fig,ax=plt.subplots(1,2,figsize=(11,4))
    ax[0].bar(labels,[r["score_pct"] for r in results],color="#FF7F6A"); ax[0].set_title("Efficacité (%)"); ax[0].set_ylim(0,100)
    ax[1].bar(labels,[r["latence_ms"] for r in results],color="#7284A8"); ax[1].set_title("Latence moyenne (ms)")
    for a in ax: a.tick_params(axis="x",rotation=15)
    plt.tight_layout(); plt.savefig("comparison.png",dpi=120); plt.show()
""")

md(r"""
## ✅ Récap

Tu as, **dans ce seul notebook** : collecté un gros corpus FR, entraîné un **tokenizer** + un **GPT de zéro**,
tracé la **courbe d'apprentissage**, **généré** du texte, et **comparé** au besoin avec Groq/Ollama.

**Pour aller plus loin** : ↑ `TARGET_MB`, ↑ `cfg.max_steps`, ↑ `cfg.n_layer`/`cfg.n_embd` (si la VRAM suit).
En cas d'OOM sur la T4 : ↓ `cfg.batch_size` et ↑ `cfg.grad_accum` (le batch effectif reste constant).
Fichiers produits : `best_model.pt`, `tokenizer.json`, `training_curve.png`, `comparison.png`.
""")


def build() -> None:
    cells = []
    for kind, src in CELLS:
        if kind == "md":
            cells.append({"cell_type": "markdown", "metadata": {}, "source": src})
        else:
            cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                          "outputs": [], "source": src})
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "accelerator": "GPU", "colab": {"provenance": []},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ notebook écrit : {OUT} ({len(cells)} cellules)")


if __name__ == "__main__":
    build()
