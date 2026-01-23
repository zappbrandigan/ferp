from textual.theme import Theme

industrial_amber = Theme(
    name="industrial-amber",
    primary="#FFB000",
    secondary="#E09F00",
    accent="#FF6A00",
    foreground="#FFE8B3",
    background="#0E0E0E",
    success="#9FD356",
    warning="#FFB000",
    error="#FF3B30",
    surface="#161616",
    panel="#1F1F1F",
    dark=True,
    variables={
        "footer-key-foreground": "#ffb000",
        "input-selection-background": "#ffb000 25%",
        "block-cursor-text-style": "none",
    },
)

blueprint = Theme(
    name="blueprint",
    primary="#4FC3F7",
    secondary="#0288D1",
    accent="#81D4FA",
    foreground="#E1F5FE",
    background="#0A192F",
    success="#4CAF50",
    warning="#FFC107",
    error="#F44336",
    surface="#102A43",
    panel="#163A5F",
    dark=True,
    variables={
        "footer-key-foreground": "#4fc3f7",
        "input-selection-background": "#0288d1 35%",
        "block-cursor-text-style": "none",
    },
)

paper_ledger = Theme(
    name="paper-ledger",
    primary="#2C3E50",
    secondary="#5D6D7E",
    accent="#1F618D",
    foreground="#1C1C1C",
    background="#FAFAF7",
    success="#2E7D32",
    warning="#F9A825",
    error="#C62828",
    surface="#F0F0EB",
    panel="#E6E6E0",
    dark=False,
    variables={
        "footer-key-foreground": "#2c3e50",
        "input-selection-background": "#1f618d 25%",
        "block-cursor-text-style": "none",
    },
)

neo_matrix = Theme(
    name="neo-matrix",
    primary="#00FF9C",
    secondary="#00C97A",
    accent="#00FFCC",
    foreground="#B6FFE3",
    background="#020D08",
    success="#00FF9C",
    warning="#FFD166",
    error="#FF4D6D",
    surface="#041A12",
    panel="#06261B",
    dark=True,
    variables={
        "footer-key-foreground": "#00ff9c",
        "input-selection-background": "#00ff9c 30%",
        "block-cursor-text-style": "none",
    },
)

slate_copper = Theme(
    name="slate-copper",
    primary="#C97C5D",
    secondary="#8C5A3C",
    # accent="#E3A587",
    accent="#DFB6A2",
    foreground="#EDE7E3",
    background="#2B2B2B",
    success="#8BC34A",
    warning="#FFB74D",
    error="#E57373",
    surface="#353535",
    panel="#404040",
    dark=True,
    variables={
        "footer-key-foreground": "#c97c5d",
        "input-selection-background": "#c97c5d 30%",
        "block-cursor-text-style": "none",
    },
)

petal_sky = Theme(
    name="petal-sky",
    primary="#CDB4DB",  # thistle
    secondary="#a2d2ff",  # sky-blue
    accent="#ffafcc",  # baby-pink
    foreground="#3A2F3F",  # derived: muted plum for legibility
    background="#F7F3FA",  # derived: off-white lavender
    surface="#EFE7F3",  # derived pastel surface
    panel="#E6DCEF",  # derived panel tone
    success="#7FB8A8",  # derived soft teal
    warning="#FFC8DD",  # pastel-petal
    error="#E89BB3",  # derived muted rose
    dark=False,
    variables={
        # Text hierarchy
        "text-muted": "#7A6F85",
        "text-subtle": "#9A90A5",
        "footer-key-foreground": "#3A2F3F",
    },
)


tokyo_night = Theme(
    name="tokyo-night",
    primary="#7AA2F7",
    secondary="#9ECE6A",
    accent="#BB9AF7",
    foreground="#C0CAF5",
    background="#1A1B26",
    success="#9ECE6A",
    warning="#E0AF68",
    error="#F7768E",
    surface="#24283B",
    panel="#2F3549",
    dark=True,
    variables={
        "footer-key-foreground": "#7aa2f7",
        "input-selection-background": "#bb9af7 30%",
        "block-cursor-text-style": "none",
    },
)

burgundy = Theme(
    name="ron-burgundy",
    primary="#7A1E2B",  # deep burgundy
    secondary="#A63A4A",  # lighter wine
    accent="#C94C5C",  # rose accent
    foreground="#E6DCDC",  # warm off-white
    background="#121012",  # near-black, warm
    success="#4FAF8F",  # muted teal-green (contrasts burgundy well)
    warning="#D4A017",  # antique gold
    error="#C83A3A",  # restrained red
    surface="#1C171A",  # panels / cards
    panel="#241C20",  # raised panels
    dark=True,
    variables={
        "footer-key-foreground": "#C94C5C",
        "input-selection-background": "#7A1E2B 40%",
        "block-cursor-text-style": "none",
    },
)

ALL_THEMES: list[Theme] = [
    industrial_amber,
    blueprint,
    paper_ledger,
    neo_matrix,
    slate_copper,
    tokyo_night,
    burgundy,
    petal_sky,
]
