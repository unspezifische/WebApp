"""Deterministic, campaign-friendly random NPC generation.

The generator deliberately produces lightweight NPC library cards rather than
full player characters.  Ability scores influence the selected occupation so
the resulting resident is mechanically plausible without requiring an agent
simulation run.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


ANCESTRY_NAMES = {
    "human": {
        "first": ("Aldren", "Brynn", "Carla", "Dain", "Elira", "Gareth", "Mara", "Niles", "Tessa", "Vond"),
        "last": ("Amberfall", "Blackwood", "Caskbow", "Duskryn", "Hawkwinter", "Morn", "Rill", "Tarm", "Vale", "Wands"),
    },
    "elf": {
        "first": ("Aelar", "Caelynn", "Erevan", "Ilyana", "Laucian", "Naivara", "Quarion", "Silaqui"),
        "last": ("Amastacia", "Galanodel", "Holimion", "Liadon", "Meliamne", "Siannodel"),
    },
    "dwarf": {
        "first": ("Adrik", "Baern", "Dagna", "Eberk", "Helja", "Morgran", "Rangrim", "Vistra"),
        "last": ("Battlehammer", "Dankil", "Fireforge", "Horn", "Ironfist", "Torunn"),
    },
    "halfling": {
        "first": ("Alton", "Bree", "Cora", "Eldon", "Lidda", "Milo", "Portia", "Roscoe"),
        "last": ("Brushgather", "Goodbarrel", "Greenbottle", "Highhill", "Tealeaf", "Underbough"),
    },
    "gnome": {
        "first": ("Bimpnottin", "Caramip", "Duvamil", "Fonkin", "Nissa", "Roondar", "Smeemo", "Zanna"),
        "last": ("Beren", "Daergel", "Folkor", "Murnig", "Nackle", "Timbers"),
    },
    "half-orc": {
        "first": ("Dench", "Feng", "Gell", "Henk", "Keth", "Myev", "Shump", "Vola"),
        "last": ("Ashscar", "Dawnrunner", "Ironhand", "Stoneward", "Thriceborn"),
    },
    "dragonborn": {
        "first": ("Arjhan", "Balasar", "Biri", "Daar", "Farideh", "Kriv", "Mehen", "Surina"),
        "last": ("Clethtinthiallor", "Daardendrian", "Kimbatuul", "Myastan", "Turnuroth"),
    },
    "tiefling": {
        "first": ("Akta", "Bryseis", "Damaia", "Kallista", "Leucis", "Mordai", "Orianna", "Therai"),
        "last": ("Art", "Carrion", "Hope", "Music", "Quest", "Sorrow"),
    },
    "half-elf": {
        "first": ("Aramil", "Jelenneth", "Lucan", "Mialee", "Sariel", "Shava", "Theren", "Valanthe"),
        "last": ("Evenwood", "Greycastle", "Moonbrook", "Starling", "Talandro"),
    },
}


@dataclass(frozen=True)
class Occupation:
    label: str
    abilities: tuple[str, ...]
    skills: str
    ac_base: int = 10
    hp_base: int = 4
    challenge: str = "0 (10 XP)"


OCCUPATIONS = {
    "laborer": Occupation("Laborer", ("strength", "constitution"), "Athletics +2", hp_base=7),
    "porter": Occupation("Porter", ("strength", "constitution"), "Athletics +3", hp_base=8),
    "guard": Occupation("Guard", ("strength", "constitution", "wisdom"), "Athletics +3, Perception +2", 14, 11, "1/8 (25 XP)"),
    "craftsperson": Occupation("Craftsperson", ("dexterity", "intelligence"), "Investigation +2, one artisan's tool", 11, 6),
    "artisan": Occupation("Artisan", ("dexterity", "intelligence", "wisdom"), "Insight +2, one artisan's tool", 11, 6),
    "scholar": Occupation("Scholar", ("intelligence", "wisdom"), "Arcana +3, History +3", hp_base=4),
    "healer": Occupation("Healer", ("wisdom", "intelligence"), "Insight +3, Medicine +4", hp_base=5),
    "merchant": Occupation("Merchant", ("charisma", "intelligence", "wisdom"), "Insight +3, Persuasion +3", 11, 5),
    "performer": Occupation("Performer", ("charisma", "dexterity"), "Acrobatics +3, Performance +4", 11, 5),
    "innkeeper": Occupation("Innkeeper", ("charisma", "wisdom", "constitution"), "Insight +3, Persuasion +3", 11, 7),
    "sailor": Occupation("Sailor", ("strength", "dexterity", "wisdom"), "Athletics +3, Perception +2", 11, 8),
    "guide": Occupation("Guide", ("wisdom", "constitution", "dexterity"), "Perception +3, Survival +4", 12, 8),
}

ALIGNMENTS = (
    "lawful good", "neutral good", "chaotic good", "lawful neutral",
    "neutral", "chaotic neutral",
)
GENDERS = ("woman", "man", "nonbinary person")


def _roll_score(rng: random.Random) -> int:
    rolls = sorted(rng.randint(1, 6) for _ in range(4))
    return sum(rolls[1:])


def roll_ability_scores(rng: random.Random) -> dict[str, int]:
    return {
        ability: _roll_score(rng)
        for ability in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
    }


def choose_occupation(scores: dict[str, int], rng: random.Random, allowed=None) -> str:
    """Choose among feasible jobs, heavily weighting relevant high scores."""
    keys = [key for key in (allowed or OCCUPATIONS) if key in OCCUPATIONS]
    if not keys:
        raise ValueError("No supported occupations were supplied")
    weights = []
    for key in keys:
        occupation = OCCUPATIONS[key]
        aptitude = sum(scores[ability] - 7 for ability in occupation.abilities)
        # Every job remains possible, while a strong aptitude is visibly favored.
        weights.append(max(1, aptitude * aptitude))
    return rng.choices(keys, weights=weights, k=1)[0]


def generated_npc(seed=None, ancestry=None, gender=None, occupation=None, alignment=None) -> dict:
    rng = random.Random(seed)
    ancestry_key = str(ancestry or rng.choice(tuple(ANCESTRY_NAMES))).strip().lower()
    if ancestry_key not in ANCESTRY_NAMES:
        raise ValueError(f"Unsupported ancestry: {ancestry}")
    gender_value = str(gender or rng.choice(GENDERS)).strip().lower()
    scores = roll_ability_scores(rng)
    occupation_key = str(occupation or choose_occupation(scores, rng)).strip().lower()
    if occupation_key not in OCCUPATIONS:
        raise ValueError(f"Unsupported occupation: {occupation}")
    job = OCCUPATIONS[occupation_key]
    names = ANCESTRY_NAMES[ancestry_key]
    name = f"{rng.choice(names['first'])} {rng.choice(names['last'])}"
    dex_mod = (scores["dexterity"] - 10) // 2
    con_mod = (scores["constitution"] - 10) // 2
    hp = max(1, job.hp_base + con_mod)
    return {
        "name": name,
        "size": "Medium" if ancestry_key not in {"halfling", "gnome"} else "Small",
        "creature_type": "humanoid",
        "creature_subtype": ancestry_key,
        "alignment": str(alignment or rng.choice(ALIGNMENTS)).strip().lower(),
        "ac": str(max(job.ac_base, 10 + dex_mod)),
        "hp": str(hp),
        "speed": 25 if ancestry_key in {"dwarf", "halfling", "gnome"} else 30,
        **scores,
        "saving_throws": "",
        "skills": job.skills,
        "immunities": "",
        "resistance": "",
        "senses": "passive Perception 10",
        "languages": "Common" + (f", {ancestry_key.title()}" if ancestry_key != "human" else ""),
        "challenge": job.challenge,
        "traits": f"Occupation: {job.label}",
        "actions": "Improvised weapon or an action appropriate to the NPC's occupation.",
        "description": f"A randomly generated {ancestry_key} {gender_value} working as a {job.label.lower()}.",
        "generation": {
            "ancestry": ancestry_key,
            "gender": gender_value,
            "occupation": occupation_key,
            "seed": seed,
        },
    }


def supported_generation_options() -> dict:
    return {
        "ancestries": sorted(ANCESTRY_NAMES),
        "genders": list(GENDERS),
        "occupations": [{"key": key, "label": value.label} for key, value in OCCUPATIONS.items()],
        "alignments": list(ALIGNMENTS),
    }
