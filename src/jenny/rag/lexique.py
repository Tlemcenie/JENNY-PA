"""Outils lexicaux français pour le RAG."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_WORD_RE = re.compile(r"[a-z0-9]+")
# durée écrite en clair
_DUREE_RE = re.compile(r"\d+\s*(?:min\b|minutes?|h\b|h\d|heures?)", re.I)
# un prix écrit
_PRIX_RE = re.compile(r"\d\s*(?:€|euros?\b)", re.I)
# une heure (9h, 19h30)
_HEURE_RE = re.compile(r"\b\d{1,2}h(?:\d{2})?\b", re.I)


def fold(text: str) -> str:
    """Minuscules sans accents."""
    t = (text or "").lower().replace("œ", "oe").replace("æ", "ae")
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


# mots vides : la seule liste
_STOPWORDS_RAW = """
a ai aie aies ait as au aux avais avait avec avez aviez avions avoir avons ayant
c ca ce ceci cela celle celles celui ces cet cette ceux chaque chez ci comme
d dans de des du donc dont du elle elles en encore entre es est et etaient etais
etait etant ete etes etre eu eux fut il ils j je jusqu jusque l la le les leur
leurs lui m ma mais me meme mes moi mon n ne ni nos notre nous on ont ou par pas
pendant peu plus pour qu que quel quelle quelles quels qui quoi s sa sans se ses
si son sont sur t ta te tes toi ton tous tout toute toutes tu un une unes uns vos
votre vous y hui aujourd lors ici la voici
bonjour bonsoir salut coucou hello hey merci super genial parfait nickel cool
svp stp plait voila alors juste aussi vraiment peut etre peutetre ok okay oui non
comment combien quand pourquoi ou lequel laquelle lesquels lesquelles
sont etes avez faites faire fais fait faut posez poser proposez proposer vendez
vendre utilisez utiliser prenez prendre peut peux pouvez pourrais pourriez pouvoir
possible besoin savoir sais sait voudrais voudrait voulez veux veut vouloir aimerais
dois doit devez devoir vais va allez aller dire dis dites chose truc fois quelque
quelqu plutot genre sinon enfin bien tres trop beaucoup assez
coup matin soir apres avant week end weekend demain semaine heure heures jour depuis
jours combien servez servons restez question questions info infos
information informations demande demander renseignement renseigner aide aider
salon prestation prestations service services
madame monsieur mademoiselle cordialement
deux trois quatre cinq six sept huit neuf dix
suis sommes serai sera seront serait seraient pres
pourrai pourra pourrez pourrons pourront pourrait pourrions bon bons bonne bonnes
venir viens vient venez venons viennent venu venue laisser laisse laissez laissent
passer passe passez donner donne donnez prevoir prevu prevue prevoit
coiffer coiffez coiffons coiffent
mere pere maman papa mari epoux epouse soeur frere ami amie copain copine
"""

STOPWORDS: frozenset[str] = frozenset(_STOPWORDS_RAW.split())

# suffixes, du plus long au plus court
_SUFFIXES = (
    "issements",
    "issement",
    "abilites",
    "ibilites",
    "abilite",
    "ibilite",
    "atrices",
    "ateurs",
    "ations",
    "ements",
    "atrice",
    "ateur",
    "ation",
    "ement",
    "euses",
    "ables",
    "ibles",
    "iques",
    "istes",
    "ments",
    "tions",
    "ances",
    "ences",
    "antes",
    "euse",
    "eurs",
    "able",
    "ible",
    "ique",
    "iste",
    "ment",
    "tion",
    "ance",
    "ence",
    "ante",
    "ants",
    "ites",
    "ives",
    "eur",
    "ant",
    "ite",
    "ive",
    "issez",
    "issent",
    "ifs",
    "ees",
    "if",
    "ir",
    "ee",
    "es",
    "er",
    "ez",
    "e",
    "s",
    "x",
)


@lru_cache(maxsize=8192)
def stem(word: str) -> str:
    """Racine française simple."""
    w = fold(word)
    if len(w) <= 3:
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


# petit lexique salon
_LEXIQUE_RAW = """
inclus: inclus incluse incluses inclut incluent inclure compris comprise comprises
  comprend comprennent comprendre
