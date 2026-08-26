"""Reusable, campaign-scoped world templates for published adventure modules."""

from pathlib import Path

from PIL import Image

from module_npcs import module_npc_presets


WATERDEEP_MODULE = "Waterdeep Dragon Heist"
WATERDEEP_MAP_KEY = "waterdeep"

# The keyed map's scale bars put the core portrait map at roughly 11,500 by
# 23,400 feet. The supplied texture includes more scenery east and west, so its
# width is derived from the raster aspect ratio to keep map pixels square.
WATERDEEP_HEIGHT_FEET = 23_403
WATERDEEP_TEXTURE_WIDTH_FEET = 16_718
WATERDEEP_CORE_WIDTH_FEET = 11_484

MODULE_DEFINITIONS = {
    "waterdeep_dragon_heist": {
        "key": "waterdeep_dragon_heist",
        "name": WATERDEEP_MODULE,
        "system": "D&D 5e",
        "setting_key": "forgotten_realms",
        "setting_name": "Forgotten Realms",
        "starting_year": 1492,
        "starting_year_label": "1492 DR",
        "calendar": {
            "slug": "harptos",
            "name": "Calendar of Harptos",
            "filename": "Harptos.json",
            "starting_month_index": 0,
            "starting_day": 1,
        },
        "settlements": ["Waterdeep"],
        "atlas_position": {"x": 0.455, "y": 0.265, "coordinate_space_key": "faerun-v1"},
        "description": "Urban intrigue in Waterdeep with a pre-built city simulation map.",
    },
    "lost_mine_of_phandelver": {
        "key": "lost_mine_of_phandelver",
        "name": "Lost Mine of Phandelver",
        "system": "D&D 5e",
        "setting_key": "forgotten_realms",
        "setting_name": "Forgotten Realms",
        "starting_year": 1491,
        "starting_year_label": "1491 DR (suggested)",
        "calendar": {
            "slug": "harptos",
            "name": "Calendar of Harptos",
            "filename": "Harptos.json",
            "starting_month_index": 0,
            "starting_day": 1,
        },
        "settlements": ["Phandalin"],
        "atlas_position": {"x": 0.431, "y": 0.282, "coordinate_space_key": "faerun-v1"},
        "description": "Starter adventure metadata and Forgotten Realms calendar; its settlement template is not yet packaged.",
    },
}


def _world_point(u, v):
    """Convert normalized texture coordinates into centered world feet."""
    return {
        "x": round((u - 0.5) * WATERDEEP_TEXTURE_WIDTH_FEET),
        "y": round((0.5 - v) * WATERDEEP_HEIGHT_FEET),
    }


def _road(key, name, width, points, road_class="avenue"):
    return {
        "id": f"waterdeep-road-{key}",
        "name": name,
        "road_class": road_class,
        "surface_type": "cobblestone",
        "width_feet": width,
        "pedestrian_speed_modifier": 1,
        "public_access": True,
        "closed": False,
        "points": [_world_point(u, v) for u, v in points],
        "template_status": "draft",
    }


def _ward(key, name, points, notes=""):
    return {
        "id": f"waterdeep-ward-{key}", "name": name, "region_type": "city",
        "district_type": "ward", "visible": True,
        "points": [_world_point(u, v) for u, v in points],
        "template_status": "inferred", "notes": notes or "Approximate ward boundary inferred from the DM map.",
    }


def _wall(key, name, points, height=35, width=24, closed=False):
    return {
        "id": f"waterdeep-wall-{key}", "name": name, "feature_type": "city_wall",
        "height_feet": height, "width_feet": width, "closed": closed,
        "material": "stone", "visible": True,
        "points": [_world_point(u, v) for u, v in points], "template_status": "traced",
    }


def _building(key, name, asset_key, u, v, width, depth, rooms):
    return {
        "id": f"waterdeep-building-{key}",
        "asset_key": asset_key,
        "name": name,
        **_world_point(u, v),
        "elevation": 0,
        "rotation": 0,
        "width_feet": width,
        "depth_feet": depth,
        "rooms": rooms,
        "front_road_id": None,
        "template_status": "approximate",
    }


