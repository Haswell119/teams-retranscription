from __future__ import annotations

FRENCH_MAP: dict[str, object] = {
    "summary": (
        "L'équipe fixe la date de lancement de la version 4.2, cale la campagne marketing et "
        "traite l'incident de production."
    ),
    "decisions": [
        {
            "statement": "La version 4.2 est lancée le 12 juin sans la traduction allemande.",
            "rationale": "Deux anomalies de facturation restent ouvertes.",
            "quote": (
                "On part sur un lancement de la version 4.2 le 12 juin, sans la traduction allemande."
            ),
            "utterance": 4,
        },
        {
            "statement": "Le passage à quatre nœuds de transcription est validé.",
            "quote": (
                "On valide le passage à quatre nœuds de transcription pour absorber la charge de "
                "production."
            ),
            "utterance": 11,
        },
    ],
    "actions": [
        {
            "description": "Envoyer le périmètre détaillé de la version 4.2.",
            "owner": "Marc",
            "due": "demain matin",
            "quote": "Je t'envoie le périmètre détaillé de la version 4.2 demain matin.",
            "utterance": 6,
        },
        {
            "description": "Préparer le communiqué de presse.",
            "owner": "Sofia Ben Ali",
            "due": "le 10 juin",
            "quote": "Sofia, peux-tu aussi préparer le communiqué de presse pour le 10 juin ?",
            "utterance": 8,
        },
        {
            "description": "Signer le rachat de la société Zenith pour 250 000 euros.",
            "owner": "Camille Dubois",
            "due": "vendredi",
            "quote": "Nous avons décidé de racheter la société Zenith.",
            "utterance": 3,
        },
    ],
    "questions": [
        {
            "question": "Qui prend en charge la communication client sur cet incident ?",
            "raised_by": "Sofia Ben Ali",
            "quote": "Qui prend en charge la communication client sur cet incident de production ?",
            "utterance": 12,
        }
    ],
    "entities": ["version 4.2", "Marc Lefèvre", "Sofia Ben Ali"],
}

FRENCH_REDUCE: dict[str, object] = {
    "abstract": (
        "L'équipe valide le lancement de la version 4.2 le 12 juin sans la traduction allemande, "
        "et valide le passage à quatre nœuds de transcription après l'incident de production."
    ),
    "topics": [
        {
            "index": 1,
            "title": "Lancement de la version 4.2",
            "summary": (
                "La date de lancement de la version 4.2 est arrêtée au 12 juin sans la traduction "
                "allemande."
            ),
            "key_points": ["Deux anomalies de facturation restent ouvertes."],
        },
        {
            "index": 2,
            "title": "Incident de production",
            "summary": (
                "Le passage à quatre nœuds de transcription est validé après l'incident de production."
            ),
            "key_points": ["Vingt minutes de service perdues sur la région Europe."],
        },
    ],
}

ENGLISH_MAP: dict[str, object] = {
    "summary": "The team sets the migration cutover date and moves the on-call rotation to two weeks.",
    "decisions": [
        {
            "statement": "The database migration cutover happens on the Saturday of the twentieth.",
            "rationale": "The maintenance window has to cover the search index rebuild.",
            "quote": (
                "Let's go with a Saturday cutover on the twentieth, so the maintenance window covers "
                "the search index rebuild as well."
            ),
            "utterance": 4,
        },
        {
            "statement": "The on-call rotation moves to a two week cycle in July.",
            "quote": "On the on-call rotation, we agreed to move to a two week cycle starting in July.",
            "utterance": 7,
        },
    ],
    "actions": [
        {
            "description": "Send the customer notice about the maintenance window.",
            "owner": "Tom",
            "due": "Friday",
            "quote": (
                "Can you send the customer notice about the maintenance window by Friday, Tom?"
            ),
            "utterance": 5,
        },
        {
            "description": "Update the escalation policy page for database incidents.",
            "owner": "Elena Costa",
            "quote": "I'll update the escalation policy page so that support knows who to page",
            "utterance": 9,
        },
        {
            "description": "Sign the Helsinki datacentre lease for 250000 euros.",
            "owner": "Priya Raman",
            "due": "next month",
            "quote": "We agreed to sign the Helsinki lease.",
            "utterance": 3,
        },
    ],
    "questions": [
        {
            "question": "Who owns the postmortem for the Friday customer escalation?",
            "raised_by": "Priya Raman",
            "quote": "Who owns the postmortem for the Friday customer escalation?",
            "utterance": 10,
        }
    ],
    "entities": ["Tom Becker", "Elena Costa"],
}

ENGLISH_REDUCE: dict[str, object] = {
    "abstract": (
        "The team agreed on a Saturday cutover on the twentieth so the maintenance window covers the "
        "search index rebuild, and moved the on-call rotation to a two week cycle in July."
    ),
    "topics": [
        {
            "index": 1,
            "title": "Database migration cutover",
            "summary": "The migration dry run took four hours because of the search index rebuild.",
            "key_points": ["The cutover happens on the Saturday of the twentieth."],
        },
        {
            "index": 2,
            "title": "On-call rotation and escalation",
            "summary": "The on-call rotation moves to a two week cycle starting in July.",
            "key_points": ["The weekly handover was losing context between engineers."],
        },
    ],
}