annulation: annuler annulation annulations annule annulee decommander desister
  desiste desistez desistement
report: reporter report deplacer decaler modifier
frais: frais facture facturer facturee factures payant payante payer penalite penalites
  supplement supplementaire gratuit gratuite gratuits gratuites offert offerte offerts gratis
  offre offrez offrir offrons
prix: prix tarif tarifs tarification coute coutent couter cout montant
horaires: horaire horaires ouverture ouvertures fermeture fermetures ferme fermee fermes
  fermez fermer ouvert ouverts ouverte ouvertes ouvrez ouvrir ouvre
enfant: enfant enfants gamin gamins gamine bambin bambins fils fille filles ado ados
  adolescent adolescente adolescents
mariage: mariage mariages mariee mariees marie noces ceremonie
accessibilite: accessible accessibles accessibilite handicap handicape handicapee
  fauteuil roulant pmr mobilite
paiement: paiement paiements payer paye regler reglement cb especes liquide cash monnaie
stationnement: stationnement stationner garer parking parkings voiture
coloration: coloration colorations couleur couleurs teinture teintures colo coloriste
balayage: balayage balayages meches meche ombre ombres eclaircir
barbe: barbe barbes rasage raser tondeuse moustache
shampoing: shampoing shampooing shampoings shampooings shampoo lavage
rdv: rdv rendez reservation reservations reserver reserve creneau creneaux
retard: retard retards retarder
acompte: acompte acomptes arrhes caution
duree: duree durees dure durer temps longtemps
naturel: naturel naturelle naturels naturelles bio biologique organique vegetal vegetale
  vegetaux vegetales
cadeau: cadeau cadeaux offrir offrez
attente: attendre attend attente attendu patienter
contact: contacter contact contactez joindre joignable joignables mail email courriel
  telephone telephoner appeler
transport: metro bus tram tramway rer transport transports
equipe: equipe coiffeur coiffeurs coiffeuse coiffeuses personnel employe employes staff
wifi: wifi wi fi internet
conges: conge conges vacances vacance
rembourse: rembourser remboursement rembourse remboursee
homme: homme hommes masculin masculine
femme: femme femmes feminin feminine dame dames
"""


def _parse_lexique(raw: str) -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    current = ""
    for line in raw.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            current, _, rest = line.partition(":")
            current = current.strip()
        else:
            rest = line
        out.setdefault(current, []).extend(rest.split())
    return {k: tuple(v) for k, v in out.items()}


_SYNONYMES: dict[str, tuple[str, ...]] = _parse_lexique(_LEXIQUE_RAW)


# sujets précis : absents = lacune
_SUJETS_RAW = """
coupe coloration balayage brushing chignon meche decoloration henne olaplex barbe
extension extensions rajout rajouts lissage lisser keratine permanente defrisage
tresse tresses natte nattes locks dreadlocks tissage perruque perruques maquillage
maquiller manucure pedicure ongle ongles vernis epilation epiler sourcil sourcils cils
massage massages tatouage tatouages piercing bronzage
recrutement recruter recrutez emploi postuler candidature stage stagiaire apprenti
apprentis apprentissage alternance embauche embauchez
"""


def _build_concepts() -> dict[str, frozenset[str]]:
    out: dict[str, set[str]] = {}
    for cid, words in _SYNONYMES.items():
        for w in words:
            out.setdefault(stem(w), set()).add(cid)
    return {k: frozenset(v) for k, v in out.items()}


_CONCEPTS_OF_STEM: dict[str, frozenset[str]] = _build_concepts()


def _build_sujets() -> frozenset[str]:
    out: set[str] = set()
    for w in _SUJETS_RAW.split():
        s = stem(w)
        out |= _CONCEPTS_OF_STEM.get(s, frozenset()) | {s}
    return frozenset(out)


SUJET_KEYS: frozenset[str] = _build_sujets()


def keys(word: str) -> frozenset[str]:
    """Racine + concepts d'un mot."""
    s = stem(word)
    return _CONCEPTS_OF_STEM.get(s, frozenset()) | {s}


