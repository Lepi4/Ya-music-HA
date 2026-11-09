"""Presentation taxonomy for Rotor genres; original playback seeds stay intact."""
from __future__ import annotations

import re


# National and regional variants belong together even when their API parent is
# rock, pop or rap. Check words/prefixes, not incidental substrings (e.g. trance).
_REGIONAL = re.compile(
    r"(?:^|[\s-])(?:israeli|turkish|russian|rus(?=rock|pop|rap|folk|bards|estrada)|"
    r"kazakh|kaz(?=estrada)|qazaq|uzbek|uz(?=retropop)|arabic|egypt|jewish|"
    r"balkan|celtic|african|afro|latin|amer(?=folk)|american|japanese|japan|"
    r"korean|chinese|italian|french|german|deutsche|dutch|scandinavian|"
    r"armenian|azerbaijan|georgian|caucasian|tatar|khaleeji|levant|moroccan|"
    r"iraqi|urdu|punjabi|oriental|eastern|euro(?=folk)|argentine|brazil|"
    r"us(?=-)|uk(?=-)|brit|texas|chicago|detroit|louisiana|memphis|miami|"
    r"philadelphia|east-coast|west-coast|goa|gypsy|израиль|турец|русск|"
    r"казах|узбек|араб|египет|еврей|балкан|кельт|африкан|афро|латино|"
    r"американ|япон|корей|китай|итальян|француз|немец|голланд|скандинав|"
    r"армян|азербайдж|грузин|кавказ|татар|халидж|левант|марокк|ирак|"
    r"урду|панджаб|восточн|европейск|аргентин|бразиль|британ|техас|"
    r"чикаг|детройт|луизиан|мемфис|майами|филадельф|цыган)", re.I,
)
_ETHNIC_STYLES = {
    "folk", "ethnic", "mizrahi", "bollywood", "arabesquemusic", "tarab",
    "mahraganat", "shelatgenre", "raigenre", "dabkegenre", "sufifolkgenre",
    "kpop", "qazaqpop", "mandopop", "mpb", "bachata", "bolero", "bossa-nova",
    "bhangra", "gagaku", "gqom", "guaguancó", "calypso", "kwaito", "cumbia",
    "mambo", "mariachi", "milonga", "rumba", "salsa", "samba", "fado",
    "flamenco", "forro", "highlife", "cha-cha", "suomisaundi",
}
_ROOTS = {
    "folkgenre": "folk", "shanson": "estrada", "chanson": "estrada",
    "ska": "reggae", "forchildren": "children", "fairytales": "children",
    "naturesounds": "relax", "other": "other",
}
_EXACT = {
    "prog": "allrock", "newwave": "allrock", "neo-prog": "allrock",
    "heavy-psych": "allrock", "neo-psychedelia": "allrock", "psychobilly": "allrock",
    "gothabilly": "allrock", "skiffle": "allrock", "twist": "allrock",
    "ebm": "electronics", "bit-8": "electronics", "chiptune": "electronics",
    "lowercase": "electronics", "psyprog": "electronics", "breaks": "electronics",
    "braindance": "electronics", "broken-beat": "electronics", "glitch": "electronics",
    "ghettotech": "electronics", "darkwave": "electronics", "downtempo": "relax",
    "big-beat": "electronics", "power-noise": "electronics",
    "boogie-woogie": "dance",
    "jungle": "electronics", "illbient": "electronics", "2step": "electronics",
    "mallsoft": "electronics", "moombahton": "electronics", "neurofunk": "electronics",
    "psybient": "electronics", "new-beat": "electronics", "new-rave": "electronics",
    "speedcore": "electronics", "footwork": "electronics", "high-energy": "dance",
    "hardstyle": "electronics", "gabber": "electronics", "happy-hardcore": "electronics",
    "soundscape": "relax", "chillout": "relax", "chillwave": "relax",
    "vaporwave": "electronics", "ethereal-wave": "electronics", "cold-wave": "electronics",
    "crunk": "rap", "boom-bap": "rap", "turntablism": "rap", "nerdcore": "rap",
    "horrorcore": "rap", "ragtime": "jazz", "dixieland": "jazz", "jive": "jazz",
    "doo-wop": "rnb", "djent": "metal", "blackgaze": "metal",
    "powerviolence": "punk", "screamo": "alternative", "rapcore": "alternative",
    "chamber": "classicalmusic", "renaissance": "classicalmusic", "choral": "classicalmusic",
    "string-quartet": "classicalmusic", "musique-concrète": "electronics",
}


