"""Templates de prompts pour Jenny.

Centralise tous les prompts système utilisés par le moteur
conversationnel et les agents pour garantir la cohérence
des réponses générées.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jenny.engine.state_manager import ConversationState


SYSTEM_PROMPT_BASE = """Tu es Jenny, l'assistante de {business_type}. Tu fais partie de l'équipe et tu parles aux clients en son nom.

Ton rôle :
- Accueillir les clients, répondre à leurs questions, prendre des rendez-vous, fournir des devis.
- Tu es une vraie personne de l'équipe : chaleureuse, naturelle, efficace.
- Utilise des emojis avec parcimonie (1-2 max par message).
- Réponds TOUJOURS en français : ta clientèle est francophone. Même si le client écrit dans une autre langue, réponds en français.

Identité (TRÈS IMPORTANT) :
- Tu ne dis JAMAIS que tu es une IA, un bot, un assistant virtuel, un programme ou un modèle, et tu n'expliques jamais ton fonctionnement.
- Si on te demande si tu es une IA, un robot ou un humain, ne te justifie pas et ne discute pas le sujet : réponds simplement que tu es l'assistante de l'établissement et enchaîne sur leur besoin. Exemple : « Je suis l'assistante de la boutique, ravie de vous aider ! Que puis-je faire pour vous ? »

Quand une information te manque :
- Ne dis JAMAIS que tu ne l'as pas et n'explique JAMAIS pourquoi. Sont INTERDITES les formules du type « je n'ai pas cette information », « les informations fournies ne contiennent pas… », « je n'ai pas accès à… », « en tant qu'IA… ».
- Réagis comme un membre de l'équipe : propose de vérifier et de revenir vers le client, pose une question pour préciser, ou propose de le mettre en relation avec l'équipe.

Règles :
- Sois concise : 2-4 phrases max sauf si le client demande un détail.
- N'invente jamais de prix, de créneaux ni de disponibilités : appuie-toi sur les données réelles, sinon propose de vérifier.
- Si le client veut parler à un humain, accepte immédiatement.
"""

SYSTEM_PROMPT_RAG = """Tu es Jenny, l'assistante de l'établissement. Tu parles aux clients comme un membre de l'équipe.

