"""Named NPC library presets supplied by installable campaign modules.

These are intentionally concise reference cards.  They identify the named
characters and their broad roles without reproducing adventure-book prose or
complete encounter stat blocks.
"""

from __future__ import annotations

from copy import deepcopy


PROFILES = {
    "commoner": dict(ac="10", hp="4", speed=30, scores=(10, 10, 10, 10, 10, 10), challenge="0 (10 XP)"),
    "noble": dict(ac="15", hp="9", speed=30, scores=(11, 12, 11, 12, 14, 16), challenge="1/8 (25 XP)"),
    "agent": dict(ac="14", hp="27", speed=30, scores=(11, 15, 12, 13, 14, 15), challenge="1 (200 XP)"),
    "veteran": dict(ac="17", hp="58", speed=30, scores=(16, 13, 14, 10, 11, 10), challenge="3 (700 XP)"),
    "mage": dict(ac="12", hp="45", speed=30, scores=(9, 14, 11, 17, 12, 15), challenge="5 (1,800 XP)"),
    "priest": dict(ac="13", hp="27", speed=30, scores=(10, 10, 12, 13, 16, 13), challenge="2 (450 XP)"),
    "champion": dict(ac="18", hp="143", speed=30, scores=(20, 15, 14, 12, 14, 12), challenge="9 (5,000 XP)"),
    "archmage": dict(ac="17", hp="126", speed=30, scores=(10, 16, 14, 20, 16, 18), challenge="13 (10,000 XP)"),
    "monk": dict(ac="20", hp="136", speed=40, scores=(18, 22, 14, 12, 20, 14), challenge="16 (15,000 XP)"),
    "dragon": dict(ac="19", hp="256", speed=40, scores=(27, 10, 25, 16, 15, 19), challenge="17 (18,000 XP)"),
    "aberration": dict(ac="16", hp="120", speed=0, scores=(10, 14, 18, 17, 15, 17), challenge="13 (10,000 XP)"),
    "devil": dict(ac="16", hp="85", speed=30, scores=(18, 15, 16, 11, 12, 14), challenge="8 (3,900 XP)"),
}


def _npc(key, name, role, ancestry="human", alignment="neutral", profile="commoner", description=None):
    data = PROFILES[profile]
    strength, dexterity, constitution, intelligence, wisdom, charisma = data["scores"]
    return {
        "source_key": key,
        "name": name,
        "size": "Large" if profile == "dragon" else "Medium",
        "creature_type": "aberration" if profile == "aberration" else ("dragon" if profile == "dragon" else ("fiend" if profile == "devil" else "humanoid")),
        "creature_subtype": ancestry,
        "alignment": alignment,
        "ac": data["ac"],
        "hp": data["hp"],
        "speed": data["speed"],
        "strength": strength,
        "dexterity": dexterity,
        "constitution": constitution,
        "intelligence": intelligence,
        "wisdom": wisdom,
        "charisma": charisma,
        "saving_throws": "",
        "skills": "",
        "immunities": "",
        "resistance": "",
        "senses": "passive Perception 10",
        "languages": "Common",
        "challenge": data["challenge"],
        "traits": f"Module role: {role}",
        "actions": "See the installed adventure module when encounter-level actions are required.",
        "description": description or f"A Waterdeep: Dragon Heist NPC associated with the role of {role.lower()}.",
    }


