# Module Format Guide

A **module** is a packaged, installable adventure: metadata, an in-world calendar, an
optional pre-built settlement map with media, wiki lore pages, and named NPC presets.
When a DM installs a module (`POST /api/campaigns/<id>/modules` with `{"module_key": ...}`),
the endpoint runs a fixed pipeline that consumes the pieces described below:

```
install_campaign_module(campaign_id)
  ├─ module_definition(module_key)            → 1. Module definition
  ├─ campaign_module_template(key, MEDIA_ROOT)→ 3. Settlement template
  │    └─ import_module_settlement(...)       → WorldAtlasLocation + MapPointOfInterest
  ├─ ensure_module_calendar(...)              → 2. Calendar JSON + Calendar row
  ├─ seed_module_wiki_pages(...)              → 4. Wiki GameElements
  ├─ seed_module_npcs(...)                    → 5. NPC presets
  ├─ record_module_installation(...)          → CampaignModuleInstallation row
  └─ campaign_atlas_config(campaign)          → setting_key drives the campaign atlas
```

Everything is optional except the **module definition** — a module may ship any subset
of the pieces (see `lost_mine_of_phandelver`, which ships definition + calendar only).

## The six module pieces

| # | Piece | Where it lives | How installation finds it |
|---|-------|----------------|---------------------------|
| 1 | Module definition | `Flask/module_templates.py` → `MODULE_DEFINITIONS` | Keyed by `module_key` (or display name) |
| 2 | Calendar format | JSON file in `Flask/` (e.g. `Harptos.json`) | `definition['calendar']['filename']`, read relative to `app.root_path` |
| 3 | Settlement template | `Flask/module_templates.py` (builder function) | `campaign_module_template(key, MEDIA_ROOT)` |
| 4 | Map media | `Flask/media/modules/<module_key>/` | `image_url` paths in the template's `reference_layers` |
| 5 | Wiki pages | `GameElement` rows in the DB | `module = <module name>` AND `element_type = 'wiki'` |
| 6 | NPC presets | `Flask/module_npcs.py` → `MODULE_NPCS` | Keyed by `definition['key']` |

---

## 1. Module definition

A plain dict in `MODULE_DEFINITIONS` (`Flask/module_templates.py`). Keys are the
stable machine key (`snake_case`); the human display name is separate.
`module_definition()` matches either value, case-insensitively.

```python
MODULE_DEFINITIONS = {
    "example_module": {
        "key": "example_module",                # stable ID, used in API calls
        "name": "Example Module",               # display name (also used as GameElement.module)
        "system": "D&D 5e",                     # game system
        "setting_key": "forgotten_realms",      # drives campaign_atlas_config()
        "setting_name": "Forgotten Realms",
        "starting_year": 1492,                  # year the campaign Calendar starts at
        "starting_year_label": "1492 DR",
        "calendar": {
            "slug": "harptos",                  # format slug stored on the Calendar
            "name": "Calendar of Harptos",      # must match a GameElement / JSON file
            "filename": "Harptos.json",         # piece #2, relative to the Flask/ dir
            "starting_month_index": 0,          # 0-based month
            "starting_day": 1,
        },
        "settlements": ["Example City"],        # informational (UI display)
        "atlas_position": {"x": 0.45, "y": 0.26, "coordinate_space_key": "faerun-v1"},
        "description": "Short catalog blurb shown in the module picker.",
    },
}
```

Notes:
- `setting_key` matters: any installed module with `setting_key = 'forgotten_realms'`
  flips the campaign atlas to the shared `faerun` / `faerun-v1` coordinate space
  (`campaign_atlas_config()`). Use the matching setting for your module or a custom key.
- `name` must be the **exact display name** used in `GameElement.module` for wiki pages,
  because `seed_module_wiki_pages()` filters by it.
- The catalog endpoint serializes every definition (minus `calendar.filename`) plus the
  NPC count, so keep all values JSON-serializable and free of server paths.

