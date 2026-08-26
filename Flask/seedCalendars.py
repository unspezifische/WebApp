import json
from pathlib import Path
from sqlalchemy.exc import IntegrityError

from app import app, db, GameElement, Campaign, Calendar

# Push the application context
app.app_context().push()

BASE_DIR = Path(__file__).resolve().parent

calendar_formats = [
    {
        "system": "universal",
        "element_type": "calendar_format",
        "module": None,
        "setting": "Real World",
        "name": "Gregorian Calendar",
        "slug": "gregorian",
        "filename": "gregorian.json",
    },
    {
        "system": "D&D 5e",
        "element_type": "calendar_format",
        "module": None,
        "setting": "Forgotten Realms",
        "name": "Calendar of Harptos",
        "slug": "harptos",
        "filename": "harptos.json",
    }
]

def load_json(filename):
    with open(BASE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)

seeded_formats = {}

for fmt in calendar_formats:
    data = load_json(fmt["filename"])

    existing = GameElement.query.filter_by(
        element_type=fmt["element_type"],
        name=fmt["name"]
    ).first()

    if existing:
        existing.system = fmt["system"]
        existing.module = fmt["module"]
        existing.setting = fmt["setting"]
        existing.data = data

        if "slug" in GameElement.__table__.columns.keys():
            existing.slug = fmt["slug"]

        try:
            db.session.commit()
            print(f"Updated calendar format: {fmt['name']}")
        except IntegrityError:
            db.session.rollback()
            print(f"Failed to update calendar format: {fmt['name']}")
            continue

        seeded_formats[fmt["slug"]] = existing
    else:
        new_element_kwargs = {
            "system": fmt["system"],
            "element_type": fmt["element_type"],
            "module": fmt["module"],
            "setting": fmt["setting"],
            "name": fmt["name"],
            "data": data,
        }

        if "slug" in GameElement.__table__.columns.keys():
            new_element_kwargs["slug"] = fmt["slug"]

        new_element = GameElement(**new_element_kwargs)

        try:
            db.session.add(new_element)
            db.session.commit()
            print(f"Inserted calendar format: {fmt['name']}")
            seeded_formats[fmt["slug"]] = new_element
        except IntegrityError:
            db.session.rollback()
            print(f"Calendar format {fmt['name']} already exists or failed to insert")
            existing = GameElement.query.filter_by(
                element_type=fmt["element_type"],
                name=fmt["name"]
            ).first()
            if existing:
                seeded_formats[fmt["slug"]] = existing

campaigns = Campaign.query.all()

for campaign in campaigns:
    if "purpose" in Calendar.__table__.columns.keys():
        existing_in_world_calendar = Calendar.query.filter_by(
            campaign_id=campaign.id,
            purpose="in_world"
        ).first()
    else:
        existing_in_world_calendar = Calendar.query.filter_by(
            campaign_id=campaign.id
        ).first()

    if existing_in_world_calendar:
        print(f"Campaign '{campaign.name}' already has a calendar")
        continue

    if campaign.rules_system == "D&D 5e" and "harptos" in seeded_formats:
        format_element = seeded_formats["harptos"]
        format_slug = "harptos"
        calendar_name = f"{campaign.name} In-World Calendar"
    else:
        format_element = seeded_formats.get("gregorian")
        format_slug = "gregorian"
        calendar_name = f"{campaign.name} Calendar"

    if not format_element:
        print(f"Could not create calendar for campaign '{campaign.name}' because format was missing")
        continue

    new_calendar_kwargs = {
        "name": calendar_name,
        "description": f"Default calendar for campaign {campaign.name}",
        "campaign_id": campaign.id,
        "format_id": format_element.id,
        "format_slug": format_slug,
        "current_year": 1487,
        "current_month_index": 9,
        "current_day": 6,
        "current_hour": 0,
        "current_minute": 0,
        "epoch_year": 1,
        "epoch_month_index": 0,
        "epoch_day": 1,
    }

    if "purpose" in Calendar.__table__.columns.keys():
        new_calendar_kwargs["purpose"] = "in_world"

    if "is_primary" in Calendar.__table__.columns.keys():
        new_calendar_kwargs["is_primary"] = True

    new_calendar = Calendar(**new_calendar_kwargs)

    try:
        db.session.add(new_calendar)
        db.session.commit()
        print(f"Created default calendar for campaign '{campaign.name}'")
    except IntegrityError:
        db.session.rollback()
        print(f"Failed to create calendar for campaign '{campaign.name}'")