# Named creatures and people presented in Appendix B. Generic entries such as
# city guards, gazers, and swashbucklers are intentionally left to the random
# generator because they are reusable creature types rather than named NPCs.
WATERDEEP_DRAGON_HEIST_NPCS = (
    _npc("ahmaergo", "Ahmaergo", "Xanathar Guild majordomo", "dwarf", "lawful evil", "champion"),
    _npc("ammalia-cassalanter", "Ammalia Cassalanter", "Cassalanter noble and arcane practitioner", alignment="lawful evil", profile="mage"),
    _npc("aurinax", "Aurinax", "guardian of the Dragonstaff", "gold dragon", "lawful good", "dragon"),
    _npc("barnibus-blastwind", "Barnibus Blastwind", "City Watch investigator and mage", profile="mage"),
    _npc("black-viper", "Esvele Rosznar (The Black Viper)", "noble and masked burglar", alignment="chaotic neutral", profile="agent"),
    _npc("davil-starsong", "Davil Starsong", "Doom Raider negotiator", "sun elf", profile="mage"),
    _npc("istrid-horn", "Istrid Horn", "Doom Raider financier", "dwarf", "neutral evil", "priest"),
    _npc("skeemo-weirdbottle", "Skeemo Weirdbottle", "Doom Raider alchemist", "gnome", "neutral evil", "mage"),
    _npc("tashlyn-yafeera", "Tashlyn Yafeera", "Doom Raider arms master", alignment="neutral", profile="champion"),
    _npc("ziraj-the-hunter", "Ziraj the Hunter", "Doom Raider assassin", "half-orc", "neutral evil", "champion"),
    _npc("felrekt-lafeen", "Fel'rekt Lafeen", "Bregan D'aerthe lieutenant", "drow", "neutral good", "agent"),
    _npc("krebbyg-masqilyr", "Krebbyg Masq'il'yr", "Bregan D'aerthe gunslinger", "drow", "chaotic neutral", "agent"),
    _npc("soluun-xibrindas", "Soluun Xibrindas", "Bregan D'aerthe gunslinger", "drow", "neutral evil", "agent"),
    _npc("durnan", "Durnan", "proprietor of the Yawning Portal", profile="champion"),
    _npc("floon-blagmaar", "Floon Blagmaar", "Waterdavian socialite", profile="commoner"),
    _npc("hlam", "Hlam", "monk of Mount Waterdeep", profile="monk"),
    _npc("hrabbaz", "Hrabbaz", "House Gralhund bodyguard", "half-orc", "neutral evil", "champion"),
    _npc("jarlaxle-baenre", "Jarlaxle Baenre", "Bregan D'aerthe leader", "drow", "chaotic neutral", "archmage"),
    _npc("laeral-silverhand", "Laeral Silverhand", "Open Lord of Waterdeep", "human", "chaotic good", "archmage"),
    _npc("manshoon", "Manshoon", "Zhentarim archmage", alignment="lawful evil", profile="archmage"),
    _npc("meloon-wardragon", "Meloon Wardragon", "adventurer and Force Grey operative", profile="champion"),
    _npc("mirt", "Mirt", "Masked Lord and Harper", alignment="chaotic good", profile="champion"),
    _npc("narl-xibrindas", "Nar'l Xibrindas", "Bregan D'aerthe spy", "drow", "neutral evil", "mage"),
    _npc("nihiloor", "Nihiloor", "Xanathar Guild mind flayer", "mind flayer", "lawful evil", "aberration"),
    _npc("noska-urgray", "Noska Ur'gray", "Xanathar Guild enforcer", "dwarf", "neutral evil", "veteran"),
    _npc("osvaldo-cassalanter", "Osvaldo Cassalanter", "heir transformed by an infernal bargain", "chain devil", "lawful evil", "devil"),
    _npc("ott-steeltoes", "Ott Steeltoes", "Xanathar Guild fish keeper", "dwarf", "chaotic evil", "commoner"),
    _npc("remallia-haventree", "Remallia Haventree", "Harper leader", "half-elf", "chaotic good", "mage"),
    _npc("renaer-neverember", "Renaer Neverember", "Waterdavian noble and Harper ally", alignment="neutral good", profile="agent"),
    _npc("saeth-cromley", "Saeth Cromley", "retired City Watch investigator", profile="veteran"),
    _npc("thorvin-twinbeard", "Thorvin Twinbeard", "Xanathar Guild engineer and Harper informant", "dwarf", "lawful neutral", "commoner"),
    _npc("urstul-floxin", "Urstul Floxin", "Zhentarim assassin", alignment="lawful evil", profile="champion"),
    _npc("vajra-safahr", "Vajra Safahr", "Blackstaff of Waterdeep", alignment="lawful neutral", profile="archmage"),
    _npc("victoro-cassalanter", "Victoro Cassalanter", "Cassalanter noble and priest", "half-elf", "lawful evil", "archmage"),
    _npc("volothamp-geddarm", "Volothamp Geddarm", "author and traveler", profile="mage"),
    _npc("xanathar", "Xanathar", "beholder crime lord", "beholder", "lawful evil", "aberration"),
    _npc("yalah-gralhund", "Yalah Gralhund", "House Gralhund noble", alignment="lawful evil", profile="noble"),
)


MODULE_NPCS = {"waterdeep_dragon_heist": WATERDEEP_DRAGON_HEIST_NPCS}


def module_npc_presets(identifier) -> list[dict]:
    return deepcopy(list(MODULE_NPCS.get(str(identifier or "").strip().casefold(), ())))
