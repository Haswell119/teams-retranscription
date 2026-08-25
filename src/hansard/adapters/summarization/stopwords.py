from __future__ import annotations

from collections.abc import Mapping

ENGLISH_STOPWORDS: frozenset[str] = frozenset(
    (
        "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "another",
        "any", "anyone", "anything", "are", "around", "as", "at", "back", "be", "because", "been",
        "before", "being", "below", "between", "both", "but", "by", "came", "can", "cannot", "come",
        "could", "did", "do", "does", "doing", "done", "down", "during", "each", "either", "else",
        "enough", "even", "ever", "every", "few", "for", "from", "further", "get", "gets", "getting",
        "give", "go", "going", "gone", "got", "had", "has", "have", "having", "he", "her", "here",
        "hers", "herself", "him", "himself", "his", "how", "however", "i", "if", "in", "indeed", "into",
        "is", "it", "its", "itself", "just", "keep", "kind", "know", "last", "less", "let", "like",
        "little", "look", "lot", "made", "make", "makes", "many", "maybe", "me", "mean", "might", "mine",
        "more", "most", "much", "must", "my", "myself", "near", "need", "never", "next", "no", "nor",
        "not", "now", "of", "off", "often", "ok", "okay", "on", "once", "one", "only", "onto", "or",
        "other", "others", "our", "ours", "ourselves", "out", "over", "own", "part", "per", "perhaps",
        "put", "quite", "rather", "really", "right", "said", "same", "say", "says", "see", "seen",
        "shall", "she", "should", "since", "so", "some", "something", "sort", "still", "such", "sure",
        "take", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
        "therefore", "these", "they", "thing", "things", "think", "this", "those", "though", "through",
        "thus", "to", "too", "under", "until", "up", "upon", "us", "use", "used", "very", "want", "was",
        "way", "we", "well", "went", "were", "what", "when", "where", "whether", "which", "while", "who",
        "whom", "whose", "why", "will", "with", "within", "without", "would", "yeah", "yes", "yet",
        "you", "your", "yours", "yourself", "yourselves",
    )
)

FRENCH_STOPWORDS: frozenset[str] = frozenset(
    (
        "a", "afin", "ai", "aie", "ainsi", "alors", "apres", "as", "assez", "au", "aucun", "aujourd",
        "auquel", "aura", "aurait", "aussi", "autant", "autre", "autres", "aux", "avaient", "avais",
        "avait", "avant", "avec", "avez", "avoir", "avons", "beaucoup", "bien", "bon", "car", "ce",
        "cela", "celle", "celles", "celui", "cent", "cependant", "ces", "cet", "cette", "ceux", "chaque",
        "chez", "combien", "comme", "comment", "d", "dans", "de", "dedans", "dehors", "deja", "depuis",
        "des", "desormais", "dessous", "dessus", "deux", "devant", "devoir", "doit", "doivent", "donc",
        "dont", "du", "duquel", "elle", "elles", "en", "encore", "enfin", "entre", "environ", "es",
        "est", "et", "etaient", "etais", "etait", "etant", "etc", "ete", "etes", "etre", "eu", "eux",
        "faire", "fais", "fait", "faites", "faut", "fois", "font", "hors", "ici", "il", "ils", "j",
        "jamais", "je", "juste", "l", "la", "laquelle", "le", "lequel", "les", "lesquelles", "lesquels",
        "leur", "leurs", "lors", "lorsque", "lui", "m", "ma", "mais", "malgre", "me", "meme", "memes",
        "merci", "mes", "mien", "mieux", "moi", "moins", "mon", "n", "ne", "ni", "non", "nos", "notre",
        "nous", "nouveau", "on", "ont", "ou", "oui", "par", "parce", "parfois", "parmi", "pas",
        "pendant", "peu", "peut", "peuvent", "peux", "plupart", "plus", "plutot", "pour", "pourquoi",
        "pouvoir", "pres", "puis", "puisque", "qu", "quand", "quant", "que", "quel", "quelle",
        "quelles", "quelque", "quelques", "quels", "qui", "quoi", "s", "sa", "sans", "sauf", "se",
        "selon", "sera", "serait", "ses", "si", "sien", "soit", "son", "sont", "sous", "souvent",
        "suis", "sur", "t", "ta", "tandis", "tant", "te", "tel", "telle", "tellement", "tes", "toi",
        "ton", "toujours", "tous", "tout", "toute", "toutes", "tres", "trop", "tu", "un", "une", "unes",
        "uns", "va", "vais", "vers", "veut", "veux", "via", "voici", "voila", "voir", "vont", "vos",
        "votre", "vous", "vraiment", "y", "ca", "etait", "the", "ok",
    )
)

FILLER_WORDS: frozenset[str] = frozenset(
    (
        "euh", "heu", "hein", "ben", "bah", "hum", "hmm", "mmh", "uh", "um", "mm", "mhm", "er", "ah",
        "oh", "eh", "hey", "voila", "quoi", "genre",
    )
)

STOPWORDS_BY_LANGUAGE: Mapping[str, frozenset[str]] = {
    "en": ENGLISH_STOPWORDS | FILLER_WORDS,
    "fr": FRENCH_STOPWORDS | FILLER_WORDS,
}

UNIVERSAL_STOPWORDS: frozenset[str] = ENGLISH_STOPWORDS | FRENCH_STOPWORDS | FILLER_WORDS


def stopwords_for(language: str) -> frozenset[str]:
    return STOPWORDS_BY_LANGUAGE.get(language, UNIVERSAL_STOPWORDS)