---

## 2. Calendar format (JSON)

A single JSON file sitting directly in `Flask/` (loaded with `app.root_path /
definition['calendar']['filename']`). It is stored verbatim into a `GameElement`
(`element_type='calendar_format'`) and then drives a per-campaign `Calendar` row
(starting year, month index, and day come from the definition).

Reference implementation: `Flask/Harptos.json`.

```json
{
  "slug": "harptos",
  "calendar_type": "lunar_solar",
  "display_name": "Calendar of Harptos",
  "hours_per_day": 24,
  "minutes_per_hour": 60,
  "weekdays": [
    { "name": "Wynne", "short_name": "Wyn" }
  ],
  "months": [
    { "name": "Hammer", "subtitle": "Hammer", "length": 31 }
  ],
  "leap_rule": "every 4 years",
  "moons": [
    { "name": "Selyune", "cycle_length_days": 30, "phase_offset": 0 }
  ],
  "holidays": [
    { "name": "Midwinter", "month_index": 0, "day": 31, "intercalary": true }
  ],
  "time_periods": [
    { "name": "Morning", "start_hour": 6, "end_hour": 12 }
  ]
}
```

Required keys: `slug`, `display_name`, `months` (each with `name`, `length`).
Everything else is optional and rendered by the calendar tools as available.
`month_index` values in `holidays` are 0-based into `months`.

---

## 3. Settlement template

A JSON-serializable dict returned by `campaign_module_template(module_key, MEDIA_ROOT)`
(`Flask/module_templates.py`). It describes one settlement — the equivalent of a
`WorldAtlasLocation` plus named `MapPointOfInterest` rows. On install it is persisted
by `import_module_settlement(campaign, template, strategy)`:

- **merge** (default) — records in `terrain_strokes`, `roads`, `water_bodies`,
  `buildings`, `reference_layers`, and `environment.regions` / `environment.fortifications`
  are merged by their `id`; scalar fields (`settlement_type`, `notes`, `atlas_x/y`) are
  updated; `points_of_interest` are added by name (case-insensitive).
- **keep** — if the settlement already exists (matched by `map_key` or `name`,
  case-insensitive) it is left untouched.
- **override** — the settlement is replaced wholesale; the old map's POIs are deleted
  and the party position re-pointed at the new `map_key`.

If no settlement exists yet, it is always **created**.

### Shape (annotated, condensed from `waterdeep_dragon_heist_template`)

```python
{
    "map_key": "waterdeep_v1",            # stable map id; used to match POIs/party
    "name": "Waterdeep",                  # settlement display name
    "settlement_type": "city",
    "atlas_x": 0.45, "atlas_y": 0.26,     # position on the campaign world atlas
    "coordinate_space_key": "faerun-v1",
    "notes": "Optional DM-facing note.",
    "terrain_strokes": [],
    "roads": [
        { "id": "high-road", "name": "The High Road", "road_class": "avenue",
          "width_feet": 48,
          "points": [{"x": -1800, "y": 4530}, ...] }   # centered world feet
    ],
    "water_bodies": [],
    "buildings": [
        { "id": "trollskull", "name": "Trollskull Manor", "asset_key": "coaching_inn",
          "x": 220, "y": 1130, "width_feet": 78, "depth_feet": 62,
          "rooms": ["Taproom", "Kitchen", "Guest rooms"] }
    ],
    "environment": {
        "biome": "coastal grassland", "coastal": True,
        "regions": [ { "id": "downtown", "name": "Downtown", "region_type": "ward", "points": [...] } ],
        "fortifications": [ { "id": "mount", "name": "Mount Waterdeep Wall", "points": [...], "height_feet": 35, "width_feet": 24 } ],
        "boundary_notes": "Optional."
    },
    "reference_layers": [ ... ],           # see Media section below
    "points_of_interest": [
        { "name": "Troll Gate", "point_type": "gate", "x": -2520, "y": 2610,
          "elevation": 0, "water_access": False, "road_access": True,
          "template_status": "approximate" }
    ],
    "party_position": { "x": 570, "y": 3240, "elevation": 0,
                        "road_access": True, "water_access": False },
    "calibration": { "core_width_feet": 12600, "height_feet": 18000,
                     "external_reference_url": "https://..." }
}
```

