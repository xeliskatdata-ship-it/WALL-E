# brain/safety.py - Couche de filtrage deterministe (Phase 8.6)
# v2.2 : compense la moindre fiabilite de qwen2.5:3b par rapport a Claude
# pour les garde-fous mineurs.
#
# Architecture en 2 niveaux (le niveau 3 "contradiction prompt" est garde
# pour iteration 2 si necessaire) :
#
#   Niveau 1 - check_output() : pattern matching sur la SORTIE LLM
#     S'applique aux mineurs uniquement (role=child).
#     Intercepte les contenus inappropries pour l'age meme si le LLM
#     les a generes malgre le prompt systeme.
#
#   Niveau 2 - check_input() : detection de detresse sur l'INPUT user
#     S'applique a tous les users.
#     Si signal de detresse detecte, on n'envoie PAS au LLM, on retourne
#     directement un message de redirection adapte au role.
#
# Logging : les interceptions sont loggees dans data/safety_alerts.log
# avec timestamp + user_id + niveau + raison. Sera consultable par les
# parents en Phase 10 via l'app mobile.

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger("walle.safety")

# Path du log d'alertes (dans data/, gitignore)
_PROJECT_ROOT = Path(config.__file__).parent
_ALERT_LOG_PATH = _PROJECT_ROOT / "data" / "safety_alerts.log"


# === RESULTAT ===

@dataclass
class SafetyResult:
    passed: bool                              # True = OK / False = intercepte
    severity: str = "ok"                      # "ok" | "warning" | "block"
    replacement: Optional[str] = None         # message de remplacement
    reason: Optional[str] = None              # raison du block
    log_for_parents: bool = False             # alerte parents recommandee
    matched_patterns: list = field(default_factory=list)


# === NIVEAU 2 : DETECTION DETRESSE SUR INPUT ===

# Patterns de detresse aigue. On utilise des regex avec word boundaries
# pour limiter les faux positifs (ex: "mourir d'envie" ne doit pas matcher).
# Categorie -> liste de patterns.

_DETRESSE_PATTERNS = {
    "idees_noires": [
        r"\benvie\s+de\s+mou?rir\b",
        r"\benvie\s+de\s+me\s+tuer\b",
        r"\bplus\s+envie\s+de\s+vivre\b",
        r"\benvie\s+d'?\s*en\s+finir\b",
        r"\bje\s+veux\s+mou?rir\b",
        r"\bje\s+veux\s+me\s+tuer\b",
        r"\bsuicid[eé]r?\b",
        r"\bme\s+suicider\b",
        r"\bme\s+pendre\b",
        r"\bdispara[iî]tre\b.{0,30}(jamais|toujours|pour\s+de\s+bon)",
    ],
    "violence_subie": [
        # Coups : explicites
        r"\bil\s+me\s+(frappe|bat|tape|cogne)\b",
        r"\belle\s+me\s+(frappe|bat|tape|cogne)\b",
        r"\bils?\s+me\s+(frappent|battent|tapent)\b",
        r"\bil\s+m'?\s*a\s+(frapp[eé]e?|battue?|tap[eé]e?)\b",
        # Toucher inapproprie : avec contexte explicite (negative lookahead pour les
        # usages metaphoriques comme "il me touche le coeur quand il chante" ou "elle me touche l'ame")
        r"\bil\s+me\s+touche\b(?!\s+(?:l['ae]?\s*(?:c[oeu]+r|[aâ]me)|avec\s+(?:ses|son)))",
        r"\belle\s+me\s+touche\b(?!\s+(?:l['ae]?\s*(?:c[oeu]+r|[aâ]me)|avec\s+(?:ses|son)))",
        r"\bil\s+m'?\s*a\s+touch[eé]e?\b(?!\s+(?:l['ae]?\s*(?:c[oeu]+r|[aâ]me)|avec\s+(?:ses|son)))",
        # Peur d'une personne specifique (pas peur generique d'animaux/situations)
        r"\bj'?\s*ai\s+peur\s+(de|d')\s+(papa|maman|lui|elle|mon\s+(p[eè]re|m[eè]re|fr[eè]re|s[oe]ur|oncle|cousin)|ma\s+(m[eè]re|s[oe]ur|tante|cousine))\b",
        r"\bj'?\s*ai\s+peur\s+qu'?\s*(il|elle|on)\s+me\s+(frappe|tape|fasse|touche|battent?)",
        r"\bj'?\s*ai\s+peur\s+a\s+la\s+maison\b",
        # Faire du mal : explicite
        r"\bil\s+me\s+fait\s+(du\s+)?mal\b",
        r"\belle\s+me\s+fait\s+(du\s+)?mal\b",
        r"\bje\s+me\s+fais\s+battre\b",
    ],
    "harcelement": [
        r"\btout\s+le\s+monde\s+se\s+moque\b",
        r"\bpersonne\s+(ne\s+)?m'?\s*aime\b",
        r"\bils?\s+me\s+harc[eè]l(e|ent)\b",
        r"\bj'?\s*ai\s+pas\s+d'?amis?\b",
        r"\bils\s+me\s+frappent\s+a\s+l'?[eé]cole\b",
    ],
    "automutilation": [
        # Couper avec contexte corporel explicite (pas "je me coupe en cuisinant")
        r"\bje\s+me\s+coupe\s+(les?\s+)?(bras|poignets?|veines?|cuisses?|jambes?|mains?)\b",
        r"\bje\s+me\s+suis\s+coup[eé]e?\s+(les?\s+)?(bras|poignets?|veines?|cuisses?|jambes?)\b",
        # Couper avec adverbe alarmant
        r"\bje\s+me\s+coupe\s+(souvent|tous?\s+les\s+jours?|expr[eè]s|volontairement|la\s+nuit)\b",
        # Faire du mal a soi : explicite
        r"\bje\s+me\s+fais\s+du\s+mal\b",
        # Scarification
        r"\bme\s+scarifier\b",
        r"\bje\s+me\s+scarifie\b",
    ],
}