_ACRONYM_RE = re.compile(r"\b[A-Z]{2}\b")


def content_words(text: str) -> list[str]:
    """Mots porteurs de sens."""
    # sigles courts (UV, CV)
    acronyms = {a.lower() for a in _ACRONYM_RE.findall(text or "")}
    out: list[str] = []
    for w in _WORD_RE.findall(fold(text)):
        if w in STOPWORDS or any(c.isdigit() for c in w):
            continue
        if len(w) < 3 and stem(w) not in _CONCEPTS_OF_STEM and w not in acronyms:
            continue
        out.append(w)
    return out


@lru_cache(maxsize=4096)
def _query_terms(text: str) -> tuple[frozenset[str], ...]:
    seen: set[str] = set()
    out: list[frozenset[str]] = []
    for w in content_words(text):
        s = stem(w)
        if s in seen:
            continue
        seen.add(s)
        out.append(keys(w))
    return tuple(out)


def query_terms(text: str) -> list[frozenset[str]]:
    """Termes d'une question, sans doublon."""
    return list(_query_terms(text or ""))


@lru_cache(maxsize=8192)
def _doc_pool(text: str) -> frozenset[str]:
    pool: set[str] = set()
    for w in content_words(text):
        pool |= keys(w)
    if _DUREE_RE.search(text):
        pool.add("duree")
    if _PRIX_RE.search(text):
        pool.add("prix")
    if _HEURE_RE.search(text):
        pool.add("horaires")
    return frozenset(pool)


def doc_pool(text: str) -> set[str]:
    """Racines + concepts d'un passage."""
    return set(_doc_pool(text or ""))


def expansions(text: str) -> list[str]:
    """Mots de la question, puis synonymes."""
    words = content_words(text)
    out = list(words)
    for w in words:
        for cid in sorted(_CONCEPTS_OF_STEM.get(stem(w), ())):
            out.extend(_SYNONYMES[cid])
    # garde l'ordre, sans doublon
    return list(dict.fromkeys(out))


# fins de flexion tolérées
_TAILS = frozenset(
    [
        "e",
        "s",
        "es",
        "er",
        "ez",
        "ent",
        "ons",
        "on",
        "a",
        "ai",
        "ait",
        "is",
        "it",
        "ir",
        "iss",
        "u",
        "us",
        "ut",
        "ant",
        "ee",
        "ees",
    ]
)


def _cousins(a: str, b: str) -> bool:
    """Même mot, flexion près ?"""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 5 or not long_.startswith(short):
        return False
    return long_ == short or long_[len(short) :] in _TAILS


def is_covered(term: frozenset[str], pool: set[str]) -> bool:
    """Terme présent (ou flexion proche) ?"""
    if term & pool:
        return True
    long_keys = [k for k in term if len(k) >= 5]
    return any(_cousins(k, p) for k in long_keys for p in pool if len(p) >= 5)


def is_sujet(term: frozenset[str]) -> bool:
    """Terme = sujet précis ?"""
    return bool(term & SUJET_KEYS)


def coverage(terms: list[frozenset[str]], pool: set[str]) -> float:
    """Part des termes couverts."""
    if not terms:
        return 0.0
    hit = sum(1 for t in terms if is_covered(t, pool))
    return hit / len(terms)


# crédit d'un simple synonyme
SYN_CREDIT = 0.8


@lru_cache(maxsize=8192)
def _doc_stems(text: str) -> frozenset[str]:
    return frozenset(stem(w) for w in content_words(text))


def match_score(query: str, doc_text: str) -> float:
    """Recouvrement pondéré (mot exact > synonyme)."""
    words = list(dict.fromkeys(stem(w) for w in content_words(query or "")))
    if not words:
        return 0.0
    stems = _doc_stems(doc_text or "")
    pool = _doc_pool(doc_text or "")
    total = 0.0
    for s in words:
        if s in stems or any(_cousins(s, p) for p in stems if len(p) >= 5):
            total += 1.0
        elif (_CONCEPTS_OF_STEM.get(s, frozenset()) | {s}) & pool:
            total += SYN_CREDIT
    return total / len(words)