def _heightmap_layer(asset_root: Path):
    path = asset_root / "waterdeep_heightmap.png"
    values = []
    if path.is_file():
        with Image.open(path) as source:
            sampled = source.convert("L").resize((128, 128), Image.Resampling.LANCZOS)
            values = list(sampled.tobytes())
    return {
        "id": "waterdeep-heightmap",
        "layer_type": "heightmap",
        "name": "Waterdeep supplied heightmap",
        "grid_width": 128,
        "grid_height": 128,
        "values": values,
        "width_feet": WATERDEEP_TEXTURE_WIDTH_FEET,
        "height_feet": WATERDEEP_HEIGHT_FEET,
        "origin_x": 0,
        "origin_y": 0,
        "min_elevation_feet": -120,
        "max_elevation_feet": 120,
        "source_image_url": "/media/modules/waterdeep_dragon_heist/waterdeep_heightmap.png",
    }


def waterdeep_dragon_heist_template(media_root):
    """Return a fresh JSON-compatible Waterdeep map and POI seed."""
    asset_root = Path(media_root) / "modules" / "waterdeep_dragon_heist"
    reference_layers = [
        {
            "id": "waterdeep-terrain-texture", "layer_type": "terrain_texture",
            "name": "Waterdeep terrain texture",
            "image_url": "/media/modules/waterdeep_dragon_heist/waterdeep_texture.jpg",
            "visible": True, "opacity": 1, "origin_x": 0, "origin_y": 0,
            "width_feet": WATERDEEP_TEXTURE_WIDTH_FEET, "height_feet": WATERDEEP_HEIGHT_FEET,
            "rotation_degrees": 0, "pixel_width": 2926, "pixel_height": 4096,
            "feet_per_pixel_x": WATERDEEP_TEXTURE_WIDTH_FEET / 2926,
            "feet_per_pixel_y": WATERDEEP_HEIGHT_FEET / 4096,
            "layer_order": -10, "scope": "city",
            "attribution": "Campaign map asset supplied by the DM",
        },
        {
            "id": "waterdeep-dm-reference", "layer_type": "reference",
            "name": "Waterdeep DM landmarks",
            "image_url": "/media/modules/waterdeep_dragon_heist/waterdeep_dm_reference.jpg",
            "visible": False, "opacity": 0.72, "origin_x": 0, "origin_y": 0,
            "width_feet": WATERDEEP_TEXTURE_WIDTH_FEET, "height_feet": WATERDEEP_HEIGHT_FEET,
            "rotation_degrees": 0, "pixel_width": 2868, "pixel_height": 4096,
            "feet_per_pixel_x": WATERDEEP_TEXTURE_WIDTH_FEET / 2868,
            "feet_per_pixel_y": WATERDEEP_HEIGHT_FEET / 4096,
            "layer_order": 10, "scope": "city",
            "attribution": "Campaign map asset supplied by the DM",
        },
        {
            "id": "waterdeep-location-key", "layer_type": "reference",
            "name": "Waterdeep ward location key",
            "image_url": "/media/modules/waterdeep_dragon_heist/waterdeep_location_key.jpg",
            "visible": False, "opacity": 0.9, "origin_x": 0, "origin_y": 0,
            "width_feet": WATERDEEP_TEXTURE_WIDTH_FEET, "height_feet": 14_490,
            "rotation_degrees": 0, "pixel_width": 4096, "pixel_height": 3550,
            "feet_per_pixel_x": WATERDEEP_TEXTURE_WIDTH_FEET / 4096,
            "feet_per_pixel_y": 14_490 / 3550,
            "layer_order": 20, "scope": "city", "reference_only": True,
            "attribution": "Campaign location key supplied by the DM",
        },
        _heightmap_layer(asset_root),
    ]

    # First-pass centerlines traced from the supplied 12,600 x 18,000 DM map.
    # Shorter streets follow their printed label and the visible block opening;
    # they remain editable and deliberately carry trace confidence metadata.
    roads = [
        _road("high-road", "The High Road", 48, [(0.556,.108),(.548,.185),(.536,.300),(.530,.414),(.536,.540),(.552,.620),(.614,.680),(.650,.756),(.708,.818)]),
        _road("way-of-the-dragon", "The Way of the Dragon", 46, [(.515,.605),(.548,.646),(.571,.690),(.592,.735),(.631,.786),(.708,.818)]),
        _road("waterdeep-way", "Waterdeep Way", 48, [(.315,.579),(.365,.590),(.414,.594),(.465,.598),(.515,.605)]),
        _road("market-ring", "The Market", 42, [(.344,.411),(.397,.407),(.457,.416),(.514,.438),(.500,.461),(.444,.470),(.379,.465),(.344,.445),(.344,.411)]),
        _road("street-singing-dolphin", "Street of the Singing Dolphin", 42, [(.258,.186),(.265,.245),(.279,.313),(.309,.381),(.337,.411)]),
        _road("skulls-street", "Skulls Street", 30, [(.405,.174),(.449,.174),(.480,.180)], "street"),
        _road("thunderstaff-way", "Thunderstaff Way", 34, [(.455,.190),(.505,.193),(.530,.199)], "street"),
        _road("sashtar-street", "Sashtar Street", 28, [(.507,.216),(.556,.220),(.590,.226)], "street"),
        _road("vondil-street", "Vondil Street", 32, [(.320,.232),(.430,.232),(.523,.233)], "street"),
        _road("saerdoun-street", "Saerdoun Street", 32, [(.522,.241),(.575,.243),(.642,.255)], "street"),
        _road("delzorin-street", "Delzorin Street", 30, [(.331,.258),(.430,.260),(.525,.264)], "street"),
        _road("diamond-street", "Diamond Street", 30, [(.247,.270),(.304,.272),(.353,.276)], "street"),
        _road("rough-road", "Rough Road", 34, [(.355,.281),(.432,.283),(.506,.286)], "street"),
        _road("sulmor-street", "Sulmor Street", 30, [(.429,.292),(.510,.292),(.601,.292),(.656,.294)], "street"),
        _road("hassantyrs-street", "Hassantyr's Street", 30, [(.414,.308),(.476,.311),(.534,.314)], "street"),
        _road("tarsars-street", "Tarsar's Street", 28, [(.609,.327),(.658,.330),(.691,.337)], "street"),
        _road("golden-serpent-street", "Golden Serpent Street", 30, [(.574,.382),(.633,.384),(.681,.389)], "street"),
        _road("tundals-lane", "Tundal's Lane", 18, [(.554,.398),(.584,.403),(.612,.409)], "lane"),
        _road("tharleon-street", "Tharleon Street", 28, [(.367,.408),(.412,.411),(.452,.416)], "street"),
        _road("keltarn-street", "Keltarn Street", 28, [(.372,.438),(.414,.441),(.455,.445)], "street"),
        _road("street-of-silks", "Street of Silks", 34, [(.487,.421),(.487,.482),(.476,.535),(.453,.580)], "street"),
        _road("street-of-silver", "Street of Silver", 34, [(.514,.420),(.515,.485),(.508,.545),(.492,.598)], "street"),
        _road("swords-street", "Swords Street", 34, [(.451,.418),(.447,.478),(.438,.538),(.414,.594)], "street"),
        _road("bazaar-street", "Bazaar Street", 34, [(.337,.410),(.400,.414),(.466,.421),(.520,.438)], "street"),
        _road("julthoon-street", "Julthoon Street", 34, [(.267,.486),(.346,.500),(.432,.512),(.532,.525)], "street"),
        _road("snail-street", "Snail Street", 30, [(.485,.603),(.536,.620),(.579,.640),(.611,.664)], "street"),
        _road("simple-street", "Simple's Street", 24, [(.543,.587),(.579,.590),(.610,.594)], "street"),
        _road("river-street", "River Street", 30, [(.624,.585),(.655,.598),(.686,.611)], "street"),
        _road("dock-street", "Dock Street", 34, [(.358,.686),(.425,.703),(.492,.716),(.557,.730)], "street"),
        _road("caravan-street", "Caravan Street", 30, [(.603,.677),(.637,.696),(.663,.720)], "street"),
        _road("coach-street", "Coach Street", 28, [(.676,.713),(.700,.735),(.714,.758)], "street"),
        _road("candle-lane", "Candle Lane", 18, [(.485,.665),(.507,.674),(.526,.683)], "lane"),
        _road("fillet-lane", "Fillet Lane", 18, [(.422,.700),(.445,.708),(.465,.715)], "lane"),
        _road("net-street", "Net Street", 22, [(.436,.719),(.467,.729),(.493,.739)], "street"),
        _road("book-street", "Book Street", 24, [(.565,.680),(.585,.706),(.603,.731)], "street"),
        _road("drakiir-street", "Drakiir Street", 24, [(.579,.729),(.607,.739),(.636,.747)], "street"),
        _road("telshambra-street", "Telshambra's Street", 26, [(.601,.670),(.637,.673),(.670,.679)], "street"),
        _road("belzers-walk", "Belzer's Walk", 18, [(.642,.684),(.667,.700),(.684,.718)], "lane"),
        _road("lions-street", "Lions Street", 28, [(.340,.548),(.388,.551),(.433,.555)], "street"),
        _road("slop-street", "Slop Street", 22, [(.522,.742),(.553,.751),(.578,.762)], "street"),
        _road("odd-street", "Odd Street", 22, [(.548,.718),(.574,.726),(.597,.736)], "street"),
    ]

    wards = [
        _ward("field", "Field Ward", [(.294,.077),(.555,.110),(.699,.173),(.660,.205),(.531,.187),(.397,.170),(.302,.132)]),
        _ward("sea", "Sea Ward", [(.258,.170),(.397,.170),(.438,.398),(.337,.411),(.270,.381),(.222,.279)]),
        _ward("north", "North Ward", [(.397,.170),(.660,.205),(.693,.394),(.520,.438),(.438,.398)]),
        _ward("castle", "Castle Ward", [(.270,.381),(.337,.411),(.520,.438),(.515,.605),(.405,.616),(.310,.588),(.257,.505)]),
        _ward("city-dead", "City of the Dead", [(.520,.438),(.693,.394),(.706,.594),(.610,.635),(.515,.605)]),
        _ward("trades", "Trades Ward", [(.515,.605),(.610,.635),(.665,.689),(.585,.704),(.500,.666)]),
        _ward("dock", "Dock Ward", [(.310,.588),(.405,.616),(.500,.666),(.585,.704),(.640,.783),(.493,.783),(.350,.735)]),
        _ward("southern", "Southern Ward", [(.585,.704),(.665,.689),(.718,.815),(.640,.783)]),
    ]

    fortifications = [
        _wall("north", "North City Wall", [(.302,.077),(.365,.088),(.438,.100),(.515,.112),(.583,.132),(.649,.154),(.699,.173)]),
        _wall("east", "Eastern City Wall", [(.699,.173),(.704,.238),(.706,.316),(.708,.392),(.709,.486),(.706,.594)]),
        _wall("trollwall", "Trollwall", [(.706,.594),(.736,.620),(.755,.680),(.768,.746),(.744,.787),(.718,.815)]),
        _wall("sea", "Sea Ward Wall", [(.302,.077),(.282,.116),(.258,.170),(.239,.227),(.222,.279),(.211,.345),(.218,.413),(.239,.480),(.257,.505)]),
        _wall("mount", "Mount Waterdeep Wall", [(.257,.505),(.245,.568),(.235,.633),(.236,.698),(.251,.744)]),
    ]

    buildings = [
        _building("trollskull", "Trollskull Manor", "coaching_inn", 0.548, 0.320, 78, 62,
                  ["Taproom", "Kitchen", "Pantry", "Cellar", "Owner rooms", "Guest rooms"]),
        _building("yawning-portal", "The Yawning Portal", "coaching_inn", 0.521, 0.650, 126, 104,
                  ["Taproom", "Kitchen", "Well chamber", "Private rooms", "Cellar", "Guest rooms"]),
        _building("castle-waterdeep", "Castle Waterdeep", "storehouse", 0.405, 0.588, 310, 250,
                  ["Great hall", "Guard rooms", "Offices", "Armory", "Barracks", "Stores", "Courtyard"]),
    ]

    poi_specs = [
        ("Troll Gate", "gate", 0.322, 0.158, False),
        ("North Gate", "gate", 0.414, 0.183, False),
        ("West Gate", "gate", 0.225, 0.342, False),
        ("River Gate", "gate", 0.674, 0.610, False),
        ("South Gate", "gate", 0.664, 0.846, False),
        ("The Market", "market", 0.370, 0.447, False),
        ("City of the Dead", "district", 0.573, 0.522, False),
        ("Castle Waterdeep", "civic", 0.405, 0.588, False),
        ("Palace of Waterdeep", "civic", 0.302, 0.588, False),
        ("Trollskull Manor", "tavern", 0.548, 0.320, False),
        ("The Yawning Portal", "tavern", 0.521, 0.650, False),
        ("Deepwater Harbor", "harbor", 0.435, 0.824, True),
        ("Naval Harbor", "harbor", 0.275, 0.755, True),
        ("Stormhaven Island", "landmark", 0.222, 0.810, True),
        ("Deepwater Isle", "landmark", 0.420, 0.888, True),
    ]
    points_of_interest = [
        {"name": name, "point_type": point_type, **_world_point(u, v), "elevation": 0,
         "water_access": water_access, "road_access": not water_access or point_type == "harbor",
         "template_status": "approximate"}
        for name, point_type, u, v, water_access in poi_specs
    ]

    return {
        "map_key": WATERDEEP_MAP_KEY, "name": "Waterdeep", "settlement_type": "city",
        "atlas_x": MODULE_DEFINITIONS["waterdeep_dragon_heist"]["atlas_position"]["x"],
        "atlas_y": MODULE_DEFINITIONS["waterdeep_dragon_heist"]["atlas_position"]["y"],
        "coordinate_space_key": "faerun-v1",
        "notes": ("Pre-built Waterdeep: Dragon Heist starting map. Terrain and named positions "
                  "are editable; draft roads and POIs should be refined against the supplied keys."),
        "terrain_strokes": [], "roads": roads, "water_bodies": [], "buildings": buildings,
        "environment": {"biome": "coastal grassland", "coastal": True, "regions": wards,
                        "fortifications": fortifications,
                        "boundary_notes": "Ward polygons are inferred first-pass boundaries; wall splines are traced from the DM map."},
        "reference_layers": reference_layers, "points_of_interest": points_of_interest,
        "party_position": {**_world_point(0.521, 0.650), "elevation": 0,
                           "road_access": True, "water_access": False},
        "calibration": {"core_width_feet": WATERDEEP_CORE_WIDTH_FEET,
                        "height_feet": WATERDEEP_HEIGHT_FEET,
                        "external_reference_url": "https://www.aidedd.org/atlas/index.php?map=W&l=1"},
    }


def campaign_module_template(module_name, media_root):
    definition = module_definition(module_name)
    if definition and definition["key"] == "waterdeep_dragon_heist":
        return waterdeep_dragon_heist_template(media_root)
    return None


def module_definition(identifier):
    normalized = (identifier or "").strip().casefold()
    for definition in MODULE_DEFINITIONS.values():
        if normalized in {definition["key"].casefold(), definition["name"].casefold()}:
            return definition
    return None


def module_catalog():
    """Return serializable module metadata without exposing server paths."""
    return [
        {
            **definition,
            "npc_count": len(module_npc_presets(definition["key"])),
            "calendar": {key: value for key, value in definition["calendar"].items() if key != "filename"},
        }
        for definition in MODULE_DEFINITIONS.values()
    ]
