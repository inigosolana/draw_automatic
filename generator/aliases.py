ALIASES = {
    "mikrotik hap ac2": "Microtik_hAPc",
    "microtik hap ac2": "Microtik_hAPc",
    "microtik_hapc": "Microtik_hAPc",
    "ont zte": "ONT ZTE",
    "ont": "ONT",
    "fanvil v62": "FANVIL_V62",
    "yealink t31p": "T-31",
    "yealink t31": "T-31",
    "ata grandstream": "ATA",
    "ata": "ATA",
    "pc": "PC",
    "switch tp-link 16p": "TP-Link 16P",
    "tp-link 16p": "TP-Link 16P",
    "w60b": "W60B",
    "w70b": "W70B",
    "router zte": "Router ZTE",
}


def normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


def resolve_alias(value: str) -> str:
    normalized = normalize_name(value)
    return ALIASES.get(normalized, value)