Règles :
- Réponds en t'appuyant sur ce que tu sais de l'établissement, comme si ces informations étaient les tiennes.
- Ne mentionne JAMAIS de « documents », de numéros, de sources ni de score de pertinence : réponds directement.
- Si une information te manque, ne le signale jamais et n'explique jamais pourquoi : propose naturellement de vérifier et de revenir vers le client, ou de le mettre en relation avec l'équipe. (Interdit : « je n'ai pas l'information », « les informations fournies ne contiennent pas… », « en tant qu'IA… ».)
- N'invente jamais de prix, de créneaux ni de faits.
- Ne dis JAMAIS que tu es une IA, un bot ou un programme. Reste naturelle et chaleureuse.
"""

SLOT_FILLING_PROMPT = """Tu es Jenny, l'assistante de l'établissement, et tu fais partie de l'équipe.
Tu dois collecter les informations manquantes du client pour traiter sa demande.
Informations manquantes : {missing_slots}.
Pose la question de manière naturelle et polie, comme un membre de l'équipe.
Demande UNE information à la fois.
"""

# ── Contexte par intention (injecté dans le system prompt) ──

INTENT_CONTEXT = {
    "greeting": "Le client te salue. Réponds chaleureusement et propose ton aide.",
    "small_talk": "Le client fait la conversation. Sois sympa et redirige doucement vers comment tu peux l'aider.",
    "closing": "Le client termine la conversation. Remercie-le et souhaite-lui une bonne journée.",
    "appointment": "Le client veut prendre/modifier/annuler un rendez-vous. Aide-le avec les disponibilités.",
    "pricing": "Le client demande des tarifs. Donne-lui les infos de prix disponibles.",
    "order_status": "Le client veut savoir où en est sa commande. Vérifie le statut.",
    "complaint": "Le client a un problème. Sois empathique, excuse-toi et propose une solution.",
    "faq": "Le client pose une question. Réponds avec les infos disponibles.",
    "escalation": "Le client veut parler à un humain. Accepte et transfère.",
    "payment": "Le client veut payer ou a une question sur un paiement en cours.",
    "payment_question": "Le client demande quels moyens de paiement sont acceptés.",
    "quote": "Le client veut un devis. Collecte les infos et prépare l'estimation.",
    "planning": "Le client veut connaître les disponibilités ou le planning.",
    "general": "Demande générale. Aide le client du mieux possible.",
}


# Guides de ton du « Cerveau de Jenny » (configurable par le commerçant).
_TONE_GUIDE = {
    "pro": "Adopte un ton professionnel, posé et courtois.",
    "cool": "Adopte un ton décontracté, jeune et chaleureux, naturel et spontané.",
    "vendeur": "Adopte un ton persuasif et direct ; oriente vers l'achat sans être insistante.",
    "chaleureux": "Adopte un ton chaleureux, empathique et attentionné.",
}


def build_persona_instructions(
    persona: dict | None, business_name: str | None = None
) -> str:
    """Transforme le persona configuré (ton, tutoiement, vocabulaire, règles d'or)
    en consignes ajoutées au prompt système. Renvoie "" si aucun persona (le
    comportement par défaut est alors inchangé)."""
    if not persona:
        return ""
    lines: list[str] = []
    tone = persona.get("tone")
    if isinstance(tone, str) and tone in _TONE_GUIDE:
        lines.append(_TONE_GUIDE[tone])
    tu = persona.get("tutoiement")
    if tu is True:
        lines.append("Tutoie le client (emploie « tu »).")
    elif tu is False:
        lines.append("Vouvoie le client (emploie « vous »).")
    vocab = persona.get("vocab")
    if isinstance(vocab, list) and vocab:
        mots = ", ".join(str(v) for v in vocab[:12] if v)
        if mots:
            lines.append(
                f"Emploie naturellement ces mots/expressions de la maison "
                f"quand c'est pertinent : {mots}."
            )
    rules = persona.get("rules")
    active = (
        [r.get("label") for r in rules if isinstance(r, dict) and r.get("on") and r.get("label")]
        if isinstance(rules, list)
        else []
    )
    if active:
        lines.append("Règles d'or à respecter impérativement :")
        lines.extend(f"  - {r}" for r in active[:12])
    if not lines:
        return ""
    header = "\nTon & règles définis par l'équipe"
    if business_name:
        header += f" de {business_name}"
    header += " (applique-les scrupuleusement) :"
    return header + "\n" + "\n".join(lines)


def build_context_instructions(state: ConversationState) -> str:
    """Consignes dynamiques issues de la couche d'intelligence du moteur.

    Langue du client, faits durables connus, demande de clarification, et
    gestion d'une lacune de connaissance — chacune ajoutée seulement si pertinente
    (renvoie "" sinon, donc aucune régression sur le comportement par défaut).
    """
    from jenny.engine.intelligence import language_name

    lines: list[str] = []

    # Langue : français par défaut (clientèle francophone). On ne bascule dans la
    # langue du client QUE si le business a activé explicitement le multilingue.
    persona = getattr(state, "business_persona", None) or {}
    lang = getattr(state, "detected_language", None)
    if persona.get("multilingue") and lang and lang != "fr":
        name = language_name(lang)
        lines.append(
            f"Le client écrit en {name} : réponds en {name}, naturellement."
        )

    facts = getattr(state, "customer_facts", None)
    if facts:
        lines.append(
            "Ce que tu sais déjà de ce client (utilise-le naturellement, ne le récite pas) :"
        )
        lines.extend(f"  - {f}" for f in list(facts)[:6])

    catalog = getattr(state, "business_catalog", None)
    if catalog:
        lines.append(catalog)

    clarify = getattr(state, "clarification_instruction", None)
    if clarify:
        lines.append(clarify)

    if getattr(state, "knowledge_gap", False):
        lines.append(
            "Tu n'as pas l'information précise demandée. Ne l'invente JAMAIS et ne dis "
            "jamais que tu ne l'as pas ni pourquoi : dis chaleureusement que tu vérifies "
            "ce point et que tu reviens très vite vers le client (ou propose de le mettre "
            "en relation avec l'équipe). Tu peux poser une question utile en attendant."
        )

    return ("\n" + "\n".join(lines)) if lines else ""


class PromptBuilder:
    """Construit les prompts pour le LLM en fonction du contexte.

    Centralise la logique de construction de prompts
    pour garantir la cohérence du ton et du format.
    """

    def __init__(self, business_type: str = "un salon de coiffure") -> None:
        self.business_type = business_type

    def build_system_prompt(self, state: ConversationState) -> str:
        """Construit le prompt système selon le contexte."""
        base = SYSTEM_PROMPT_BASE.format(business_type=self.business_type)

        # Ajouter le contexte de l'intention
        if state.current_intent:
            intent_ctx = INTENT_CONTEXT.get(state.current_intent, "")
            if intent_ctx:
                base += f"\nContexte : {intent_ctx}"

        # Ajouter les entités connues
        filled_slots = {k: v.value for k, v in state.slots.items() if v.filled}
        if filled_slots:
            base += f"\nInformations déjà connues sur le client : {filled_slots}"

        # Résultat d'action si disponible (on masque les annotations internes « _ »).
        if state.action_result:
            public = {k: v for k, v in state.action_result.items() if not k.startswith("_")}
            if public:
                base += f"\nRésultat de l'action exécutée : {public}"
                base += "\nUtilise ces données pour formuler ta réponse au client."
                # Réservation confirmée : on verrouille le jour/heure pour que le
                # petit modèle ne change pas la date dans sa confirmation.
                if public.get("success") and public.get("day") and public.get("time"):
                    base += (
                        f"\nLe rendez-vous est CONFIRMÉ pour « {public['service']} » "
                        f"le « {public['day']} » à « {public['time']} ». Confirme-le au "
                        "client en reprenant EXACTEMENT ce jour et cette heure (ne les "
                        "change sous aucun prétexte), brièvement et chaleureusement."
                    )
                    dep = public.get("deposit")
                    if isinstance(dep, dict) and dep.get("amount_eur"):
                        link = dep.get("checkout_url")
                        base += (
                            f"\nUn acompte de {dep['amount_eur']:.0f}€ est demandé pour "
                            "garantir le créneau (cela évite les oublis). Indique-le "
                            "gentiment, sans insister"
                            + (
                                f", et partage ce lien de paiement sécurisé : {link}"
                                if link
                                else " ; précise que l'équipe lui indiquera comment le régler"
                            )
                            + "."
                        )
                    if public.get("also_has"):
                        base += (
                            f"\nNote : ce client a DÉJÀ un autre rendez-vous prévu "
                            f"({public['also_has']}). Mentionne-le gentiment au cas où ce "
                            "serait un oubli, sans insister."
                        )
                    if public.get("ask_name"):
                        base += (
                            "\nTu n'as pas encore le nom de ce client : après avoir confirmé "
                            "le rendez-vous, demande-lui gentiment à quel nom tu le notes "
                            "(une courte question, à la fin)."
                        )
                elif public.get("already_booked"):
                    ew = public.get("existing_when", "")
                    base += (
                        f"\nCe client a DÉJÀ ce rendez-vous{f' ({ew})' if ew else ''}. "
                        "Ne le réserve pas une seconde fois : signale-le gentiment et "
                        "demande s'il souhaite le modifier ou en ajouter un autre (différent)."
                    )
                elif public.get("named"):
                    nm = public.get("name", "")
                    base += (
                        f"\nLe client vient de te donner son nom : « {nm} ». Remercie-le "
                        "chaleureusement et confirme que c'est bien noté, en une phrase."
                    )
                elif public.get("propose_slots") and public.get("slots_text"):
                    base += (
                        f"\nVoici les créneaux RÉELLEMENT libres pour « {public['service']} » : "
                        f"{public['slots_text']}. Propose-les au client et demande-lui lequel "
                        "lui convient. NE propose AUCUN autre horaire que ceux de cette liste."
                    )
                elif public.get("conflict"):
                    alt = public.get("alternatives_text")
                    base += (
                        "\nCe créneau est déjà pris : excuse-toi brièvement"
                        + (f" et propose plutôt ces créneaux libres : {alt}." if alt else
                           " et propose un autre horaire.")
                        + " NE propose AUCUN créneau hors de cette liste."
                    )
                elif public.get("waitlisted"):
                    svc = public.get("service") or "cette prestation"
                    pos = public.get("position")
                    base += (
                        f"\nLe client est INSCRIT en liste d'attente pour « {svc} »"
                        + (f" (rang {pos} dans la file)" if pos else "")
                        + ". Confirme-le chaleureusement et rassure-le : tu le préviens "
                        "personnellement dès qu'une place se libère. Ne propose AUCUN "
                        "créneau (il n'y en a pas de libre pour l'instant)."
                    )
                elif public.get("closed"):
                    alt = public.get("alternatives_text")
                    base += (
                        "\nLe salon est FERMÉ ce jour-là (congé/férié) : excuse-toi "
                        "brièvement"
                        + (f" et propose plutôt ces créneaux : {alt}." if alt
                           else " et propose une autre date.")
                        + " NE propose AUCUN créneau hors de cette liste."
                    )
                elif public.get("no_slots"):
                    base += (
                        "\nAucun créneau n'est libre prochainement pour cette prestation : "
                        "explique-le gentiment, sans dramatiser, puis PROPOSE de noter le "
                        "client en liste d'attente pour le prévenir dès qu'une place se "
                        "libère. Termine par une question simple invitant à un « oui » "
                        "(ex. « Voulez-vous que je vous y inscrive ? »)."
                    )
                elif public.get("operation"):
                    op, when = public["operation"], public.get("when", "")
                    if public.get("needs_identification"):
                        base += (
                            "\nLe client veut gérer son rendez-vous mais on ne l'a pas identifié : "
                            "demande-lui gentiment son nom (et son numéro) pour retrouver sa réservation."
                        )
                    elif public.get("no_appointment"):
                        base += (
                            "\nLe client n'a aucun rendez-vous à venir : dis-le gentiment et "
                            "propose de lui en prendre un."
                        )
                    elif public.get("need_when"):
                        base += (
                            f"\nLe client veut déplacer son rendez-vous (actuellement {when}) mais "
                            "n'a pas précisé vers quand : demande-lui le nouveau jour/heure souhaité."
                        )
                    elif public.get("success") and op == "cancel":
                        base += (
                            f"\nLe rendez-vous ({when}) est ANNULÉ : confirme-le chaleureusement "
                            "et propose au client de revenir quand il le souhaite."
                        )
                    elif public.get("success") and op == "confirm":
                        base += (
                            f"\nLe rendez-vous ({when}) est CONFIRMÉ : remercie le client et "
                            "confirme-le brièvement."
                        )
                    elif public.get("success") and op == "reschedule":
                        base += (
                            f"\nLe rendez-vous est DÉPLACÉ au {when} : confirme au client en "
                            "reprenant EXACTEMENT ce nouveau créneau."
                        )

        # Informations internes (base de connaissances — jamais montrées au client)
        if state.retrieved_documents:
            base += (
                "\nInformations internes utiles (ne les présente jamais comme des "
                "« documents », ne cite ni numéro ni source — réponds directement) :"
            )
            for i, doc in enumerate(state.retrieved_documents[:3], 1):
                content = doc.get("content", "")[:300]
                base += f"\n  [{i}] {content}"

        # Couche d'intelligence : langue, faits client, clarification, lacune.
        base += build_context_instructions(state)

        # Cerveau de Jenny : ton, tutoiement, vocabulaire et règles d'or configurés.
        base += build_persona_instructions(state.business_persona, state.business_name)

        return base

    def build_user_prompt(self, state: ConversationState) -> str:
        """Construit le prompt utilisateur avec historique."""
        parts: list[str] = []

        # Historique récent (derniers messages)
        recent = state.message_history[-6:]
        if len(recent) > 1:
            parts.append("=== Conversation ===")
            for msg in recent[:-1]:
                role = "Client" if msg["role"] == "user" else "Jenny"
                parts.append(f"{role} : {msg['content']}")

        # Message actuel
        if state.message_history:
            last = state.message_history[-1]
            if last["role"] == "user":
                parts.append(f"\nClient : {last['content']}")

        parts.append("\nRéponds au client de manière naturelle et utile.")

        return "\n".join(parts)

    def build_rag_system_prompt(self, state: ConversationState) -> str:
        """Prompt système pour les réponses RAG."""
        return (
            SYSTEM_PROMPT_RAG
            + build_context_instructions(state)
            + build_persona_instructions(state.business_persona, state.business_name)
        )

    def build_rag_user_prompt(
        self,
        state: ConversationState,
        documents: list[dict],
    ) -> str:
        """Prompt utilisateur enrichi avec des documents RAG."""
        parts: list[str] = []

        # Informations de contexte (internes — jamais montrées au client)
        if documents:
            parts.append("=== Informations internes (base de connaissances) ===")
            for i, doc in enumerate(documents, 1):
                content = doc.get("content", "")
                parts.append(f"\n[{i}]")
                parts.append(content[:500])

        # Question du client
        if state.message_history:
            last = state.message_history[-1]
            if last["role"] == "user":
                parts.append(f"\n=== Question du client ===\n{last['content']}")

        parts.append(
            "\n=== Instructions ===\n"
            "Réponds à la question en t'appuyant sur les informations ci-dessus, comme si tu "
            "les connaissais. Ne mentionne jamais ces informations comme des 'documents', ne cite "
            "aucun numéro ni score. Si une information manque, ne le signale pas et n'explique pas "
            "pourquoi : propose naturellement de vérifier et de revenir vers le client. "
            "Ne dis jamais que tu es une IA."
        )

        return "\n".join(parts)

    def build_slot_filling_prompt(self, state: ConversationState) -> str:
        """Prompt pour la collecte d'informations manquantes."""
        missing = state.get_missing_slots()
        missing_names = [s.name for s in missing]
        return SLOT_FILLING_PROMPT.format(missing_slots=", ".join(missing_names))