Rules of thumb:
- Every list record should carry a stable `id` (merge de-dupes on it).
- POI coordinates are **centered world feet**: `(u - 0.5) * width_feet`,
  `(0.5 - v) * height_feet` (see `_world_point()` in `module_templates.py`).
- `party_position` seeds the party's starting spot; keep it on the map.
- Register the template in the `campaign_module_template()` dispatcher, keyed by
  `definition["key"]` (unregistered modules simply install without a settlement).

### 4. Map media

Rasters (PNG/JPEG/WebP) live in `Flask/media/modules/<module_key>/` and are referenced
from `reference_layers` with URLs of the form `/media/modules/<module_key>/<file>`:

```python
{
    "id": "city-terrain-texture", "layer_type": "terrain_texture",   # or "reference"
    "name": "City terrain texture",
    "image_url": "/media/modules/my_module/city_texture.jpg",
    "visible": True, "opacity": 1,
    "origin_x": 0, "origin_y": 0,
    "width_feet": 12600, "height_feet": 18000, "rotation_degrees": 0,
    "pixel_width": 2926, "pixel_height": 4096,
    "feet_per_pixel_x": 12600 / 2926, "feet_per_pixel_y": 18000 / 4096,
    "layer_order": -10, "scope": "city",
    "attribution": "Campaign map asset supplied by the DM"
}
```

On install, `persist_reference_layer_media()` copies every referenced file into Postgres
(`MapMediaAsset`) and rewrites `image_url` to an opaque `/api/map-media/<public_id>` URL,
so the local file is only needed once — the campaign is self-contained afterwards.

---

## 5. Wiki pages

Wiki pages are **database rows**, not files. Each page is a `GameElement` with:

| Column | Value |
|--------|-------|
| `system` | e.g. `"D&D 5e"` |
| `element_type` | `'wiki'` |
| `module` | **exact module display name** (must equal `definition['name']`) |
| `name` | stable unique page name |
| `data` | `{"title": "Page Title", "content": "Markdown body"}` |

`seed_module_wiki_pages(campaign, module_name)` queries
`GameElement.query.filter_by(module=module_name, element_type='wiki')` and inserts a
campaign `Page` for every page whose title is not already present (existing campaign
pages are never overwritten; a page titled `"Main Page"` is skipped).

Seed them with a small script following the pattern of `Flask/seedCalendars.py`:
create the `GameElement` rows inside `app.app_context()` and commit. `GameElement.name`
is `unique=True`, so names must be globally unique across all modules (e.g.
`waterdeep_trollskull_manor`).

## 6. NPC presets

Named NPCs live in `Flask/module_npcs.py` under `MODULE_NPCS`, keyed by
`definition['key']` → list of dicts. `seed_module_npcs()` merges them by name
(case-insensitive): existing campaign NPCs are skipped, new ones get `source='Module'`.

Each record uses the `NPC_RECORD_FIELDS` whitelist — unknown keys are ignored:

```python
{
    "name": "Ahmaergo",                 # required; dedup key
    "size": "Medium", "creature_type": "humanoid", "creature_subtype": "dwarf",
    "alignment": "lawful evil",
    "ac": 16, "hp": 67, "speed": 30,
    "strength": 14, "dexterity": 12, "constitution": 13,
    "intelligence": 10, "wisdom": 11, "charisma": 16,
    "saving_throws": ["Constitution +4", "Charisma +5"],
    "skills": ["Perception +3", "Deception +4"],
    "immunities": [], "resistance": [],
    "senses": "darkvision 60 ft", "languages": "Common, Dwarvish",
    "challenge": 2,
    "traits": ["...", "..."], "actions": ["...", "..."],
    "description": "Flavor text shown in the NPC roster."
}
```

