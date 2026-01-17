language_articles: dict[str, list[str]] = {
    # English
    "en": ["a", "an", "the"],
    # Spanish
    "es": ["el", "la", "los", "las", "un", "una", "unos", "unas"],
    # French (with elision)
    "fr": ["le", "la", "les", "un", "une", "des", "l'"],
    # German (base forms only)
    "de": ["der", "die", "das", "ein", "eine"],
    # Italian (including elision)
    "it": ["il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "un'", "l'"],
    # Portuguese
    "pt": ["o", "a", "os", "as", "um", "uma", "uns", "umas"],
    # Dutch
    "nl": ["de", "het", "een"],
    # Swedish (indefinite only; definite is suffixed)
    "sv": ["en", "ett"],
    # Norwegian (Bokmål/Nynorsk shared forms)
    "no": ["en", "ei", "et"],
    # Danish (definite is suffixed)
    "da": ["en", "et"],
    # Romanian (indefinite only; definite is enclitic)
    "ro": ["un", "o", "niște"],
    # Hungarian
    "hu": ["a", "az", "egy"],
    # Turkish (indefinite only)
    "tr": ["bir"],
    # Modern Greek (transliterated with correct forms)
    "el": ["ο", "η", "το", "ένας", "μία", "ένα"],
}