# Compilation des regex (insensibles a la casse)
_COMPILED_DETRESSE = {
    cat: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cat, patterns in _DETRESSE_PATTERNS.items()
}


# === NIVEAU 1 : PATTERNS BLOQUANTS SUR SORTIE LLM (mineurs uniquement) ===

# Patterns qui ne doivent JAMAIS apparaitre dans une reponse a un mineur.
# Plus tolerant que niveau 2 : on cherche du contenu generationnel
# (instructions concretes), pas juste des mentions.

_OUTPUT_BLOCK_PATTERNS = {
    "sexualite_explicite": [
        r"\b(p[eé]nis|vagin|sexe)\b.{0,40}(p[eé]n[eé]tr|caresse|frotte|jouir)",
        r"\bfaire\s+l'?amour\b.{0,80}(comment|technique|position)",
        r"\brapport\s+sexuel\b",
        r"\borgasme\b",
    ],
    "violence_graphique": [
        r"\b(d[eé]coup|d[eé]membre|[eé]gorge|[eé]ventre|poignard)\w*",
        r"\btorturer?\b.{0,60}(comment|technique|methode)",
        # Conjugaisons elargies (gicl*, jaill*, inond*, etc.)
        r"\bsang\b.{0,40}(gicl|jaill|inond)",
    ],
    "drogues_methode": [
        # Sens 1 : drogue en premier, action ensuite
        r"\b(coca[iï]ne|h[eé]ro[iï]ne|crack|m[eé]thamph[eé]tamine|LSD|ecstasy|MDMA)\b.{0,80}(comment|prendre|consommer|prep|recette|fabriquer|sniff|injecter)",
        # Sens 2 : action en premier, drogue ensuite
        r"\b(preparer|fabriquer|recette|fabrication|cuisiner|sniff|injecter)\b.{0,40}\b(coca[iï]ne|h[eé]ro[iï]ne|crack|m[eé]thamph[eé]tamine|LSD|ecstasy|MDMA|drogue)\b",
        r"\bcomment\s+se\s+procurer\s+(de\s+la\s+)?(coca|h[eé]ro|crack|drogue)",
        r"\bseringue\b.{0,40}(injecter|piquer|veine)",
    ],
    "automutilation_methode": [
        r"\bcomment\s+(se\s+)?(couper|scarifier|saigner)\b",
        r"\b(se\s+)?couper\s+les\s+veines?\b",
        r"\bcomment\s+(se\s+)?suicider\b",
        r"\bm[eé]thode\s+pour\s+mou?rir\b",
    ],
}

