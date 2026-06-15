"""Banc d'essai (eval) de Jenny.

Mesure l'efficacité de Jenny sur des scénarios clients réalistes et variés :
grounding (réponses fondées sur la base de connaissances), respect de la persona
(jamais « IA », pas de fuite RAG), clarification quand le besoin est flou,
détection des lacunes, et réponse dans la langue du client.
"""

from jenny.eval.scenarios import SCENARIOS, Scenario, Turn

__all__ = ["SCENARIOS", "Scenario", "Turn"]