def genre_path(slug: str, title: str = "", parent: str = "") -> tuple[str, str]:
    """Return a base genre and a meaningful micro-genre family, never page numbers."""
    value = str(slug or "").lower().replace("_", "-")
    if value in _ETHNIC_STYLES or _REGIONAL.search(value + " " + title):
        return "ethnic", ""
    root = _ROOTS.get(parent, parent) if parent else _ROOTS.get(value, "")
    if not root:
        root = _EXACT.get(value, "")
    if not root:
        rules = (
            ("classicalmusic", ("classical", "baroque", "opera", "symphony", "symphonic-music", "piano", "ancient-music")),
            ("metal", ("metal", "black", "death", "doom", "thrash", "trash", "grind")),
            ("electronics", ("house", "techno", "trance", "dubstep", "dnb", "drum", "bass", "break", "electro", "ambient", "synth", "garage", "phonk")),
            ("punk", ("punk", "hardcore", "noisecore")),
            ("allrock", ("rock", "rnr", "new-wave", "stoner", "grunge", "shoegaze")),
            ("rap", ("rap", "hip-hop", "hiphop", "trap", "grime")),
            ("jazz", ("jazz", "bebop", "bop", "swing")),
            ("blues", ("blues", "boogie")),
            ("pop", ("pop",)),
            ("rnb", ("rnb", "soul", "funk")),
            ("folk", ("folk", "bluegrass", "acoustic", "jig")),
            ("country", ("country",)),
            ("reggae", ("reggae", "dancehall", "ska", "dub", "ragga")),
            ("dance", ("dance", "disco", "edm")),
            ("indie", ("indie",)), ("alternative", ("alternative", "core")),
            ("estrada", ("estrada", "chanson", "romances")),
            ("soundtrack", ("soundtrack", "film", "movie")),
            ("children", ("children", "lullaby", "fairytale")),
            ("bard", ("bard", "singer-songwriter")), ("relax", ("relax", "lounge", "meditation")),
        )
        root = next((name for name, markers in rules if any(m in value for m in markers)), "other")
    # The API's parent is authoritative for regular genres; micro-genres have no
    # parent and use these semantic families only to keep long branches browsable.
    families = {
        "metal": (("Блэк-метал", ("black",)), ("Дэт-метал", ("death",)),
                  ("Дум и сладж", ("doom", "sludge", "drone")),
                  ("Трэш и грайнд", ("thrash", "trash", "grind")),
                  ("Металкор", ("core",)), ("Пауэр и хэви", ("power", "heavy", "classic", "epic", "speed")),
                  ("Прогрессивный и симфонический", ("prog", "symphonic", "neoclassical"))),
        "electronics": (("Хаус", ("house",)), ("Техно", ("techno",)), ("Транс", ("trance", "psyprog")),
                        ("Бейс, брейкбит и драм-н-бейс", ("bass", "drum", "dnb", "break", "jungle", "neurofunk", "garage", "2step")),
                        ("Эмбиент и даунтемпо", ("ambient", "bient", "downtempo", "lowercase")),
                        ("Электро и синтезаторная музыка", ("electro", "synth", "ebm", "wave", "chiptune", "bit-8"))),
        "allrock": (("Психоделический и прогрессивный", ("psych", "prog", "space", "stoner", "desert", "art-", "symphonic")),
                    ("Альтернативный и экспериментальный", ("alternative", "indie", "experimental", "noise", "post", "grunge", "shoegaze", "math"))),
    }
    family = next((name for name, markers in families.get(root, ()) if any(m in value for m in markers)), "Другие направления")
    return root, family