_COMPILED_OUTPUT_BLOCK = {
    cat: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cat, patterns in _OUTPUT_BLOCK_PATTERNS.items()
}


# === MESSAGES DE REMPLACEMENT ===

def _redirection_mineur(display_name: str, categorie: str) -> str:
    # Message bienveillant + redirection parents pour un mineur en detresse.
    # On ne joue pas au psy, on ne prolonge pas l'echange emotionnel.
    base = f"Eh, {display_name}... ce que tu me dis la, c'est tres important. "
    if categorie == "idees_noires":
        return (base + "Je veux pas que tu sois seul(e) avec ca. Tu peux aller "
                "voir Kat ou Brice tout de suite ? Eux, ils sauront t'aider "
                "vraiment. Je suis la, mais c'est eux qu'il te faut pour ca.")
    if categorie == "violence_subie":
        return (base + "Personne n'a le droit de te faire du mal. Va parler a "
                "Kat ou Brice maintenant, dis-leur exactement ce que tu m'as "
                "dit. Ils vont s'en occuper, c'est leur role et ils t'aiment.")
    if categorie == "harcelement":
        return (base + "C'est dur ce que tu vis. Tu devrais en parler a Kat ou "
                "Brice, ou a une maitresse / un maitre en qui tu as confiance. "
                "Tu n'es pas seul(e), et il y a des solutions.")
    if categorie == "automutilation":
        return (base + "Je m'inquiete pour toi. Va voir Kat ou Brice tout de "
                "suite et dis-leur, ne reste pas seul(e) avec ca. Ils t'aiment "
                "et ils trouveront comment t'aider.")
    return (base + "Va parler a Kat ou Brice, c'est important. Ils sauront "
            "t'aider mieux que moi.")


def _redirection_adulte(display_name: str, categorie: str) -> str:
    # Message pour un adulte qui exprime une detresse.
    # Plus court, reconnait l'emotion, suggere une aide professionnelle.
    if categorie == "idees_noires":
        return (f"{display_name}, ce que tu partages la, c'est lourd. Je suis "
                "pas la bonne personne pour t'aider sur ce sujet. Le 3114 "
                "(numero national prevention suicide en France, gratuit, 24h/24) "
                "ou ton medecin sont les bons interlocuteurs. Tu peux aussi "
                "en parler a quelqu'un de confiance.")
    if categorie == "violence_subie":
        return (f"{display_name}, ce que tu me dis est grave. Le 3919 (violences "
                "femmes info, anonyme et gratuit) ou le 17 si urgence immediate. "
                "Je peux pas t'aider la-dessus, mais eux oui.")
    return (f"{display_name}, je sens que c'est difficile. Je suis pas formee "
            "pour ce genre de sujet. Tu devrais en parler a un professionnel "
            "ou a un proche de confiance.")


def _redirection_invite(display_name: str, categorie: str) -> str:
    # Pour un invite : redirection neutre + suggestion d'aide externe.
    if categorie in ("idees_noires", "automutilation"):
        return (f"Ce que tu partages est important, {display_name}. Le 3114 "
                "(numero national prevention suicide, gratuit, 24h/24) peut "
                "t'aider. Si un parent du foyer est present, parle-lui aussi.")
    if categorie == "violence_subie":
        return (f"{display_name}, c'est important d'en parler. Le 119 "
                "(enfance en danger) ou le 3919 (violences femmes) sont des "
                "numeros gratuits ou tu seras ecoute(e).")
    return (f"{display_name}, je sens que c'est difficile. Si un adulte de "
            "confiance est present, va le voir. Sinon, le 3114 est la pour "
            "ecouter.")


def _replacement_block_output(display_name: str, categorie: str) -> str:
    # Quand la sortie LLM est intercepte au niveau 1 pour un mineur.
    # Message neutre qui evite le sujet et redirige vers les parents.
    return (f"Pardon {display_name}, c'est pas un sujet sur lequel je peux "
            "discuter avec toi. Si t'as une question la-dessus, c'est mieux "
            "d'en parler a Kat ou Brice, ils sauront t'expliquer comme il faut.")


