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
    primary="#37FF14DC",
    secondary="#0F7B0F",
    accent="#ABFCAB",
    foreground="#B6FFB6",
    background="#000B00",
    success="#00FF66",
    warning="#FFB000",
    error="#FF3B30",
    surface="#000B00",
    panel="#000B00",
    dark=True,
    variables={
        "footer-key-foreground": "#39ff14",
        "input-selection-background": "#39ff14 25%",
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

zapp_brannigan = Theme(
    name="zapp-brannigan",
    primary="#C9A23F",  # Brash command gold (medals, epaulettes)
    secondary="#1F6F78",  # DOOP teal / space-navy interface
    warning="#E5533D",  # Dramatic ego-red warnings
    error="#B11226",  # Militaristic red (court-martial chic)
    success="#4CAF73",  # Overconfident “mission accomplished” green
    accent="#5FD3E6",  # Loud, vain highlight gold
    foreground="#ECE8E1",  # Retro-future off-white text
    background="#0E1418",  # Deep space bridge black
    surface="#172026",  # Console surface
    panel="#1E2A32",  # Panels, dialogs, sidebars
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#C9A23F",
    },
)


black_and_white = Theme(
    name="black-and-white",
    primary="#FFFFFF",
    secondary="#C7C5C5",
    warning="#E5533D",
    error="#B11226",
    success="#4CAF73",
    accent="#AAAAAA",
    foreground="#ECE8E1",
    background="#000000",
    surface="#000000",
    panel="#000000",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#FFFFFF",
    },
)


ALL_THEMES: list[Theme] = [
    industrial_amber,
    blueprint,
    paper_ledger,
    neo_matrix,
    slate_copper,
    burgundy,
    black_and_white,
    zapp_brannigan,
]