Helper `_npc()` in `module_npcs.py` fills sensible defaults; `module_npc_presets(key)`
returns the list (or `[]` if the module ships none). The count appears in the module
catalog, so NPCs are announced in the UI before install.

---

## Integration checklist (new module)

1. **Definition** — add an entry to `MODULE_DEFINITIONS` in `Flask/module_templates.py`.
2. **Calendar** (optional) — add `<Name>.json` next to `Flask/app.py`, point
   `definition['calendar']['filename']` at it; verify `starting_month_index`/`day`.
3. **Settlement** (optional) — write `<key>_template(media_root)`, return the dict in
   the Section 3 shape, and dispatch it from `campaign_module_template()` on the key.
4. **Media** (optional) — drop rasters into `Flask/media/modules/<key>/`; reference them
   as `/media/modules/<key>/<file>`; keep pixel dimensions accurate for calibration.
5. **Wiki pages** (optional) — insert `GameElement` rows (`element_type='wiki'`,
   `module=<display name>`, `data={'title', 'content'}`); unique `name` ≤ 50 chars.
6. **NPCs** (optional) — add a tuple/list under `MODULE_NPCS[key]` in `Flask/module_npcs.py`.
7. **Test** — `GET /api/campaigns/<id>/modules` should list it under `available_modules`
   with the right NPC count, then
   `POST /api/campaigns/<id>/modules` with `{"module_key": ..., "settlement_strategy": "merge"|"keep"|"override", "calendar_strategy": "keep_current"|"use_module"}`
   against a scratch campaign and confirm the atlas, calendar, wiki, and NPC endpoints.

Reference modules: `waterdeep_dragon_heist` (full: definition + calendar + settlement +
media + wiki + NPCs) and `lost_mine_of_phandelver` (minimal: definition + calendar).

---

## Campaign bundles (`bundle.sh` / `flask import-module`)

Separate from the code-defined modules above, `<repo root>/bundle.sh` packages a
campaign's *data* (rows tagged with a given `source`) into a redistributable folder here:

```
Flask/modules/<module_name>/
  ├─ manifest.json      # module_name, source_campaign, exported_from_host, exported_at
  ├─ npcs.json          # NPC rows (source == module_name, scoped to the source campaign)
  ├─ settlements.json   # WorldAtlasLocation rows (same scoping)
  ├─ items.json         # Item rows (source == module_name; items aren't campaign-scoped)
  ├─ loot_boxes.json
  ├─ calendar_events.json
  └─ wiki_pages/*.md
```

Build one with:

```
./bundle.sh --campaignName "<campaign>" --moduleName "<module_name>" --hostname <host>
```

`publish.sh --modules` (or `--all`) rsyncs everything under `Flask/modules/` to the
target server and confirms the `flask import-module` command is available there.
Publishing never installs a bundle into a campaign automatically — installation is
per-campaign and idempotent, run on the target server:

```
flask import-module --module-name "<module_name>" --campaign-name "<target campaign>"
```

`publish.sh --docker` targets the local docker-compose stack instead of the
bare-metal Pi (that stack only runs locally; the Pi is bare-metal, so `--nginx`
and `--mtg` can't be combined with `--docker`). Since `docker-compose.yaml` bind-mounts
`./Flask` into the `flask` container, bundles are already visible inside it — `--docker
--modules` just verifies `flask import-module` works there. Install a bundle locally with:

```
docker compose exec flask flask import-module --module-name "<module_name>" --campaign-name "<target campaign>"
```

Rows are matched by `(campaign_id, source, name)` for NPCs/settlements and
`(source, name)` for items, so re-running the command against the same campaign
updates existing rows instead of duplicating them.