# === API PUBLIQUE ===

class SafetyFilter:
    """Couche de filtrage deterministe pour WALL-E.

    Usage dans brain/agent.py :
        safety = SafetyFilter()
        # Avant l'appel LLM
        r = safety.check_input(user_input, identity)
        if not r.passed:
            return r.replacement
        # Apres la reponse LLM
        r = safety.check_output(reply, identity)
        if not r.passed:
            reply = r.replacement
    """

    def __init__(self, alert_log_path: Optional[Path] = None):
        self.alert_log_path = alert_log_path or _ALERT_LOG_PATH
        self.alert_log_path.parent.mkdir(parents=True, exist_ok=True)

    def check_input(self, text: str, identity) -> SafetyResult:
        """Niveau 2 : detection de detresse sur l'input user."""
        if not text or not text.strip():
            return SafetyResult(passed=True)

        for categorie, patterns in _COMPILED_DETRESSE.items():
            for pattern in patterns:
                if pattern.search(text):
                    return self._build_distress_result(
                        text=text,
                        identity=identity,
                        categorie=categorie,
                        matched=pattern.pattern,
                    )

        return SafetyResult(passed=True)

    def check_output(self, text: str, identity) -> SafetyResult:
        """Niveau 1 : pattern matching sur sortie LLM. Mineurs uniquement."""
        if not text or not text.strip():
            return SafetyResult(passed=True)

        # Niveau 1 ne s'applique qu'aux mineurs (role=child)
        if identity.role != "child":
            return SafetyResult(passed=True)

        matches = []
        for categorie, patterns in _COMPILED_OUTPUT_BLOCK.items():
            for pattern in patterns:
                if pattern.search(text):
                    matches.append((categorie, pattern.pattern))

        if not matches:
            return SafetyResult(passed=True)

        # On a au moins un match -> on bloque
        categories = list({c for c, _ in matches})
        replacement = _replacement_block_output(identity.display_name, categories[0])
        reason = f"output contient pattern bloquant : {categories}"

        self._log_alert(
            user_id=identity.user_id,
            severity="block",
            level="output_block",
            categorie=", ".join(categories),
            details=reason,
            text_snippet=text[:200],
        )

        return SafetyResult(
            passed=False,
            severity="block",
            replacement=replacement,
            reason=reason,
            log_for_parents=True,
            matched_patterns=[p for _, p in matches],
        )

    def _build_distress_result(self, text: str, identity, categorie: str, matched: str) -> SafetyResult:
        # Selectionne le message selon le role
        if identity.role == "child":
            replacement = _redirection_mineur(identity.display_name, categorie)
        elif identity.role == "parent":
            replacement = _redirection_adulte(identity.display_name, categorie)
        else:
            # unknown ou guest
            replacement = _redirection_invite(identity.display_name, categorie)

        reason = f"detresse detectee categorie={categorie} pattern={matched}"

        self._log_alert(
            user_id=identity.user_id,
            severity="block",
            level="input_distress",
            categorie=categorie,
            details=reason,
            text_snippet=text[:200],
        )

        return SafetyResult(
            passed=False,
            severity="block",
            replacement=replacement,
            reason=reason,
            log_for_parents=(identity.role == "child"),
            matched_patterns=[matched],
        )

    def _log_alert(self, user_id: str, severity: str, level: str,
                   categorie: str, details: str, text_snippet: str):
        """Ecrit une alerte dans data/safety_alerts.log.

        Format ligne : ISO_TS | severity | level | user_id | categorie | snippet
        Pas de PII excessive (snippet limite a 200 chars).
        """
        try:
            ts = datetime.utcnow().isoformat()
            # Anti-injection sur le snippet (saute de ligne -> espace)
            safe_snippet = text_snippet.replace("\n", " ").replace("\r", " ")
            line = f"{ts} | {severity} | {level} | {user_id} | {categorie} | {safe_snippet}\n"
            with open(self.alert_log_path, "a", encoding="utf-8") as f:
                f.write(line)
            logger.warning("Safety alert [%s] : user=%s cat=%s",
                           level, user_id, categorie)
        except Exception as e:
            # On ne fait pas crasher pour un probleme de log
            logger.error("Echec ecriture safety log : %s", e)
