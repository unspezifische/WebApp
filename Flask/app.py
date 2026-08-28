def resolve_system_from_request():
    """Resolve game system using explicit header/param first, then campaign.

    Order of precedence:
    1) `System` header or `system` query param (explicit override).
    2) `CampaignID` header -> look up the campaign's effective rules system.
    If neither yields a system, returns (None, None) and leaves the caller to warn.
    """
    system_override = request.headers.get('System') or request.args.get('system')
    if system_override:
        return system_override, None

    campaign_id = request.headers.get('CampaignID')
    if campaign_id:
        campaign = Campaign.query.filter_by(id=campaign_id).first()
        if campaign:
            return campaign.rules_system, campaign
    return None, None
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask import render_template ## For rendering wiki pages
from flask import redirect, url_for

## Server Admin Console
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
import flask_monitoringdashboard as dashboard
from flask_migrate import upgrade

## For database stuff
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select, Numeric, text, func, UniqueConstraint
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, TSVECTOR

from flask_migrate import Migrate   ## For database migrations

from flask_compress import Compress

from rapidfuzz import fuzz, process

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import NotFound
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, decode_token, get_jwt, unset_jwt_cookies

from jwt import InvalidTokenError, ExpiredSignatureError
from flask_socketio import SocketIO, join_room, leave_room, emit, send, disconnect

from threading import Thread, Lock
from datetime import datetime, timedelta, timezone
from functools import wraps
import io
import os
import hashlib
import mimetypes
import base64
import csv  ## For importing items from CSV
import json ## For sending JSON data


import logging ## For debug logging
import traceback
import shutil
import subprocess

from settlement_simulation import calculate_lamplighter_state
from travel_planning import estimate_travel_options
from economy_simulation import commodity_price, simulate_business_day, simulate_commodity_day
from workforce_simulation import rebalance_workforce, choose_noble_investment
from module_templates import campaign_module_template, module_catalog, module_definition
from module_npcs import module_npc_presets
from npc_generation import generated_npc, supported_generation_options
from settlement_generation import BIOMES, GOVERNMENTS, RESOURCES, SETTLEMENT_PRESETS, generate_settlement

import markdown
from urllib.parse import unquote

DND_RULESET_SYSTEMS = {
    '3.5e': 'D&D 3.5e',
    '4e': 'D&D 4e',
    '5e': 'D&D 5e',
    '5e (2024)': 'D&D 5e (2024)',
}


app = Flask(__name__)
Compress(app)
dashboard.bind(app)

app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'Library')
app.config['SECRET_KEY'] = 'secret-key'

db_url = os.environ.get("DATABASE_URL")

if not db_url:
    # Bare-metal default: local Postgres on the same machine
    # (use localhost TCP to avoid socket/peer surprises)
    db_url = "postgresql://admin:admin@localhost:5432/db"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 10,
    "max_overflow": 20,
    "pool_timeout": 30,
}

## Token stuff
app.config['JWT_SECRET_KEY'] = 'jwt-secret-key'
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=5)
jwt = JWTManager(app)

app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024 # 2Gb Upload size
app.config['PROPAGATE_EXCEPTIONS'] = True

## Database stuff
db = SQLAlchemy()

## Admin Console
admin = Admin(app, name='Kachhapa Admin')

# # For INFO level
# app.logger.setLevel(logging.INFO)  # set the desired logging level
# handler = logging.StreamHandler()
# handler.setLevel(logging.INFO)  # set the desired logging level
# app.logger.addHandler(handler)
# app.debug = False

# For DEBUG level
app.logger.setLevel(logging.DEBUG)  # set the desired logging level to DEBUG
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)  # set the desired logging level to DEBUG
app.logger.addHandler(handler)
app.debug = True

app.logger.debug("Debugging set to True")

RABBIT_URL = os.getenv("RABBIT_URL", "amqp://guest:guest@127.0.0.1:5672//")

socketio = SocketIO(
    app,
    async_mode=os.getenv("SOCKETIO_ASYNC_MODE", "gevent"),
    message_queue=RABBIT_URL,
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    ping_timeout=60000,
)

socketio.init_app(app)

db.init_app(app)

# Map of username -> sid for active socket connections. Guarded by a lock
active_connections = {}
active_connections_lock = Lock()


def socket_db_session(handler):
    """Ensure Socket.IO events always release DB connections back to the pool."""
    @wraps(handler)
    def wrapped(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()

    return wrapped


INTEGER_MIN = -2147483648
INTEGER_MAX = 2147483647



# Association table
campaign_members = db.Table('campaign_members',
    db.Column('userID', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('campaignID', db.Integer, db.ForeignKey('campaign.id'), primary_key=True),
    db.Column('characterID', db.Integer, db.ForeignKey('character.id'))
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))
    is_online = db.Column(db.Boolean, default=False) ## Tracks if a user is currently signed in or not
    sid = db.Column(db.String(100), nullable=True)  ## Stores the web socket ID a user is connected from
    campaigns = db.relationship('Campaign', secondary=campaign_members, backref=db.backref('members', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'is_online': self.is_online,
            'sid': self.sid,
            'campaigns': [campaign.to_dict() for campaign in self.campaigns]
        }

class Character(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(120))  # legacy icon filepath or name

    system = db.Column(db.String(50))
    userID = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='characters')
    campaignID = db.Column(db.Integer, db.ForeignKey('campaign.id'))
    campaign = db.relationship('Campaign', backref='party_members')

    character_name = db.Column(db.String(50), nullable=True)

    Class = db.Column(db.String(50))
    Subclass = db.Column(db.String(80), nullable=True)
    Background = db.Column(db.String(50))
    Race = db.Column(db.String(50))
    Alignment = db.Column(db.String(50))
    ExperiencePoints = db.Column(db.Integer)

    strength = db.Column(db.Integer)
    dexterity = db.Column(db.Integer)
    constitution = db.Column(db.Integer)
    intelligence = db.Column(db.Integer)
    wisdom = db.Column(db.Integer)
    charisma = db.Column(db.Integer)

    PersonalityTraits = db.Column(db.Text)
    Ideals = db.Column(db.Text)
    Bonds = db.Column(db.Text)
    Flaws = db.Column(db.Text)
    Feats = db.Column(db.Text)
    Proficiencies = db.Column(db.Text)

    CurrentHitPoints = db.Column(db.Integer)
    TemporaryHitPoints = db.Column(db.Integer)

    cp = db.Column(db.Integer)
    sp = db.Column(db.Integer)
    ep = db.Column(db.Integer)
    gp = db.Column(db.Integer)
    pp = db.Column(db.Integer)

    # Avatar system
    avatar_mode = db.Column(
        db.String(20),
        nullable=False,
        default='initials',
        server_default='initials'
    )
    avatar_color = db.Column(db.String(20), nullable=True, default='#64748b')
    avatar_text_color = db.Column(db.String(20), nullable=True, default='#f8fafc')
    avatar_image_url = db.Column(db.String(255), nullable=True)
    avatar_thumb_url = db.Column(db.String(255), nullable=True)
    avatar_preset_key = db.Column(db.String(100), nullable=True)
    avatar_shape = db.Column(
        db.String(20),
        nullable=False,
        default='circle',
        server_default='circle'
    )
    avatar_frame_color = db.Column(db.String(20), nullable=True)

    inventory = db.relationship('InventoryItem', backref='character', lazy=True)
    journal_entries = db.relationship('Journal', backref='character', lazy=True)

    def get_avatar_initials(self):
        name = (self.character_name or '').strip()
        if not name:
            return '?'

        parts = [part for part in name.split() if part]
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()

        return parts[0][:2].upper()

    def get_avatar_props(self):
        mode = (self.avatar_mode or 'initials').strip().lower()

        default_bg = self.avatar_color or '#64748b'
        default_text = self.avatar_text_color or '#f8fafc'

        image_url = self.avatar_thumb_url or self.avatar_image_url or None
        full_image_url = self.avatar_image_url or None

        if mode == 'image' and image_url:
            resolved_mode = 'image'
        elif mode == 'upload' and image_url:
            # Backward compatibility with any older saved values
            resolved_mode = 'image'
        elif mode == 'preset' and self.avatar_preset_key:
            preset = character_avatar_preset(self.avatar_preset_key)
            if preset:
                resolved_mode = 'preset'
                image_url = preset['url']
                full_image_url = preset['url']
            else:
                resolved_mode = 'initials'
        else:
            resolved_mode = 'initials'

        return {
            'mode': resolved_mode,
            'initials': self.get_avatar_initials(),
            'color': default_bg,
            'text_color': default_text,
            'image_url': image_url,
            'full_image_url': full_image_url,
            'preset_key': self.avatar_preset_key,
            'shape': self.avatar_shape or 'circle',
            'frame_color': self.avatar_frame_color,
        }

    def to_dict(self):
        avatar = self.get_avatar_props()

        return {
            'id': self.id,
            'icon': self.icon,
            'userID': self.userID,
            'campaignID': self.campaignID,
            'campaign': self.campaign.name if self.campaign else None,
            'Name': self.character_name,
            'Class': self.Class,
            'Subclass': self.Subclass,
            'Background': self.Background,
            'Race': self.Race,
            'Alignment': self.Alignment,
            'ExperiencePoints': self.ExperiencePoints,
            'strength': self.strength,
            'dexterity': self.dexterity,
            'constitution': self.constitution,
            'intelligence': self.intelligence,
            'wisdom': self.wisdom,
            'charisma': self.charisma,
            'PersonalityTraits': self.PersonalityTraits,
            'Ideals': self.Ideals,
            'Bonds': self.Bonds,
            'Flaws': self.Flaws,
            'Proficiencies': json.loads(self.Proficiencies) if self.Proficiencies else [],
            'CurrentHitPoints': self.CurrentHitPoints,
            'TemporaryHitPoints': self.TemporaryHitPoints,
            'cp': self.cp,
            'sp': self.sp,
            'ep': self.ep,
            'gp': self.gp,
            'pp': self.pp,
            'Feats': json.loads(self.Feats) if self.Feats else [],

            'avatar_mode': self.avatar_mode,
            'avatar_color': self.avatar_color,
            'avatar_text_color': self.avatar_text_color,
            'avatar_image_url': self.avatar_image_url,
            'avatar_thumb_url': self.avatar_thumb_url,
            'avatar_preset_key': self.avatar_preset_key,
            'avatar_shape': self.avatar_shape,
            'avatar_frame_color': self.avatar_frame_color,

            'avatar': avatar,
        }

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    system = db.Column(db.String(50), nullable=False)    # e.g., 'D&D', 'Pathfinder'
    ruleset = db.Column(db.String(30))                   # e.g., '3.5e', '4e', '5e', '5e (2024)'
    icon = db.Column(db.String(120))  # icon filepath or name
    description = db.Column(db.Text)
    module = db.Column(db.String(160))
    calendars = db.relationship('Calendar', backref='campaign', lazy=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    dm_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scribes = db.Column(ARRAY(db.Integer), default=[])  # List of user IDs who are scribes
    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_campaigns')
    dm = db.relationship('User', foreign_keys=[dm_id], backref='dm_campaigns')

    @property
    def rules_system(self):
        """Return the catalog key used for classes, races, and other rules data."""
        if self.system == 'D&D 5e':  # Compatibility before/while the migration runs.
            return 'D&D 5e'
        if self.system == 'D&D':
            return DND_RULESET_SYSTEMS.get(self.ruleset or '5e', 'D&D 5e')
        return self.system

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'system': self.system,
            'ruleset': self.ruleset,
            'rules_system': self.rules_system,
            'description': self.description,
            'module': self.module,
            'icon': self.icon,
            'owner': self.owner.username if self.owner else None,
            'owner_id': self.owner.id if self.owner else None,
            'dm': self.dm.username if self.dm else None,
            'dm_id': self.dm.id if self.dm else None,
            'scribes': self.scribes,
        }


class CampaignModuleInstallation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=True, index=True)
    module_key = db.Column(db.String(120), nullable=False)
    module_name = db.Column(db.String(160), nullable=False)
    setting_key = db.Column(db.String(80))
    starting_year = db.Column(db.Integer)
    installed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    settlement_strategy = db.Column(db.String(30), nullable=False, default='merge')
    calendar_strategy = db.Column(db.String(30), nullable=False, default='keep_current')
    installed_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('campaign_id', 'module_key', name='uq_campaign_module_installation'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'module_key': self.module_key,
            'module_name': self.module_name,
            'setting_key': self.setting_key,
            'starting_year': self.starting_year,
            'settlement_strategy': self.settlement_strategy,
            'calendar_strategy': self.calendar_strategy,
            'installed_by_id': self.installed_by_id,
            'installed_at': self.installed_at.isoformat() if self.installed_at else None,
        }


class LamplighterRoute(db.Model):
    """An ordered street-lighting route in campaign world coordinates (feet)."""
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    evening_start_minute = db.Column(db.Integer, nullable=False, default=1080)
    morning_start_minute = db.Column(db.Integer, nullable=False, default=300)
    minutes_per_stop = db.Column(db.Integer, nullable=False, default=8)
    active = db.Column(db.Boolean, nullable=False, default=True)


class StreetLamp(db.Model):
    """A persistent lamp state plus its position in Kachhapa's Cartesian CRS."""
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False, index=True)
    route_id = db.Column(db.Integer, db.ForeignKey('lamplighter_route.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    elevation = db.Column(db.Float, nullable=False, default=0)
    route_order = db.Column(db.Integer, nullable=False)
    lit = db.Column(db.Boolean, nullable=False, default=False)
    fuel_remaining = db.Column(db.Float, nullable=True)

    __table_args__ = (UniqueConstraint('route_id', 'route_order', name='uq_street_lamp_route_order'),)


class PartyMapPosition(db.Model):
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), primary_key=True)
    map_key = db.Column(db.String(120), nullable=False, default='pinewater')
    x = db.Column(db.Float, nullable=False, default=0)
    y = db.Column(db.Float, nullable=False, default=0)
    elevation = db.Column(db.Float, nullable=False, default=0)
    water_access = db.Column(db.Boolean, nullable=False, default=False)
    road_access = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {'campaign_id': self.campaign_id, 'map_key': self.map_key, 'x': self.x, 'y': self.y, 'elevation': self.elevation,
                'water_access': self.water_access, 'road_access': self.road_access}


class MapPointOfInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False, index=True)
    map_key = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    point_type = db.Column(db.String(50), nullable=False, default='landmark')
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    elevation = db.Column(db.Float, nullable=False, default=0)
    water_access = db.Column(db.Boolean, nullable=False, default=False)
    road_access = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {'id': self.id, 'campaign_id': self.campaign_id, 'map_key': self.map_key, 'name': self.name,
                'point_type': self.point_type, 'x': self.x, 'y': self.y, 'elevation': self.elevation,
                'water_access': self.water_access, 'road_access': self.road_access}


def seed_campaign_world(campaign):
    """Instantiate a fresh settlement from the campaign's selected module."""
    template = campaign_module_template(campaign.module, MEDIA_ROOT)
    if not template:
        return None
    template = persist_reference_layer_media(campaign.id, template)

    location = WorldAtlasLocation(
        campaign_id=campaign.id,
        name=template['name'],
        map_key=template['map_key'],
        settlement_type=template['settlement_type'],
        notes=template.get('notes'),
        atlas_x=template.get('atlas_x'),
        atlas_y=template.get('atlas_y'),
        is_primary=True,
        terrain_strokes=template.get('terrain_strokes', []),
        roads=template.get('roads', []),
        water_bodies=template.get('water_bodies', []),
        buildings=template.get('buildings', []),
        reference_layers=template.get('reference_layers', []),
        environment=template.get('environment', {}),
    )
    db.session.add(location)
    db.session.flush()

    for point in template.get('points_of_interest', []):
        db.session.add(MapPointOfInterest(
            campaign_id=campaign.id,
            map_key=location.map_key,
            name=point['name'],
            point_type=point.get('point_type', 'landmark'),
            x=point['x'],
            y=point['y'],
            elevation=point.get('elevation', 0),
            water_access=point.get('water_access', False),
            road_access=point.get('road_access', True),
        ))

    party = template.get('party_position')
    if party:
        db.session.add(PartyMapPosition(
            campaign_id=campaign.id,
            map_key=location.map_key,
            x=party['x'],
            y=party['y'],
            elevation=party.get('elevation', 0),
            water_access=party.get('water_access', False),
            road_access=party.get('road_access', True),
        ))
    return location


class SettlementMapDesign(db.Model):
    """Campaign-scoped authoring state, stored in world feet rather than render units."""
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), primary_key=True)
    terrain_strokes = db.Column(db.JSON, nullable=False, default=list)
    roads = db.Column(db.JSON, nullable=False, default=list)
    buildings = db.Column(db.JSON, nullable=False, default=list)
    reference_layers = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'campaign_id': self.campaign_id,
            'coordinate_unit': 'feet',
            'terrain_strokes': self.terrain_strokes or [],
            'roads': self.roads or [],
            'buildings': self.buildings or [],
            'reference_layers': self.reference_layers or [],
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WorldAtlasLocation(db.Model):
    """A place on a campaign atlas with its own independently editable map."""
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default='New Settlement')
    location_type = db.Column(db.String(30), nullable=False, default='settlement')
    settlement_type = db.Column(db.String(30), nullable=False, default='town')
    status = db.Column(db.String(20), nullable=False, default='active')
    population = db.Column(db.Integer)
    notes = db.Column(db.Text)
    destroyed_at = db.Column(db.DateTime)
    map_key = db.Column(db.String(120), nullable=False)
    atlas_x = db.Column(db.Float)
    atlas_y = db.Column(db.Float)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    terrain_strokes = db.Column(db.JSON, nullable=False, default=list)
    roads = db.Column(db.JSON, nullable=False, default=list)
    water_bodies = db.Column(db.JSON, nullable=False, default=list)
    buildings = db.Column(db.JSON, nullable=False, default=list)
    reference_layers = db.Column(db.JSON, nullable=False, default=list)
    environment = db.Column(db.JSON, nullable=False, default=dict)
    generation_config = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint('campaign_id', 'map_key', name='uq_world_atlas_location_map_key'),)

    def atlas_dict(self):
        return {
            'id': self.id, 'campaign_id': self.campaign_id, 'name': self.name,
            'location_type': self.location_type, 'map_key': self.map_key,
            'atlas_x': self.atlas_x, 'atlas_y': self.atlas_y, 'is_primary': self.is_primary,
            'settlement_type': self.settlement_type, 'status': self.status,
            'population': self.population, 'notes': self.notes or '',
            'environment': self.environment or {},
            'generation_config': self.generation_config or {},
            'placed': self.atlas_x is not None and self.atlas_y is not None,
            'destroyed_at': self.destroyed_at.isoformat() if self.destroyed_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_map_dict(self):
        return {
            **self.atlas_dict(), 'settlement_id': self.id, 'coordinate_unit': 'feet',
            'terrain_strokes': self.terrain_strokes or [], 'roads': self.roads or [],
            'water_bodies': self.water_bodies or [], 'buildings': self.buildings or [],
            'reference_layers': self.reference_layers or [],
        }


class MapMediaAsset(db.Model):
    """Opaque, database-backed raster used by settlement maps and world atlases."""
    __tablename__ = 'map_media_asset'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, unique=True, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False, default='map_reference')
    name = db.Column(db.String(160), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    pixel_width = db.Column(db.Integer)
    pixel_height = db.Column(db.Integer)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    @property
    def content_url(self):
        return f'/api/map-media/{self.public_id}'


class CampaignWorldAtlas(db.Model):
    """One canonical setting atlas per campaign; art lives in PostgreSQL."""
    __tablename__ = 'campaign_world_atlas'
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), primary_key=True)
    setting_key = db.Column(db.String(80), nullable=False, default='custom')
    coordinate_space_key = db.Column(db.String(80), nullable=False, default='custom-v1')
    name = db.Column(db.String(160), nullable=False, default='Campaign World')
    image_asset_id = db.Column(db.Integer, db.ForeignKey('map_media_asset.id', ondelete='SET NULL'))
    attribution = db.Column(db.Text)
    source_name = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    image_asset = db.relationship('MapMediaAsset', foreign_keys=[image_asset_id])

    def to_dict(self):
        return {
            'key': self.setting_key,
            'coordinate_space_key': self.coordinate_space_key,
            'name': self.name,
            'image_url': self.image_asset.content_url if self.image_asset else None,
            'image_asset_id': self.image_asset_id,
            'source_name': self.source_name,
            'attribution': self.attribution or '',
            'tile_url_template': None,
        }


class SettingWorldAtlas(db.Model):
    """Server-wide licensed atlas default shared by modules in the same setting."""
    __tablename__ = 'setting_world_atlas'
    setting_key = db.Column(db.String(80), primary_key=True)
    coordinate_space_key = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    image_asset_id = db.Column(db.Integer, db.ForeignKey('map_media_asset.id', ondelete='SET NULL'))
    attribution = db.Column(db.Text)
    source_name = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    image_asset = db.relationship('MapMediaAsset', foreign_keys=[image_asset_id])
class SettlementEconomyState(db.Model):
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), primary_key=True)
    day_index = db.Column(db.Integer, nullable=False, default=0)


class CommodityMarket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False, index=True)
    commodity_key = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    base_price_cp = db.Column(db.Integer, nullable=False)
    current_price_cp = db.Column(db.Integer, nullable=False)
    stock = db.Column(db.Float, nullable=False)
    target_stock = db.Column(db.Float, nullable=False)
    daily_demand = db.Column(db.Float, nullable=False)
    daily_supply = db.Column(db.Float, nullable=False)
    import_threshold = db.Column(db.Float, nullable=False, default=.3)
    import_quantity = db.Column(db.Float, nullable=False)
    elasticity = db.Column(db.Float, nullable=False, default=.65)
    last_imported = db.Column(db.Float, nullable=False, default=0)

    __table_args__ = (UniqueConstraint('campaign_id', 'commodity_key', name='uq_commodity_market_campaign_key'),)

    def to_dict(self):
        return {'id':self.id,'commodity_key':self.commodity_key,'name':self.name,'base_price_cp':self.base_price_cp,
                'current_price_cp':self.current_price_cp,'stock':round(self.stock,2),'target_stock':self.target_stock,
                'price_index':round(self.current_price_cp / self.base_price_cp, 2),'last_imported':self.last_imported}


class SettlementBusiness(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    business_type = db.Column(db.String(50), nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    foot_traffic = db.Column(db.Float, nullable=False, default=1)
    quality = db.Column(db.Float, nullable=False, default=1)
    accessibility = db.Column(db.Float, nullable=False, default=1)
    cash_reserves_cp = db.Column(db.Integer, nullable=False, default=0)
    daily_capacity = db.Column(db.Integer, nullable=False, default=100)
    average_sale_cp = db.Column(db.Integer, nullable=False, default=40)
    cost_of_goods_rate = db.Column(db.Float, nullable=False, default=.4)
    daily_overhead_cp = db.Column(db.Integer, nullable=False, default=500)
    closure_grace_days = db.Column(db.Integer, nullable=False, default=3)
    slump_days = db.Column(db.Integer, nullable=False, default=0)
    player_owned = db.Column(db.Boolean, nullable=False, default=False)
    closed = db.Column(db.Boolean, nullable=False, default=False)

    def simulation_dict(self):
        return {column:getattr(self,column) for column in ('id','x','y','foot_traffic','quality','accessibility','cash_reserves_cp',
                'daily_capacity','average_sale_cp','cost_of_goods_rate','daily_overhead_cp','closure_grace_days','slump_days','closed')}

    def to_dict(self):
        return {'id':self.id,'name':self.name,'business_type':self.business_type,'x':self.x,'y':self.y,
                'foot_traffic':self.foot_traffic,'quality':self.quality,'accessibility':self.accessibility,
                'cash_reserves_cp':self.cash_reserves_cp,'player_owned':self.player_owned,'closed':self.closed,'slump_days':self.slump_days}


class BusinessDailyLedger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('settlement_business.id', ondelete='CASCADE'), nullable=False, index=True)
    day_index = db.Column(db.Integer, nullable=False)
    customers = db.Column(db.Integer, nullable=False)
    revenue_cp = db.Column(db.Integer, nullable=False)
    costs_cp = db.Column(db.Integer, nullable=False)
    profit_cp = db.Column(db.Integer, nullable=False)
    cash_reserves_cp = db.Column(db.Integer, nullable=False)
    market_share = db.Column(db.Float, nullable=True)

    __table_args__ = (UniqueConstraint('business_id', 'day_index', name='uq_business_ledger_day'),)

    def to_dict(self):
        return {'day_index':self.day_index,'customers':self.customers,'revenue_cp':self.revenue_cp,
                'costs_cp':self.costs_cp,'profit_cp':self.profit_cp,'cash_reserves_cp':self.cash_reserves_cp,
                'market_share':self.market_share}


class OccupationDefinition(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    campaign_id=db.Column(db.Integer,db.ForeignKey('campaign.id'),nullable=False,index=True)
    occupation_key=db.Column(db.String(80),nullable=False)
    name=db.Column(db.String(120),nullable=False)
    ability_weights=db.Column(db.JSON,nullable=False,default=dict)
    target_workers=db.Column(db.Integer,nullable=False,default=0)
    minimum_suitability=db.Column(db.Float,nullable=False,default=.42)
    base_wage_cp=db.Column(db.Integer,nullable=False,default=20)
    produces_commodity_key=db.Column(db.String(80),nullable=True)
    __table_args__=(UniqueConstraint('campaign_id','occupation_key',name='uq_occupation_campaign_key'),)
    def simulation_dict(self): return {'key':self.occupation_key,'ability_weights':self.ability_weights,'target_workers':self.target_workers,'minimum_suitability':self.minimum_suitability}
    def to_dict(self): return {'id':self.id,'key':self.occupation_key,'name':self.name,'ability_weights':self.ability_weights,'target_workers':self.target_workers,'base_wage_cp':self.base_wage_cp,'produces_commodity_key':self.produces_commodity_key}


class NobleFamily(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    campaign_id=db.Column(db.Integer,db.ForeignKey('campaign.id'),nullable=False,index=True)
    name=db.Column(db.String(120),nullable=False)
    wealth_cp=db.Column(db.Integer,nullable=False,default=0)
    investment_risk=db.Column(db.Float,nullable=False,default=.5)
    active=db.Column(db.Boolean,nullable=False,default=True)
    def to_dict(self): return {'id':self.id,'name':self.name,'wealth_cp':self.wealth_cp,'investment_risk':self.investment_risk,'active':self.active}


class SettlementEconomicAgent(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    campaign_id=db.Column(db.Integer,db.ForeignKey('campaign.id'),nullable=False,index=True)
    npc_id=db.Column(db.Integer,db.ForeignKey('npc.id'),nullable=True,unique=True)
    name=db.Column(db.String(120),nullable=False)
    strength=db.Column(db.Integer,nullable=False,default=10);dexterity=db.Column(db.Integer,nullable=False,default=10)
    constitution=db.Column(db.Integer,nullable=False,default=10);intelligence=db.Column(db.Integer,nullable=False,default=10)
    wisdom=db.Column(db.Integer,nullable=False,default=10);charisma=db.Column(db.Integer,nullable=False,default=10)
    economic_autonomy=db.Column(db.Boolean,nullable=False,default=True)
    story_locked=db.Column(db.Boolean,nullable=False,default=False)
    simulation_generated=db.Column(db.Boolean,nullable=False,default=True)
    social_class=db.Column(db.String(30),nullable=False,default='commoner')
    occupation_key=db.Column(db.String(80),nullable=True)
    employer_business_id=db.Column(db.Integer,db.ForeignKey('settlement_business.id'),nullable=True)
    noble_family_id=db.Column(db.Integer,db.ForeignKey('noble_family.id'),nullable=True)
    wealth_cp=db.Column(db.Integer,nullable=False,default=0)
    career_cooldown_until_day=db.Column(db.Integer,nullable=False,default=0)
    def simulation_dict(self):
        return {key:getattr(self,key) for key in ('id','strength','dexterity','constitution','intelligence','wisdom','charisma','economic_autonomy','story_locked','social_class','occupation_key','career_cooldown_until_day')}
    def to_dict(self): return {'id':self.id,'npc_id':self.npc_id,'name':self.name,'abilities':{key:getattr(self,key) for key in ('strength','dexterity','constitution','intelligence','wisdom','charisma')},'economic_autonomy':self.economic_autonomy,'story_locked':self.story_locked,'simulation_generated':self.simulation_generated,'social_class':self.social_class,'occupation_key':self.occupation_key,'employer_business_id':self.employer_business_id,'noble_family_id':self.noble_family_id,'wealth_cp':self.wealth_cp,'career_cooldown_until_day':self.career_cooldown_until_day}


class EmploymentHistory(db.Model):
    id=db.Column(db.Integer,primary_key=True);agent_id=db.Column(db.Integer,db.ForeignKey('settlement_economic_agent.id',ondelete='CASCADE'),nullable=False,index=True)
    day_index=db.Column(db.Integer,nullable=False);from_occupation=db.Column(db.String(80));to_occupation=db.Column(db.String(80));reason=db.Column(db.String(120),nullable=False)


class NobleInvestment(db.Model):
    id=db.Column(db.Integer,primary_key=True);family_id=db.Column(db.Integer,db.ForeignKey('noble_family.id',ondelete='CASCADE'),nullable=False,index=True)
    business_id=db.Column(db.Integer,db.ForeignKey('settlement_business.id',ondelete='CASCADE'),nullable=False,index=True)
    principal_cp=db.Column(db.Integer,nullable=False,default=0);total_dividends_cp=db.Column(db.Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint('family_id','business_id',name='uq_noble_family_business_investment'),)
    def to_dict(self): return {'id':self.id,'family_id':self.family_id,'business_id':self.business_id,'principal_cp':self.principal_cp,'total_dividends_cp':self.total_dividends_cp}


class NobleDecisionLedger(db.Model):
    id=db.Column(db.Integer,primary_key=True);family_id=db.Column(db.Integer,db.ForeignKey('noble_family.id',ondelete='CASCADE'),nullable=False,index=True)
    day_index=db.Column(db.Integer,nullable=False);decision_type=db.Column(db.String(50),nullable=False);business_id=db.Column(db.Integer,db.ForeignKey('settlement_business.id'),nullable=True)
    amount_cp=db.Column(db.Integer,nullable=False,default=0);summary=db.Column(db.Text,nullable=False)
  
class Page(db.Model):
    __table_args__ = (
        UniqueConstraint('wiki_id', 'title', name='uq_page_wiki_id_title'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=True)
    wiki_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    wiki = db.relationship(
        'Campaign',
        backref=db.backref('pages', lazy=True, cascade='all, delete-orphan')
    )
    tsv = db.Column(TSVECTOR)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'wiki_id': self.wiki_id,
        }


def seed_module_wiki_pages(campaign, module_name, existing_titles=None):
    """Add a module's non-main wiki pages without duplicating campaign titles."""
    if existing_titles is None:
        existing_titles = {
            page.title for page in Page.query.filter_by(wiki_id=campaign.id).all()
        } if campaign.id else set()
    seeded_titles = set(existing_titles)
    added = 0
    module_pages = GameElement.query.filter_by(module=module_name, element_type='wiki').all()
    for module_page in module_pages:
        page_data = module_page.data or {}
        title = page_data.get('title') or module_page.name
        content = page_data.get('content', '')
        normalized_title = title.strip() if isinstance(title, str) else ''
        if not normalized_title or normalized_title == 'Main Page' or normalized_title in seeded_titles:
            continue
        seeded_titles.add(normalized_title)
        db.session.add(Page(title=normalized_title, content=content, wiki=campaign))
        added += 1
    return added


def seed_campaign_wiki(campaign, module_name=None):
    """Attach initial module wiki pages and exactly one Main Page."""
    if module_name:
        seed_module_wiki_pages(campaign, module_name, existing_titles=set())
        main_page_content = f"This campaign is using the {module_name} module."
    else:
        main_page_content = campaign.description or "Welcome to the campaign!"

    db.session.add(Page(
        title='Main Page',
        content=main_page_content,
        wiki=campaign
    ))


class Revisions(db.Model):
    revision_id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('page.id'), nullable=False)
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('revisions', lazy=True))
    page = db.relationship('Page', backref='revisions')

# Loot association table
loot_box_items = db.Table('loot_box_items',
    db.Column('itemID', db.Integer, db.ForeignKey('item.id'), primary_key=True),
    db.Column('loot_boxID', db.Integer, db.ForeignKey('loot_box.id'), primary_key=True),
    db.Column('quantity', db.Integer)
)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(80), nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(80), nullable=False)
    weight = db.Column(Numeric(10, 2))  # Changed to Numeric with precision and scale
    description = db.Column(db.Text)

    # The relationships
    armor = db.relationship('Armor', backref='item', cascade='all, delete-orphan')
    weapon = db.relationship('Weapon', backref='item', cascade='all, delete-orphan')
    spellItem = db.relationship('SpellItem', backref='item', cascade='all, delete-orphan')
    mountVehicle = db.relationship('MountVehicle', backref='item', cascade='all, delete-orphan')
    loot_boxes = db.relationship('LootBox', secondary=loot_box_items, backref=db.backref('items'), lazy=True)


    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'cost': self.cost,
            'currency': self.currency,
            'weight': self.weight,
            'description': self.description
        }

class Weapon(db.Model):
    itemID = db.Column(db.Integer, db.ForeignKey('item.id'), primary_key=True)
    weapon_type = db.Column(db.String(20), nullable=False)
    damage = db.Column(db.String(20), nullable=False)
    damage_type = db.Column(db.String(20), nullable=False)
    weapon_range = db.Column(db.Integer)

    def to_dict(self):
        return {
            'weapon_type': self.weapon_type,
            'damage': self.damage,
            'damage_type': self.damage_type,
            'weapon_range': self.weapon_range,
        }

class Armor(db.Model):
    itemID = db.Column(db.Integer, db.ForeignKey('item.id'), primary_key=True)
    armor_class = db.Column(db.Integer, nullable=False)
    armor_type = db.Column(db.String(20), nullable=False)
    strength_needed = db.Column(db.Integer)
    stealth_disadvantage = db.Column(db.Boolean)

    def to_dict(self):
        return {
            'armor_class': self.armor_class,
            'armor_type': self.armor_type,
            'strength_needed': self.strength_needed,
            'stealth_disadvantage': self.stealth_disadvantage,
        }

class Spell(db.Model):
    __tablename__ = 'spells'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    level = db.Column(db.String(80), nullable=False)
    casting_time = db.Column(db.String(80), nullable=False)
    range = db.Column(db.String(80), nullable=False)
    components = db.Column(db.String(80), nullable=False)
    duration = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    classes = db.Column(db.String(80), nullable=False)
    school = db.Column(db.String(80), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'Name': self.name,
            'Level': self.level,
            'casting_time': self.casting_time,
            'Range': self.range,
            'Components': self.components.split(","),
            'Duration': self.duration,
            'Description': self.description,
            'Classes': self.classes.split(","),
            'School': self.school
        }

class SpellItem(db.Model):
    __tablename__ = 'spell_items'

    itemID = db.Column(db.Integer, db.ForeignKey('item.id'), primary_key=True)
    charges = db.Column(db.Integer)
    spell_id = db.Column(db.Integer, db.ForeignKey('spells.id'), nullable=True)  # Allow spell items without an associated spell


    def to_dict(self):
        return {
            'id': self.id,
            'charges': self.charges,
        }

class MountVehicle(db.Model):
    itemID = db.Column(db.Integer, db.ForeignKey('item.id'), primary_key=True)
    speed = db.Column(db.Integer, nullable=False)
    speed_unit = db.Column(db.String(20), nullable=False)
    capacity = db.Column(db.Integer, nullable=True)
    vehicle_type = db.Column(db.String(20), nullable=False)

    def to_dict(self):
        return {
            'speed': self.speed,
            'speed_unit': self.speed_unit,
            'capacity': self.capacity,
            'vehicle_type': self.vehicle_type
        }


class InventoryItem(db.Model):
    __tablename__ = 'inventory'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    characterID = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)
    itemID = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    equipped = db.Column(db.Boolean)

    # Relationship to the Item table
    item = db.relationship('Item', backref='inventory_items')

    def to_dict(self):
        item_dict = {
            'id': self.id,
            'name': self.name,
            'itemID': self.itemID,
            'quantity': self.quantity,
            'equipped': self.equipped,
            'type': self.item.type,
            'description': self.item.description,
        }

        # If the item is a weapon, include the damage details
        if self.item.type == 'Weapon' and self.item.weapon:
            item_dict['weaponType'] = self.item.weapon[0].weapon_type
            item_dict['damage'] = self.item.weapon[0].damage
            item_dict['damageType'] = self.item.weapon[0].damage_type
            item_dict['range'] = self.item.weapon[0].weapon_range

        # If the item is armor, include the armor class details
        if self.item.type == 'Armor' and self.item.armor:
            item_dict['AC'] = self.item.armor[0].armor_class
            item_dict['armorType'] = self.item.armor[0].armor_type

        return item_dict

class Spellbook(db.Model):
    __tablename__ = 'spellbook'

    id = db.Column(db.Integer, primary_key=True)
    characterID = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)
    spell_id = db.Column(db.Integer, db.ForeignKey('spells.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    equipped = db.Column(db.Boolean)

    # Relationship to the Spell table
    spell = db.relationship('Spell', backref='spellbook_items')

    def to_dict(self):
        return {
            'id': self.id,
            'characterID': self.characterID,
            'SpellID': self.spell_id,
            'Quantity': self.quantity,
            'Name': self.spell.name,
            'Level': self.spell.level,
            'casting_time': self.spell.casting_time,
            'Range': self.spell.range,
            'Components': self.spell.components.split(","),
            'Duration': self.spell.duration,
            'Description': self.spell.description,
            'Classes': self.spell.classes.split(","),
            'School': self.spell.school,
            'equipped': self.equipped,
        }

class Journal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    userID = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    campaignID = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    characterID = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=True)
    title = db.Column(db.String(100), nullable=False)
    entry = db.Column(db.Text, nullable=False)
    date_created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_modified = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    calendar_id = db.Column(db.Integer, db.ForeignKey('calendar.id'), nullable=True)
    journal_year = db.Column(db.Integer, nullable=True)
    journal_month_index = db.Column(db.Integer, nullable=True)
    journal_day = db.Column(db.Integer, nullable=True)
    journal_hour = db.Column(db.Integer, nullable=True)
    journal_minute = db.Column(db.Integer, nullable=True)

    calendar = db.relationship('Calendar', lazy=True)

    def get_journal_date_display(self):
        if self.journal_year is None or self.journal_month_index is None or self.journal_day is None:
            return None

        if not self.calendar:
            return f"Year {self.journal_year}, Month {self.journal_month_index + 1}, Day {self.journal_day}"

        format_data = self.calendar.get_format_data() if hasattr(self.calendar, 'get_format_data') else {}
        months = format_data.get('months', [])

        month_name = None
        month_subtitle = None
        if 0 <= self.journal_month_index < len(months):
            month_name = months[self.journal_month_index].get('name')
            month_subtitle = months[self.journal_month_index].get('subtitle')

        if month_name:
            if month_subtitle:
                return f"{month_name} ({month_subtitle}) {self.journal_day}, Year {self.journal_year}"
            return f"{month_name} {self.journal_day}, Year {self.journal_year}"

        return f"Year {self.journal_year}, Month {self.journal_month_index + 1}, Day {self.journal_day}"

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.entry,
            'date_created': self.date_created.isoformat(),
            'date_modified': self.date_modified.isoformat(),
            'journal_date': {
                'calendar_id': self.calendar_id,
                'year': self.journal_year,
                'month_index': self.journal_month_index,
                'day': self.journal_day,
                'hour': self.journal_hour,
                'minute': self.journal_minute,
            } if self.journal_year is not None else None,
            'journal_date_display': self.get_journal_date_display(),
        }

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_ids = db.Column(db.String, nullable=False)  # This would be a comma-separated string of IDs.
    group_id = db.Column(db.String, nullable=False)  # New field: group_id
    message_type = db.Column(db.String(50), nullable=False)  # e.g. 'item_transfer', 'chat', etc.
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    item = db.relationship('Item', backref='messages', lazy=True)  # Add for ORM relationship
    message_text = db.Column(db.Text, nullable=False)  # The actual message text.
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'sender_id': self.sender_id,
            'group_id': self.group_id,
            'recipient_ids': self.recipient_ids.split(','),
            'message_type': self.message_type,
            'item_id': self.item_id,
            'message_text': self.message_text,
            'timestamp': self.timestamp.isoformat(),
        }


class NPC(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    size = db.Column(db.String(20), nullable=False)  # Example: "Medium"
    creature_type = db.Column(db.String(50), nullable=False)  # Example: "humanoid"
    creature_subtype = db.Column(db.String(50), nullable=True)  # Example: "goblinoid"
    alignment = db.Column(db.String(50), nullable=False)  # Example: "chaotic evil"
    
    ac = db.Column(db.String(50), nullable=False)  # Armor Class
    hp = db.Column(db.String(50), nullable=False)  # Hit Points
    speed = db.Column(db.Integer, nullable=False)  # Speed (in feet)
    
    # Stats
    strength = db.Column(db.Integer, nullable=False)
    dexterity = db.Column(db.Integer, nullable=False)
    constitution = db.Column(db.Integer, nullable=False)
    intelligence = db.Column(db.Integer, nullable=False)
    wisdom = db.Column(db.Integer, nullable=False)
    charisma = db.Column(db.Integer, nullable=False)
    
    # Skills and Senses
    saving_throws = db.Column(db.String(120), nullable=True)  # Example: "Int +5, Wis +3"
    skills = db.Column(db.String(120), nullable=True)  # Example: "Stealth +6, Survival +2"
    immunities = db.Column(db.String(120), nullable=True)
    resistance = db.Column(db.String(120), nullable=True)
    senses = db.Column(db.String(120), nullable=True)  # Example: "darkvision 60 ft, passive Perception 10"
    languages = db.Column(db.String(120), nullable=True)  # Example: "Common, Goblin"
    challenge = db.Column(db.String(50), nullable=True)  # Challenge Rating and XP

    # Traits
    traits = db.Column(db.String(1000), nullable=True)  # Example: "Brute, Surprise Attack"
    
    # Actions (simple example with a single attack, but can be more complex)
    actions = db.Column(db.String(1000), nullable=True)  # Example: "Morningstar: +4 to hit, 11 (2d8+2) piercing damage"

    description = db.Column(db.Text, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'name': self.name,
            'size': self.size,
            'creature_type': self.creature_type,
            'creature_subtype': self.creature_subtype,
            'alignment': self.alignment,
            'ac': self.ac,
            'hp': self.hp,
            'speed': self.speed,
            'strength': self.strength,
            'dexterity': self.dexterity,
            'constitution': self.constitution,
            'intelligence': self.intelligence,
            'wisdom': self.wisdom,
            'charisma': self.charisma,
            'saving_throws': self.saving_throws,
            'skills': self.skills,
            'immunities': self.immunities,
            'resistance': self.resistance,
            'senses': self.senses,
            'languages': self.languages,
            'challenge': self.challenge,
            'traits': self.traits,
            'actions': self.actions,
            'description': self.description,
        }

class GameElement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    system = db.Column(db.String(50))  # e.g., 'D&D 5e', 'pathfinder'
    element_type = db.Column(db.String(50))  # e.g., 'class', 'race', 'character_background', 'character_sheet', 'NPC_jobs'
    module = db.Column(db.String(50), nullable=True)  # Specific module, if applicable
    setting = db.Column(db.String(50), nullable=True)  # Specific setting, if applicable
    name = db.Column(db.String(50), unique=True)
    data = db.Column(JSONB)

    def __repr__(self):
        return f'<GameElement {self.element_type} {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'system': self.system,
            'element_type': self.element_type,
            'module': self.module,
            'setting': self.setting,
            'name': self.name,
            'data': self.data,
        }

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)  # Use LargeBinary for binary data
    mimetype = db.Column(db.String(50), nullable=False)  # Store the MIME type
    campaignID = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)  # Add campaignID column


class SoundAsset(db.Model):
    __tablename__ = 'sound_asset'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    filename = db.Column(db.String(255), nullable=False, unique=True)
    original_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(20), nullable=False, default='music', server_default='music')
    cover_filename = db.Column(db.String(255))
    cover_mimetype = db.Column(db.String(100))
    duration_seconds = db.Column(db.Float)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    uploaded_by = db.relationship('User', backref='sound_assets')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'mimetype': self.mimetype,
            'originalFilename': self.original_filename,
            'url': f'/media/sounds/{self.filename}',
            'coverUrl': f'/media/sounds/covers/{self.cover_filename}' if self.cover_filename else None,
            'durationSeconds': self.duration_seconds,
            'uploadedBy': self.uploaded_by.username if self.uploaded_by else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }


class SoundPlaylist(db.Model):
    __tablename__ = 'sound_playlist'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    shuffle = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    tracks = db.relationship(
        'SoundPlaylistTrack',
        cascade='all, delete-orphan',
        order_by='SoundPlaylistTrack.position',
        back_populates='playlist',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'shuffle': self.shuffle,
            'tracks': [entry.sound_asset.to_dict() for entry in self.tracks if entry.sound_asset],
        }


class SoundPlaylistTrack(db.Model):
    __tablename__ = 'sound_playlist_track'

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('sound_playlist.id', ondelete='CASCADE'), nullable=False, index=True)
    sound_asset_id = db.Column(db.Integer, db.ForeignKey('sound_asset.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    playlist = db.relationship('SoundPlaylist', back_populates='tracks')
    sound_asset = db.relationship('SoundAsset')

    __table_args__ = (
        db.UniqueConstraint('playlist_id', 'sound_asset_id', name='uq_sound_playlist_track_asset'),
    )


class SoundQuickEffectSlot(db.Model):
    __tablename__ = 'sound_quick_effect_slot'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=False, index=True)
    slot = db.Column(db.Integer, nullable=False)
    sound_asset_id = db.Column(db.Integer, db.ForeignKey('sound_asset.id', ondelete='SET NULL'), nullable=True)
    sound_asset = db.relationship('SoundAsset')

    __table_args__ = (
        db.UniqueConstraint('campaign_id', 'slot', name='uq_sound_quick_effect_campaign_slot'),
        db.CheckConstraint('slot >= 1 AND slot <= 6', name='ck_sound_quick_effect_slot_range'),
    )

    def to_dict(self):
        return {'slot': self.slot, 'sound': self.sound_asset.to_dict() if self.sound_asset else None}


class LootBox(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False) ## Which lootbox the item is in
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=True, index=True)
    system = db.Column(db.String(50), nullable=True, index=True)
    module_key = db.Column(db.String(120), nullable=True, index=True)
    is_preset = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'campaign_id': self.campaign_id,
            'system': self.system,
            'module_key': self.module_key,
            'is_preset': self.is_preset,
            'editable': not self.is_preset,
            'scope': 'module_preset' if self.is_preset and self.module_key else ('system_preset' if self.is_preset else 'campaign'),
        }

class RandomTable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # Table Name
    description = db.Column(db.Text, nullable=True)  # Optional description of table
    dice_type = db.Column(db.String(20), nullable=False)  # Example: "1d100"
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=True, index=True)
    system = db.Column(db.String(50), nullable=True, index=True)
    module_key = db.Column(db.String(120), nullable=True, index=True)
    is_preset = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    table_entries = db.relationship('TableEntry', backref='random_table', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'dice_type': self.dice_type,
            'campaign_id': self.campaign_id,
            'system': self.system,
            'module_key': self.module_key,
            'is_preset': self.is_preset,
            'editable': not self.is_preset,
            'scope': 'module_preset' if self.is_preset and self.module_key else ('system_preset' if self.is_preset else 'campaign'),
            'table_entries': [entry.to_dict() for entry in self.table_entries]
        }

class TableEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('random_table.id'), nullable=False)
    min_roll = db.Column(db.Integer, nullable=False)  # Minimum roll value for this entry
    max_roll = db.Column(db.Integer, nullable=True)  # Maximum roll value for this entry
    result = db.Column(db.Text, nullable=False)  # The result of the roll

    def to_dict(self):
        return {
            'id': self.id,
            'table_id': self.table_id,
            'min_roll': self.min_roll,
            'max_roll': self.max_roll,
            'result': self.result
        }

class Calendar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)

    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)

    # Reusable calendar template
    format_id = db.Column(db.Integer, db.ForeignKey('game_element.id'), nullable=False)

    # Optional display/cache field if you want it
    format_slug = db.Column(db.String(50), nullable=True)

    current_year = db.Column(db.Integer, nullable=False, default=1)
    current_month_index = db.Column(db.Integer, nullable=False, default=0)
    current_day = db.Column(db.Integer, nullable=False, default=1)
    current_hour = db.Column(db.Integer, nullable=False, default=0)
    current_minute = db.Column(db.Integer, nullable=False, default=0)

    epoch_year = db.Column(db.Integer, nullable=True, default=1)
    epoch_month_index = db.Column(db.Integer, nullable=True, default=0)
    epoch_day = db.Column(db.Integer, nullable=True, default=1)

    format_element = db.relationship('GameElement', backref='calendars', lazy=True)

    events = db.relationship(
        'CalendarEvent',
        backref='calendar',
        lazy=True,
        cascade='all, delete-orphan'
    )

    def get_format_data(self):
        return (self.format_element.data if self.format_element else {}) or {}

    def get_hours_in_day(self):
        format_data = self.get_format_data()
        return format_data.get('hours_per_day', 24)

    def get_minutes_in_hour(self):
        format_data = self.get_format_data()
        return format_data.get('minutes_per_hour', 60)

    def get_time_period(self, hour=None):
        format_data = self.get_format_data()
        periods = format_data.get('time_periods', [])

        if hour is None:
            hour = self.current_hour

        for period in periods:
            start_hour = period.get('start_hour', 0)
            end_hour = period.get('end_hour', 0)

            if start_hour <= end_hour:
                if start_hour <= hour < end_hour:
                    return period['name']
            else:
                if hour >= start_hour or hour < end_hour:
                    return period['name']

        return None

    def to_dict(self):
        format_data = self.get_format_data()
        months = format_data.get('months', [])
        weekdays = format_data.get('weekdays', [])
        moons = format_data.get('moons', [])
        holidays = format_data.get('holidays', [])

        current_month = None
        if 0 <= self.current_month_index < len(months):
            current_month = months[self.current_month_index]

        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'campaign_id': self.campaign_id,
            'format': {
                'id': self.format_element.id if self.format_element else None,
                'name': self.format_element.name if self.format_element else None,
                'slug': self.format_slug,
                'display_name': format_data.get('display_name'),
            },
            'current_date': {
                'year': self.current_year,
                'month_index': self.current_month_index,
                'month_name': current_month.get('name') if current_month else None,
                'month_subtitle': current_month.get('subtitle') if current_month else None,
                'day': self.current_day,
                'hour': self.current_hour,
                'minute': self.current_minute,
            },
            'time_period': self.get_time_period(),
            'hours_in_day': self.get_hours_in_day(),
            'minutes_in_hour': self.get_minutes_in_hour(),
            'months': months,
            'days': weekdays,
            'moons': moons,
            'holidays': holidays,
            'events': [event.to_dict() for event in self.events],
        }


class CalendarEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    calendar_id = db.Column(db.Integer, db.ForeignKey('calendar.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    color = db.Column(db.String(20), nullable=True)

    start_year = db.Column(db.Integer, nullable=False)
    start_month_index = db.Column(db.Integer, nullable=False)
    start_day = db.Column(db.Integer, nullable=False)
    start_hour = db.Column(db.Integer, nullable=True)
    start_minute = db.Column(db.Integer, nullable=True)

    is_player_visible = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'calendar_id': self.calendar_id,
            'name': self.name,
            'description': self.description,
            'color': self.color,
            'year': self.start_year,
            'month_index': self.start_month_index,
            'day': self.start_day,
            'hour': self.start_hour,
            'minute': self.start_minute,
            'is_player_visible': self.is_player_visible,
        }


def ensure_module_calendar(campaign, definition, strategy='keep_current'):
    """Create or reconcile the campaign calendar for an installed module."""
    calendar_config = definition.get('calendar') or {}
    if not calendar_config:
        return Calendar.query.filter_by(campaign_id=campaign.id).first()

    format_element = GameElement.query.filter_by(
        element_type='calendar_format',
        name=calendar_config['name'],
    ).first()
    if not format_element:
        calendar_path = Path(app.root_path) / calendar_config['filename']
        with calendar_path.open('r', encoding='utf-8') as calendar_file:
            format_data = json.load(calendar_file)
        format_element = GameElement(
            system=definition.get('system'),
            element_type='calendar_format',
            module=None,
            setting=definition.get('setting_name'),
            name=calendar_config['name'],
            data=format_data,
        )
        db.session.add(format_element)
        db.session.flush()

    calendar = Calendar.query.filter_by(campaign_id=campaign.id).first()
    if not calendar:
        calendar = Calendar(
            name=f"{campaign.name} In-World Calendar",
            description=f"{definition['setting_name']} calendar for {campaign.name}",
            campaign_id=campaign.id,
            format_id=format_element.id,
            format_slug=calendar_config['slug'],
            current_year=definition.get('starting_year') or 1,
            current_month_index=calendar_config.get('starting_month_index', 0),
            current_day=calendar_config.get('starting_day', 1),
            current_hour=0,
            current_minute=0,
            epoch_year=1,
            epoch_month_index=0,
            epoch_day=1,
        )
        db.session.add(calendar)
        return calendar

    if strategy == 'use_module':
        calendar.format_id = format_element.id
        calendar.format_slug = calendar_config['slug']
        if definition.get('starting_year') is not None:
            calendar.current_year = definition['starting_year']
    return calendar


def _merge_template_records(existing, incoming):
    existing = list(existing or [])
    known = {str(record.get('id')) for record in existing if record.get('id') is not None}
    return [*existing, *(record for record in (incoming or []) if str(record.get('id')) not in known)]


def import_module_settlement(campaign, template, strategy):
    """Import, merge, retain, or replace a module settlement map."""
    template = persist_reference_layer_media(campaign.id, template)
    locations = WorldAtlasLocation.query.filter_by(campaign_id=campaign.id).all()
    incoming_name = template['name'].strip().casefold()
    location = next(
        (value for value in locations if value.map_key == template['map_key'] or value.name.strip().casefold() == incoming_name),
        None,
    )
    if not location:
        location = WorldAtlasLocation(
            campaign_id=campaign.id,
            name=template['name'],
            map_key=template['map_key'],
            settlement_type=template['settlement_type'],
            notes=template.get('notes'),
            atlas_x=template.get('atlas_x'),
            atlas_y=template.get('atlas_y'),
            is_primary=not locations,
            terrain_strokes=template.get('terrain_strokes', []),
            roads=template.get('roads', []),
            water_bodies=template.get('water_bodies', []),
            buildings=template.get('buildings', []),
            reference_layers=template.get('reference_layers', []),
            environment=template.get('environment', {}),
        )
        db.session.add(location)
        db.session.flush()
        result = 'created'
    elif strategy == 'keep':
        return location, 'kept'
    elif strategy == 'override':
        previous_map_key = location.map_key
        location.settlement_type = template['settlement_type']
        location.notes = template.get('notes')
        if template.get('atlas_x') is not None:
            location.atlas_x = template['atlas_x']
            location.atlas_y = template.get('atlas_y')
        location.terrain_strokes = template.get('terrain_strokes', [])
        location.roads = template.get('roads', [])
        location.water_bodies = template.get('water_bodies', [])
        location.buildings = template.get('buildings', [])
        location.reference_layers = template.get('reference_layers', [])
        location.environment = template.get('environment', {})
        for point in MapPointOfInterest.query.filter_by(campaign_id=campaign.id, map_key=previous_map_key).all():
            db.session.delete(point)
        location.map_key = template['map_key']
        party_position = PartyMapPosition.query.filter_by(campaign_id=campaign.id, map_key=previous_map_key).first()
        if party_position:
            party_position.map_key = location.map_key
        result = 'overridden'
    else:
        location.terrain_strokes = _merge_template_records(location.terrain_strokes, template.get('terrain_strokes'))
        location.roads = _merge_template_records(location.roads, template.get('roads'))
        location.water_bodies = _merge_template_records(location.water_bodies, template.get('water_bodies'))
        location.buildings = _merge_template_records(location.buildings, template.get('buildings'))
        location.reference_layers = _merge_template_records(location.reference_layers, template.get('reference_layers'))
        if template.get('environment'):
            current_environment = dict(location.environment or {})
            template_environment = template['environment']
            current_environment.update({key: value for key, value in template_environment.items() if key not in {'regions', 'fortifications'}})
            current_environment['regions'] = _merge_template_records(current_environment.get('regions'), template_environment.get('regions'))
            current_environment['fortifications'] = _merge_template_records(current_environment.get('fortifications'), template_environment.get('fortifications'))
            location.environment = current_environment
        result = 'merged'

    existing_points = {
        point.name.strip().casefold()
        for point in MapPointOfInterest.query.filter_by(campaign_id=campaign.id, map_key=location.map_key).all()
    }
    for point in template.get('points_of_interest', []):
        if point['name'].strip().casefold() in existing_points:
            continue
        db.session.add(MapPointOfInterest(
            campaign_id=campaign.id, map_key=location.map_key, name=point['name'],
            point_type=point.get('point_type', 'landmark'), x=point['x'], y=point['y'],
            elevation=point.get('elevation', 0), water_access=point.get('water_access', False),
            road_access=point.get('road_access', True),
        ))
    location.updated_at = datetime.now(timezone.utc)
    return location, result


def record_module_installation(campaign, definition, user_id, settlement_strategy, calendar_strategy):
    installation = CampaignModuleInstallation(
        campaign_id=campaign.id,
        module_key=definition['key'],
        module_name=definition['name'],
        setting_key=definition.get('setting_key'),
        starting_year=definition.get('starting_year'),
        installed_by_id=user_id,
        settlement_strategy=settlement_strategy,
        calendar_strategy=calendar_strategy,
    )
    db.session.add(installation)
    return installation


NPC_RECORD_FIELDS = {
    'name', 'size', 'creature_type', 'creature_subtype', 'alignment', 'ac', 'hp',
    'speed', 'strength', 'dexterity', 'constitution', 'intelligence', 'wisdom',
    'charisma', 'saving_throws', 'skills', 'immunities', 'resistance', 'senses',
    'languages', 'challenge', 'traits', 'actions', 'description',
}


def npc_from_record(campaign_id, record):
    """Build an NPC model from either a generated or module preset record."""
    values = {key: record.get(key) for key in NPC_RECORD_FIELDS}
    return NPC(campaign_id=campaign_id, **values)


def seed_module_npcs(campaign, definition):
    """Merge a module's named NPCs into the campaign library by stable name."""
    presets = module_npc_presets(definition.get('key'))
    if not presets:
        return []
    existing_names = {
        npc.name.strip().casefold()
        for npc in NPC.query.filter_by(campaign_id=campaign.id).all()
    }
    added = []
    for preset in presets:
        normalized_name = preset['name'].strip().casefold()
        if normalized_name in existing_names:
            continue
        npc = npc_from_record(campaign.id, preset)
        db.session.add(npc)
        added.append(npc)
        existing_names.add(normalized_name)
    return added


## Add all the models to the admin console
admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(Character, db.session))
admin.add_view(ModelView(Campaign, db.session))
admin.add_view(ModelView(CampaignModuleInstallation, db.session))
admin.add_view(ModelView(Page, db.session))
admin.add_view(ModelView(Revisions, db.session))
admin.add_view(ModelView(Item, db.session))
admin.add_view(ModelView(InventoryItem, db.session))
admin.add_view(ModelView(Spell, db.session))
admin.add_view(ModelView(SpellItem, db.session))
admin.add_view(ModelView(MountVehicle, db.session))
admin.add_view(ModelView(Armor, db.session))
admin.add_view(ModelView(Weapon, db.session))
admin.add_view(ModelView(Journal, db.session))
admin.add_view(ModelView(Message, db.session))
admin.add_view(ModelView(LootBox, db.session))
admin.add_view(ModelView(NPC, db.session))
admin.add_view(ModelView(GameElement, db.session))
admin.add_view(ModelView(Document, db.session))
admin.add_view(ModelView(SoundAsset, db.session))
admin.add_view(ModelView(SoundPlaylist, db.session))
admin.add_view(ModelView(SoundQuickEffectSlot, db.session))
admin.add_view(ModelView(RandomTable, db.session))
admin.add_view(ModelView(Calendar, db.session))
admin.add_view(ModelView(CalendarEvent, db.session))

from flask.cli import with_appcontext
import click

## Avatar handling utilities
from pathlib import Path
from uuid import uuid4
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

# Large cartographic references are retained at source resolution. Viewer-safe
# derivatives are generated after validation instead of rejecting useful maps.
Image.MAX_IMAGE_PIXELS = 300_000_000

BASE_DIR = Path(app.root_path).resolve()
MEDIA_ROOT = BASE_DIR / "media"
AVATAR_ROOT = MEDIA_ROOT / "avatars"
AVATAR_UPLOAD_ROOT = AVATAR_ROOT / "uploads"
AVATAR_DEFAULT_ROOT = AVATAR_ROOT / "defaults"
CAMPAIGN_ICON_ROOT = MEDIA_ROOT / "campaign-icons"
MAP_REFERENCE_ROOT = MEDIA_ROOT / "maps"
SOUND_ROOT = MEDIA_ROOT / "sounds"

app.config["MEDIA_ROOT"] = str(MEDIA_ROOT)
app.config["AVATAR_ROOT"] = str(AVATAR_ROOT)
app.config["AVATAR_UPLOAD_ROOT"] = str(AVATAR_UPLOAD_ROOT)
app.config["CAMPAIGN_ICON_ROOT"] = str(CAMPAIGN_ICON_ROOT)


def store_map_media_asset(campaign_id, data, filename, mimetype=None, purpose='map_reference', name=None,
                          pixel_width=None, pixel_height=None):
    """Store map bytes once per campaign and return an opaque database URL."""
    digest = hashlib.sha256(data).hexdigest()
    existing = MapMediaAsset.query.filter_by(campaign_id=campaign_id, sha256=digest, purpose=purpose).first()
    if existing:
        return existing
    asset = MapMediaAsset(
        public_id=uuid4().hex, campaign_id=campaign_id, purpose=purpose,
        name=(name or Path(filename).stem)[:160], original_filename=Path(filename).name[:255],
        mimetype=(mimetype or mimetypes.guess_type(filename)[0] or 'application/octet-stream')[:100],
        byte_size=len(data), sha256=digest, pixel_width=pixel_width, pixel_height=pixel_height, data=data,
    )
    db.session.add(asset)
    db.session.flush()
    return asset


def persist_reference_layer_media(campaign_id, template):
    """Copy packaged/legacy map rasters into PostgreSQL and rewrite their URLs."""
    payload = json.loads(json.dumps(template))
    for layer in payload.get('reference_layers', []):
        for field in ('image_url', 'original_image_url', 'source_image_url'):
            current = layer.get(field)
            if not isinstance(current, str) or not current.startswith('/media/'):
                continue
            source_path = MEDIA_ROOT / current.removeprefix('/media/')
            is_module_asset = '/modules/' in current
            purpose = 'module_map' if is_module_asset else 'map_reference'
            asset_campaign_id = None if is_module_asset else campaign_id
            if source_path.is_file():
                asset = store_map_media_asset(
                    asset_campaign_id, source_path.read_bytes(), source_path.name, purpose=purpose,
                    name=layer.get('name'), pixel_width=layer.get('pixel_width'), pixel_height=layer.get('pixel_height'),
                )
            else:
                asset = MapMediaAsset.query.filter_by(
                    campaign_id=asset_campaign_id, original_filename=source_path.name, purpose=purpose
                ).first()
                if not asset:
                    app.logger.warning('Map media source is missing and could not be imported: %s', source_path)
                    continue
            layer[field] = asset.content_url
            layer[f'{field}_asset_id'] = asset.id
            if layer.get('layer_type') == 'heightmap' and not layer.get('values'):
                try:
                    with Image.open(io.BytesIO(asset.data)) as source:
                        sampled = source.convert('L').resize((128, 128), Image.Resampling.LANCZOS)
                        layer['values'] = list(sampled.tobytes())
                        layer['grid_width'] = 128
                        layer['grid_height'] = 128
                except Exception:
                    app.logger.exception('Unable to sample database-backed heightmap %s', asset.id)
    return payload
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_MAP_REFERENCE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_SOUND_EXTENSIONS = {"mp3", "wav", "ogg", "m4a", "aac", "webm", "flac"}
MAX_SOUND_UPLOAD_BYTES = 1024 * 1024 * 1024
LOSSLESS_SOUND_EXTENSIONS = {'wav', 'flac'}

CHARACTER_AVATAR_PRESETS = [
    {'key': 'barbarian', 'name': 'Barbarian', 'url': '/avatars/barbarian.webp'},
    {'key': 'bard', 'name': 'Bard', 'url': '/avatars/bard.webp'},
    {'key': 'cleric', 'name': 'Cleric', 'url': '/avatars/clerid.webp'},
    {'key': 'druid', 'name': 'Druid', 'url': '/avatars/druid.webp'},
    {'key': 'fighter', 'name': 'Fighter', 'url': '/avatars/fighter.webp'},
    {'key': 'knight', 'name': 'Knight', 'url': '/avatars/knight.webp'},
    {'key': 'monk', 'name': 'Monk', 'url': '/avatars/monk.webp'},
    {'key': 'paladin', 'name': 'Paladin', 'url': '/avatars/paladin.webp'},
    {'key': 'ranger', 'name': 'Ranger', 'url': '/avatars/ranger.webp'},
    {'key': 'rogue', 'name': 'Rogue', 'url': '/avatars/rogue.webp'},
    {'key': 'sorcerer', 'name': 'Sorcerer', 'url': '/avatars/sorcerer.webp'},
    {'key': 'warlock', 'name': 'Warlock', 'url': '/avatars/warlock.webp'},
    {'key': 'wizard', 'name': 'Wizard', 'url': '/avatars/wizard.webp'},
]

CAMPAIGN_ICON_PRESETS = [
    {'key': 'world-turtle', 'name': 'World Turtle', 'url': '/sea_turtle_icon_512.png'},
    {'key': 'neverwinter', 'name': 'Neverwinter', 'url': '/Neverwinter.png'},
    {'key': 'dungeon-master', 'name': 'Dungeon Master', 'url': '/avatars/DM.webp'},
    {'key': 'knight', 'name': 'Knight', 'url': '/avatars/knight.webp'},
    {'key': 'wizard', 'name': 'Wizard', 'url': '/avatars/wizard.webp'},
    {'key': 'rogue', 'name': 'Rogue', 'url': '/avatars/rogue.webp'},
    {'key': 'druid', 'name': 'Druid', 'url': '/avatars/druid.webp'},
    {'key': 'bard', 'name': 'Bard', 'url': '/avatars/bard.webp'},
]


def character_avatar_preset(key):
    return next((preset for preset in CHARACTER_AVATAR_PRESETS if preset['key'] == key), None)


def campaign_icon_preset(key):
    return next((preset for preset in CAMPAIGN_ICON_PRESETS if preset['key'] == key), None)

def allowed_avatar_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS

def allowed_map_reference_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_MAP_REFERENCE_EXTENSIONS


def allowed_sound_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_SOUND_EXTENSIONS


def sound_library_user():
    user = User.query.filter_by(username=get_jwt_identity()).first()
    campaign_id = request.headers.get('CampaignID')
    campaign = Campaign.query.get(campaign_id) if campaign_id else None
    if not user or not campaign or user.id not in {campaign.dm_id, campaign.owner_id}:
        return None
    return user


def sound_library_context():
    user = User.query.filter_by(username=get_jwt_identity()).first()
    campaign_id = request.headers.get('CampaignID')
    campaign = Campaign.query.get(campaign_id) if campaign_id else None
    if not user or not campaign or user.id not in {campaign.dm_id, campaign.owner_id}:
        return None, None
    return user, campaign


def ensure_default_sound_playlists(user, campaign):
    if SoundPlaylist.query.filter_by(campaign_id=campaign.id).first():
        return
    db.session.add_all([
        SoundPlaylist(campaign_id=campaign.id, name='Traveling Music', shuffle=True, created_by_id=user.id),
        SoundPlaylist(campaign_id=campaign.id, name='Combat', shuffle=True, created_by_id=user.id),
    ])
    db.session.commit()


def serialized_quick_effect_slots(campaign_id):
    configured = {
        entry.slot: entry.to_dict()
        for entry in SoundQuickEffectSlot.query.filter_by(campaign_id=campaign_id).all()
    }
    return [configured.get(slot, {'slot': slot, 'sound': None}) for slot in range(1, 7)]


def sound_upload_error(message, code, status, filename=None):
    """Return a safe, machine-readable upload error for per-file UI feedback."""
    error = {'code': code}
    if filename:
        error['filename'] = secure_filename(filename)
    return jsonify({'message': message, 'error': error}), status


def extract_embedded_sound_cover(sound_path):
    """Return normalized embedded cover art when the audio container provides it."""
    try:
        from mutagen import File as MutagenFile
        from mutagen.flac import Picture
        from mutagen.id3 import APIC, ID3

        try:
            audio = MutagenFile(sound_path)
        except Exception:
            audio = None
        candidates = []
        candidates.extend(getattr(audio, 'pictures', []) or [])
        tags = getattr(audio, 'tags', None)
        if not tags and Path(sound_path).suffix.lower() == '.mp3':
            try:
                tags = ID3(sound_path)
            except Exception:
                tags = None
        if tags:
            candidates.extend(value for value in tags.values() if isinstance(value, APIC))
            covers = tags.get('covr') if hasattr(tags, 'get') else None
            if covers:
                candidates.extend(covers if isinstance(covers, (list, tuple)) else [covers])
            encoded_pictures = tags.get('metadata_block_picture') if hasattr(tags, 'get') else None
            for encoded in encoded_pictures or []:
                try:
                    picture = Picture(base64.b64decode(encoded))
                    candidates.append(picture)
                except Exception:
                    continue
        for candidate in candidates:
            image_bytes = bytes(getattr(candidate, 'data', candidate))
            if not image_bytes or len(image_bytes) > 15 * 1024 * 1024:
                continue
            try:
                with Image.open(io.BytesIO(image_bytes)) as cover:
                    cover.load()
                    cover.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
                    has_alpha = cover.mode in {'RGBA', 'LA'} or 'transparency' in cover.info
                    output = io.BytesIO()
                    if has_alpha:
                        cover.convert('RGBA').save(output, 'PNG', optimize=True)
                        return output.getvalue(), 'png', 'image/png'
                    cover.convert('RGB').save(output, 'JPEG', quality=90, optimize=True)
                    return output.getvalue(), 'jpg', 'image/jpeg'
            except Exception:
                continue
    except Exception:
        app.logger.info('No readable embedded cover art in %s', sound_path, exc_info=True)
    return None


def sound_duration_seconds(sound_path):
    """Read a track's duration without decoding the complete audio file."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(sound_path)
        duration = float(getattr(getattr(audio, 'info', None), 'length', 0) or 0)
        return round(duration, 3) if duration > 0 else None
    except Exception:
        app.logger.info('No readable duration metadata in %s', sound_path, exc_info=True)
        return None


class SoundTranscodeError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def transcode_sound_to_mp3(source_path, destination_path):
    """Convert a lossless upload to a compact, browser-streamable MP3."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SoundTranscodeError(
            'transcoder_unavailable',
            'Audio compression is not installed on this server. Install ffmpeg and try again.',
        )
    # Audio imports are background preparation work from the user's point of
    # view. Keep them from monopolizing a small Pi while maps and API requests
    # are being served. `nice` is optional so local development remains
    # portable; limiting ffmpeg to one worker is effective on every platform.
    command = [
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(source_path), '-map_metadata', '0', '-vn',
        '-codec:a', 'libmp3lame', '-b:a', '192k', '-threads', '1', str(destination_path),
    ]
    nice = shutil.which('nice')
    if nice:
        command = [nice, '-n', '10', *command]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=3600, check=False
        )
    except subprocess.TimeoutExpired as error:
        raise SoundTranscodeError('transcode_timeout', 'Audio compression took longer than one hour.') from error
    if completed.returncode or not destination_path.is_file() or destination_path.stat().st_size == 0:
        detail = (completed.stderr or '').strip().splitlines()
        app.logger.warning('ffmpeg could not transcode %s: %s', source_path.name, detail[-1] if detail else 'unknown error')
        raise SoundTranscodeError('transcode_failed', 'The server could not convert this audio file to MP3.')


@app.route('/api/sounds', methods=['GET', 'POST'])
@jwt_required()
def sounds():
    user = sound_library_user()
    if not user:
        return jsonify({'message': 'Only a campaign DM or owner may use the shared sound library'}), 403

    if request.method == 'GET':
        assets = SoundAsset.query.order_by(SoundAsset.category, SoundAsset.name).all()
        durations_updated = False
        for asset in assets:
            if asset.duration_seconds is None:
                asset.duration_seconds = sound_duration_seconds(SOUND_ROOT / asset.filename)
                durations_updated = durations_updated or asset.duration_seconds is not None
        if durations_updated:
            db.session.commit()
        return jsonify({'sounds': [asset.to_dict() for asset in assets]}), 200

    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return sound_upload_error('Choose an audio file to upload', 'missing_file', 400)
    if not allowed_sound_file(uploaded.filename):
        return sound_upload_error(
            'Unsupported format. Choose MP3, WAV, OGG, M4A, AAC, WebM, or FLAC audio.',
            'unsupported_format', 400, uploaded.filename,
        )
    mimetype = (uploaded.mimetype or '').lower()
    if mimetype and not (mimetype.startswith('audio/') or mimetype in {'application/ogg', 'application/octet-stream'}):
        return sound_upload_error(
            f'The browser identified this file as {mimetype}, not audio.',
            'invalid_mimetype', 400, uploaded.filename,
        )

    uploaded.stream.seek(0, 2)
    uploaded_size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    if uploaded_size == 0:
        return sound_upload_error('The selected audio file is empty.', 'empty_file', 400, uploaded.filename)
    if uploaded_size > MAX_SOUND_UPLOAD_BYTES:
        return sound_upload_error('The file is larger than the 1 GB upload limit.', 'file_too_large', 413, uploaded.filename)

    category = (request.form.get('category') or 'music').strip().lower()
    if category not in {'music', 'environment', 'sfx'}:
        return sound_upload_error('Sound category must be music, environment, or sfx.', 'invalid_category', 400, uploaded.filename)

    original_name = secure_filename(uploaded.filename)
    extension = original_name.rsplit('.', 1)[1].lower()
    display_name = (request.form.get('name') or Path(original_name).stem).strip()[:120]
    if not display_name:
        return sound_upload_error('A sound name is required.', 'missing_name', 400, uploaded.filename)

    SOUND_ROOT.mkdir(parents=True, exist_ok=True)
    should_transcode = extension in LOSSLESS_SOUND_EXTENSIONS
    stored_extension = 'mp3' if should_transcode else extension
    stored_mimetype = 'audio/mpeg' if should_transcode else uploaded.mimetype
    stored_filename = f'{uuid4().hex}.{stored_extension}'
    stored_path = SOUND_ROOT / stored_filename
    source_path = SOUND_ROOT / f'.{uuid4().hex}.upload.{extension}'
    try:
        uploaded.save(source_path)
    except (OSError, IOError):
        source_path.unlink(missing_ok=True)
        app.logger.exception('Unable to write uploaded sound %s', original_name)
        return sound_upload_error(
            'The server could not write this file to sound storage.',
            'storage_error', 500, uploaded.filename,
        )

    cover_filename = None
    cover_mimetype = None
    extracted_cover = extract_embedded_sound_cover(source_path)
    try:
        if should_transcode:
            transcode_sound_to_mp3(source_path, stored_path)
        else:
            source_path.replace(stored_path)
    except SoundTranscodeError as error:
        stored_path.unlink(missing_ok=True)
        return sound_upload_error(str(error), error.code, 422, uploaded.filename)
    except (OSError, IOError):
        stored_path.unlink(missing_ok=True)
        app.logger.exception('Unable to finalize uploaded sound %s', original_name)
        return sound_upload_error('The server could not finalize this audio file.', 'storage_error', 500, uploaded.filename)
    finally:
        source_path.unlink(missing_ok=True)

    if extracted_cover:
        cover_bytes, cover_extension, cover_mimetype = extracted_cover
        cover_root = SOUND_ROOT / 'covers'
        cover_root.mkdir(parents=True, exist_ok=True)
        cover_filename = f'{uuid4().hex}.{cover_extension}'
        try:
            (cover_root / cover_filename).write_bytes(cover_bytes)
        except (OSError, IOError):
            cover_filename = None
            cover_mimetype = None
            app.logger.warning('Audio uploaded, but embedded cover art could not be stored for %s', original_name)

    asset = SoundAsset(
        name=display_name,
        filename=stored_filename,
        original_filename=original_name,
        mimetype=stored_mimetype,
        category=category,
        cover_filename=cover_filename,
        cover_mimetype=cover_mimetype,
        duration_seconds=sound_duration_seconds(stored_path),
        uploaded_by_id=user.id,
    )
    try:
        db.session.add(asset)
        db.session.commit()
    except Exception:
        db.session.rollback()
        stored_path.unlink(missing_ok=True)
        if cover_filename:
            (SOUND_ROOT / 'covers' / cover_filename).unlink(missing_ok=True)
        app.logger.exception('Unable to record uploaded sound %s', original_name)
        return sound_upload_error(
            'The file reached the server, but its library record could not be saved.',
            'database_error', 500, uploaded.filename,
        )

    socketio.emit('sound_library_updated', {'action': 'created', 'sound': asset.to_dict()})
    return jsonify({'sound': asset.to_dict()}), 201


@app.route('/api/sound-playlists', methods=['GET', 'POST'])
@jwt_required()
def sound_playlists():
    user, campaign = sound_library_context()
    if not user:
        return jsonify({'message': 'Only a campaign DM or owner may manage playlists'}), 403

    if request.method == 'GET':
        ensure_default_sound_playlists(user, campaign)
        playlists = SoundPlaylist.query.filter_by(campaign_id=campaign.id).order_by(SoundPlaylist.name).all()
        return jsonify({'playlists': [playlist.to_dict() for playlist in playlists]}), 200

    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()[:120]
    if not name:
        return jsonify({'message': 'A playlist name is required'}), 400
    duplicate = SoundPlaylist.query.filter(
        SoundPlaylist.campaign_id == campaign.id,
        db.func.lower(SoundPlaylist.name) == name.lower(),
    ).first()
    if duplicate:
        return jsonify({'message': 'That playlist already exists'}), 409
    playlist = SoundPlaylist(
        campaign_id=campaign.id,
        name=name,
        shuffle=bool(data.get('shuffle', False)),
        created_by_id=user.id,
    )
    db.session.add(playlist)
    db.session.commit()
    socketio.emit('sound_playlists_updated', {'campaignID': campaign.id})
    return jsonify({'playlist': playlist.to_dict()}), 201


@app.route('/api/sound-quick-effects', methods=['GET'])
@jwt_required()
def sound_quick_effects():
    _user, campaign = sound_library_context()
    if not campaign:
        return jsonify({'message': 'Only a campaign DM or owner may use Quick FX'}), 403
    return jsonify({'slots': serialized_quick_effect_slots(campaign.id)}), 200


@app.route('/api/sound-quick-effects/<int:slot>', methods=['PUT'])
@jwt_required()
def configure_sound_quick_effect(slot):
    _user, campaign = sound_library_context()
    if not campaign:
        return jsonify({'message': 'Only a campaign DM or owner may configure Quick FX'}), 403
    if slot < 1 or slot > 6:
        return jsonify({'message': 'Quick FX slots are numbered 1 through 6'}), 400

    data = request.get_json(silent=True) or {}
    sound_id = data.get('soundId')
    sound = None
    if sound_id is not None:
        sound = SoundAsset.query.get(sound_id)
        if not sound:
            return jsonify({'message': 'Sound not found'}), 404
        if sound.category != 'sfx':
            return jsonify({'message': 'Quick FX slots only accept sound effects'}), 400

    configured = SoundQuickEffectSlot.query.filter_by(campaign_id=campaign.id, slot=slot).first()
    if not configured:
        configured = SoundQuickEffectSlot(campaign_id=campaign.id, slot=slot)
        db.session.add(configured)
    configured.sound_asset = sound
    db.session.commit()
    socketio.emit('sound_quick_effects_updated', {'campaignID': campaign.id})
    return jsonify({'slots': serialized_quick_effect_slots(campaign.id)}), 200


@app.route('/api/sound-playlists/<int:playlist_id>', methods=['PATCH', 'DELETE'])
@jwt_required()
def sound_playlist(playlist_id):
    _user, campaign = sound_library_context()
    if not campaign:
        return jsonify({'message': 'Only a campaign DM or owner may manage playlists'}), 403
    playlist = SoundPlaylist.query.filter_by(id=playlist_id, campaign_id=campaign.id).first()
    if not playlist:
        return jsonify({'message': 'Playlist not found'}), 404

    if request.method == 'DELETE':
        db.session.delete(playlist)
        db.session.commit()
        socketio.emit('sound_playlists_updated', {'campaignID': campaign.id})
        return '', 204

    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = str(data.get('name') or '').strip()[:120]
        if not name:
            return jsonify({'message': 'A playlist name is required'}), 400
        duplicate = SoundPlaylist.query.filter(
            SoundPlaylist.campaign_id == campaign.id,
            SoundPlaylist.id != playlist.id,
            db.func.lower(SoundPlaylist.name) == name.lower(),
        ).first()
        if duplicate:
            return jsonify({'message': 'That playlist already exists'}), 409
        playlist.name = name
    if 'shuffle' in data:
        playlist.shuffle = bool(data['shuffle'])
    db.session.commit()
    socketio.emit('sound_playlists_updated', {'campaignID': campaign.id})
    return jsonify({'playlist': playlist.to_dict()}), 200


@app.route('/api/sound-playlists/<int:playlist_id>/tracks', methods=['POST'])
@jwt_required()
def add_sound_playlist_track(playlist_id):
    _user, campaign = sound_library_context()
    if not campaign:
        return jsonify({'message': 'Only a campaign DM or owner may manage playlists'}), 403
    playlist = SoundPlaylist.query.filter_by(id=playlist_id, campaign_id=campaign.id).first()
    if not playlist:
        return jsonify({'message': 'Playlist not found'}), 404
    data = request.get_json(silent=True) or {}
    sound = SoundAsset.query.get(data.get('soundId'))
    if not sound or sound.category == 'sfx':
        return jsonify({'message': 'Choose a music or environment track'}), 400
    existing = SoundPlaylistTrack.query.filter_by(playlist_id=playlist.id, sound_asset_id=sound.id).first()
    if not existing:
        next_position = max((entry.position for entry in playlist.tracks), default=-1) + 1
        db.session.add(SoundPlaylistTrack(
            playlist_id=playlist.id,
            sound_asset_id=sound.id,
            position=next_position,
        ))
        db.session.commit()
    socketio.emit('sound_playlists_updated', {'campaignID': campaign.id})
    return jsonify({'playlist': playlist.to_dict()}), 200


@app.route('/api/sound-playlists/<int:playlist_id>/tracks/<int:sound_id>', methods=['DELETE'])
@jwt_required()
def remove_sound_playlist_track(playlist_id, sound_id):
    _user, campaign = sound_library_context()
    if not campaign:
        return jsonify({'message': 'Only a campaign DM or owner may manage playlists'}), 403
    playlist = SoundPlaylist.query.filter_by(id=playlist_id, campaign_id=campaign.id).first()
    if not playlist:
        return jsonify({'message': 'Playlist not found'}), 404
    entry = SoundPlaylistTrack.query.filter_by(playlist_id=playlist.id, sound_asset_id=sound_id).first()
    if entry:
        db.session.delete(entry)
        db.session.flush()
        remaining_tracks = [remaining for remaining in playlist.tracks if remaining.id != entry.id]
        for position, remaining in enumerate(remaining_tracks):
            remaining.position = position
        db.session.commit()
    socketio.emit('sound_playlists_updated', {'campaignID': campaign.id})
    return jsonify({'playlist': playlist.to_dict()}), 200


@app.route('/media/<path:filename>', methods=['GET'])
def development_media(filename):
    return send_from_directory(app.config["MEDIA_ROOT"], filename)

def ensure_avatar_dirs(user_id: int) -> tuple[Path, Path]:
    user_root = Path(app.config["AVATAR_UPLOAD_ROOT"]) / str(user_id)
    thumb_root = user_root / "thumbs"
    user_root.mkdir(parents=True, exist_ok=True)
    thumb_root.mkdir(parents=True, exist_ok=True)
    return user_root, thumb_root

def build_avatar_urls(user_id: int, filename: str, thumb_filename: str | None = None) -> tuple[str, str | None]:
    image_url = f"/media/avatars/uploads/{user_id}/{filename}"
    thumb_url = f"/media/avatars/uploads/{user_id}/thumbs/{thumb_filename}" if thumb_filename else None
    return image_url, thumb_url

def make_avatar_thumbnail(src_path: Path, dst_path: Path, size=(128, 128)) -> None:
    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        img.thumbnail(size)
        img.save(dst_path, format="WEBP", quality=88)


def save_campaign_icon(uploaded, campaign_id: int) -> str:
    destination = Path(app.config['CAMPAIGN_ICON_ROOT']) / str(campaign_id)
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"campaign_{campaign_id}_{uuid4().hex}.webp"
    output_path = destination / filename
    with Image.open(uploaded.stream) as image:
        image.load()
        normalized = ImageOps.fit(image.convert('RGB'), (512, 512), method=Image.Resampling.LANCZOS)
        normalized.save(output_path, format='WEBP', quality=90, method=6)
    return f"/media/campaign-icons/{campaign_id}/{filename}"

######################################################################################
@app.cli.command("set-all-users-offline")
@with_appcontext
def set_all_users_offline_command():
    set_all_users_offline()
    click.echo("All users set offline.")

def normalize_keys(d):
    if isinstance(d, dict):
        new_dict = {}
        for k, v in d.items():
            new_key = k.lower().replace(' ', '_')
            if k.endswith('n') and not new_key.endswith('n'):
                app.logger.error(f"Key '{k}' was transformed to '{new_key}' incorrectly.")
            new_dict[new_key] = normalize_keys(v)
        return new_dict
    elif isinstance(d, list):
        return [normalize_keys(i) for i in d]
    else:
        return d

def load_json_files(directory):
    elements = []
    if os.path.exists(directory):
        for filename in os.listdir(directory):
            if not filename.endswith('.json'):
                continue

            # Skip macOS resource fork files (._*) which are not valid JSON
            if filename.startswith('._'):
                app.logger.debug("Skipping macOS resource file: %s", filename)
                continue

            file_path = os.path.join(directory, filename)
            # Try UTF-8 first, fall back to latin-1 if necessary
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    data = json.load(file)
            except UnicodeDecodeError as ude:
                app.logger.warning("UnicodeDecodeError reading %s with utf-8: %s; trying latin-1", filename, ude)
                try:
                    with open(file_path, 'r', encoding='latin-1') as file:
                        data = json.load(file)
                except Exception as e:
                    app.logger.error("Error decoding JSON from file %s with latin-1: %s", filename, e)
                    continue
            except json.JSONDecodeError as jde:
                app.logger.error("Error decoding JSON from file %s: %s", filename, jde)
                continue
            except Exception as e:
                app.logger.error("Unexpected error reading %s: %s", filename, e)
                continue

            normalized_data = normalize_keys(data)
            base_name = os.path.splitext(filename)[0]
            elements.append((base_name, normalized_data))
            app.logger.debug("Loaded %s from %s", filename, directory)
    return elements

def insert_elements(system, element_type, directory):
    if not os.path.exists(directory):
        app.logger.warn(f"Directory {directory} does not exist. Skipping...")
        return
    elements = load_json_files(directory)
    app.logger.debug(f"Loading Elements from {directory}")  # Print the elements
    with db.session.no_autoflush:
        for name, data in elements:
            existing_element = GameElement.query.filter_by(name=name).first()
            if existing_element is None:
                new_element = GameElement(name=name, system=system, element_type=element_type, data=data, setting='Faerun')
                # app.logger.debug(f"New element: {new_element}")  # Print the new element
                db.session.add(new_element)
    db.session.commit()

def populate_game_elements():
    insert_elements('D&D 5e', 'race', './GameElements/races')
    insert_elements('D&D 5e', 'class', './GameElements/classes')
    insert_elements('D&D 5e', 'character_background', './GameElements/characterBackgrounds')
    insert_elements('D&D 5e', 'character_sheet', './GameElements/characterSheets')


def set_all_users_offline():
    users = User.query.all()

    for user in users:
        user.is_online = False
        # campaign.members.append(user)   ## Temporary
    db.session.commit()


## Fuzzy Logic for mapping incoming data to model columns
def get_table_columns(model):
    """Get the column names for a given SQLAlchemy model."""
    return [column.name for column in model.__table__.columns]

def map_fields(data, model):
    """Map incoming data fields to model columns using fuzzy matching."""
    app.logger.debug(f"Mapping fields for {model.__name__}")

    valid_fields = get_table_columns(model)
    mapped_data = {}
    matched_fields = set()

    for key, value in data.items():
        best_match = None
        for score_cutoff in range(100, 75, -5):
            match = process.extractOne(key, valid_fields, score_cutoff=score_cutoff)
            if match and match[0] not in matched_fields:
                best_match = match
                app.logger.debug(f"Score cutoff: {score_cutoff}, Mapping {key} to {best_match[0]}")
                break

        if best_match:
            mapped_data[best_match[0]] = value
            matched_fields.add(best_match[0])
        else:
            mapped_data[key] = value  # Keep original if no match found
            app.logger.debug(f"No match found for {key}")

        # Stop if all valid fields have been matched
        if len(matched_fields) == len(valid_fields):
            break

    # app.logger.debug("Mapped data: %s", mapped_data)
    return mapped_data


migrate = Migrate(app, db)


@app.route('/')
def index():
    return "Flask Websocket Server"


# Global error handler
@app.errorhandler(Exception)
def handle_exception(e):
    tb = traceback.format_exc()
    app.logger.error(f"An error occurred: {str(e)}")
    app.logger.error(f"Request data: {request.data}")
    app.logger.error(f"Traceback: {tb}")
    
    # Return a JSON response with a generic error message and traceback
    response = {
        "error": "An unexpected error occurred",
        "details": str(e),
        "traceback": tb
    }
    return jsonify(response), 500

@app.errorhandler(NotFound)
def handle_not_found(e):
    app.logger.error(f"404 Not Found: {request.url}")
    app.logger.error(f"Request method: {request.method}")
    app.logger.error(f"Request headers: {request.headers}")
    app.logger.error(f"Request data: {request.data}")
    
    # Return a JSON response with a 404 error message
    response = {
        "error": "The requested URL was not found on the server.",
        "details": str(e)
    }
    return jsonify(response), 404

@app.after_request
def refresh_expiring_jwts(response):
    try:
        exp_timestamp = get_jwt()["exp"]
        now = datetime.now(timezone.utc)
        target_timestamp = datetime.timestamp(now + timedelta(minutes=30))
            
        if target_timestamp > exp_timestamp:
            access_token = create_access_token(identity=get_jwt_identity())
            set_shared_session_cookie(response, access_token)
            
            # Get the JSON data from the response
            data = response.get_json()
            
            # Check if data is a list
            if isinstance(data, list):
                # Add the new token to each dictionary in the list
                for item in data:
                    if isinstance(item, dict):
                        item['new_token'] = access_token
            elif isinstance(data, dict):
                # Add the new token to the data dictionary
                data['new_token'] = access_token
            
            # Keep the original status code and headers while exposing the refreshed
            # bearer token to clients that already understand `new_token`.
            if data is not None:
                response.set_data(app.json.dumps(data))
                response.content_type = 'application/json'
        return response
    
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original response
        return response


SHARED_SESSION_COOKIE = 'kachhapa_session'


def shared_session_cookie_domain():
    """Return the hostname shared by the Kachhapa sibling sites.

    Browsers isolate localStorage by origin, but a Domain cookie issued for
    raspberrypi.local is available to maps.raspberrypi.local and the other
    Nginx virtual hosts. Localhost and numeric development hosts remain
    host-only cookies.
    """
    hostname = (request.host or '').split(':', 1)[0].lower().rstrip('.')
    if not hostname or hostname == 'localhost' or hostname.replace('.', '').isdigit():
        return None
    first_label, separator, parent = hostname.partition('.')
    if separator and first_label in {'app', 'maps', 'mtg', 'tools'}:
        return parent
    return hostname if '.' in hostname else None


def shared_session_cookie_secure():
    forwarded_proto = request.headers.get('X-Forwarded-Proto', '').split(',', 1)[0].strip()
    return request.is_secure or forwarded_proto == 'https'


def set_shared_session_cookie(response, token):
    response.set_cookie(
        SHARED_SESSION_COOKIE,
        token,
        max_age=int(app.config['JWT_ACCESS_TOKEN_EXPIRES'].total_seconds()),
        httponly=True,
        secure=shared_session_cookie_secure(),
        samesite='Lax',
        domain=shared_session_cookie_domain(),
        path='/',
    )


def clear_shared_session_cookie(response):
    response.delete_cookie(
        SHARED_SESSION_COOKIE,
        httponly=True,
        secure=shared_session_cookie_secure(),
        samesite='Lax',
        domain=shared_session_cookie_domain(),
        path='/',
    )

## Verify a user's JWT token
@app.route('/api/verify', methods=['POST'])
def verify_token():
    # app.logger.debug("/api/verify: %s", request.json)
    data = request.get_json()
    origin = request.headers.get('Origin')
    token = data.get('token')
    app.logger.debug("Token: %s", token)
    # app.logger.debug("Origin: %s", origin)
    try:
        decoded_token = decode_token(token)
        app.logger.debug("Decoded Token:", decoded_token)

        user = User.query.filter_by(username=decoded_token['sub']).first()
        if user is None:
            print("Invalid user")
            app.logger.info("Invalid user")
            return jsonify({'error': 'Invalid user'}), 401
        response = jsonify({'success': True, "id": user.id, "username": user.username})
        # Upgrade existing origin-local sessions to the shared sibling-host cookie.
        set_shared_session_cookie(response, token)
        return response
    except InvalidTokenError:
        return jsonify({'error': 'InvalidTokenError- POST /api/verify'}), 401
    except ExpiredSignatureError:
        print("Expired token")
        app.logger.info("Expired token")
        return jsonify({'error': 'Expired token- ExpiredSignatureError'}), 401


@app.route('/api/session', methods=['GET'])
def restore_shared_session():
    """Bootstrap the existing bearer-token frontend on any sibling hostname."""
    token = request.cookies.get(SHARED_SESSION_COOKIE)
    if not token:
        return jsonify({'message': 'No shared session'}), 401
    try:
        decoded_token = decode_token(token)
        user = User.query.filter_by(username=decoded_token['sub']).first()
        if user is None:
            raise InvalidTokenError('Unknown user')
        return jsonify({
            'success': True,
            'access_token': token,
            'id': user.id,
            'username': user.username,
        }), 200
    except (InvalidTokenError, ExpiredSignatureError):
        response = jsonify({'message': 'Shared session expired'})
        clear_shared_session_cookie(response)
        return response, 401


@app.route('/api/logout', methods=['POST'])
def logout():
    response = jsonify({'success': True})
    clear_shared_session_cookie(response)
    return response, 200

## Used to log in a new user
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    if 'username' not in data or 'password' not in data:
        return jsonify({'message': 'Username and password are required!'}), 400
    try:
        user = User.query.filter_by(username=str(data['username']).lower()).first()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception('Login failed because the application database is unavailable')
        return jsonify({
            'message': 'The server database is unavailable or has not finished initializing. Please try again shortly.'
        }), 503
    if not user:
        return jsonify({'message': 'Invalid Username'}), 401
    elif not check_password_hash(user.password, data['password']):
        return jsonify({'message': 'Incorrect Password'}), 401
    print("Creating Access Token for", user.username)
    # app.logger.info("Creating Access Token for %s", user.username)
    access_token = create_access_token(identity=user.username)

    user.is_online = True
    db.session.commit()
    # campaign_id = request.args.get('campaignID')  # Retrieve the campaignID from the request arguments
    # emit_active_users(campaign_id)
    response = jsonify({
        'message': 'Login successful!', 
        'access_token': access_token,
        'userID': user.id,  # Include the user's ID in the response
        'username': user.username,
    })
    set_shared_session_cookie(response, access_token)
    return response, 200

@app.route('/api/register', methods=['POST'])
def register():
    ## app.logger.debug("/api/register: %s", request.json)
    data = request.get_json()
    app.logger.debug("Data from Register:", data)
    
    if 'username' not in data or 'password' not in data:
        return jsonify({'message': 'Username and password are required!'}), 400

    # Check if a user with the given username already exists
    existing_user = User.query.filter_by(username=data['username'].lower()).first()
    if existing_user:
        return jsonify({'message': 'A user with this username already exists.'}), 400

    hashed_password = generate_password_hash(data['password'], method='sha256')
    new_user = User(username=data['username'].lower(), password=hashed_password)

    db.session.add(new_user)
    db.session.commit()
    ## app.logger.debug(new_user.is_online)
    access_token = create_access_token(identity=new_user.username)
    
    # If the client provided an initial character, create it and associate with the user and campaign
    try:
        character_data = data.get('character')
        campaign_id = data.get('CampaignID', 1)

        created_character = None
        if character_data:
            # Map incoming character fields to the Character model columns
            mapped = map_fields(character_data, Character)

            # Ability scores may be provided nested under `abilityScores`
            ability_scores = character_data.get('abilityScores') or character_data.get('ability_scores') or {}

            # Helper to get value from nested abilityScores or top-level mapped fields
            def get_score(key):
                val = ability_scores.get(key) if isinstance(ability_scores, dict) else None
                if val is None:
                    val = mapped.get(key)
                return int(val) if val is not None and str(val).isdigit() else 0

            created_character = Character(
                icon=mapped.get('icon'),
                system=mapped.get('system', character_data.get('system', 'D&D 5e')),
                userID=new_user.id,
                campaignID=campaign_id,
                character_name=(mapped.get('character_name') or mapped.get('name') or character_data.get('Name') or character_data.get('name')),
                Class=mapped.get('Class') or mapped.get('class'),
                Background=mapped.get('Background') or mapped.get('background'),
                Race=mapped.get('Race') or mapped.get('race'),
                Alignment=mapped.get('Alignment') or mapped.get('alignment'),
                ExperiencePoints=int(mapped.get('ExperiencePoints')) if mapped.get('ExperiencePoints') else 0,
                strength=get_score('strength'),
                dexterity=get_score('dexterity'),
                constitution=get_score('constitution'),
                intelligence=get_score('intelligence'),
                wisdom=get_score('wisdom'),
                charisma=get_score('charisma'),
                PersonalityTraits=mapped.get('PersonalityTraits') or mapped.get('personalitytraits'),
                Ideals=mapped.get('Ideals') or mapped.get('ideals'),
                Bonds=mapped.get('Bonds') or mapped.get('bonds'),
                Flaws=mapped.get('Flaws') or mapped.get('flaws'),
                Feats=json.dumps(mapped.get('Feats', [])) if mapped.get('Feats') is not None else json.dumps([]),
                Proficiencies=json.dumps(mapped.get('Proficiencies', [])) if mapped.get('Proficiencies') is not None else json.dumps([]),
                CurrentHitPoints=int(mapped.get('CurrentHitPoints')) if mapped.get('CurrentHitPoints') else 0,
                cp=int(mapped.get('cp')) if mapped.get('cp') else 0,
                sp=int(mapped.get('sp')) if mapped.get('sp') else 0,
                ep=int(mapped.get('ep')) if mapped.get('ep') else 0,
                gp=int(mapped.get('gp')) if mapped.get('gp') else 0,
                pp=int(mapped.get('pp')) if mapped.get('pp') else 0
            )

            db.session.add(created_character)
            db.session.flush()  # ensure id is available

            # Insert association row into campaign_members with the characterID
            try:
                insert_stmt = campaign_members.insert().values(
                    userID=new_user.id,
                    campaignID=campaign_id,
                    characterID=created_character.id
                )
                db.session.execute(insert_stmt)
            except Exception:
                app.logger.exception('Failed to insert campaign_members row')

        db.session.commit()
    except Exception:
        # If character creation or association failed, rollback but still return registration token
        app.logger.exception('Error creating initial character for new user')
        db.session.rollback()

    response = jsonify({
        'message': 'Registration successful!', 
        'access_token': access_token,
        'userID': new_user.id,  # legacy key (camelCase)
        'user_id': new_user.id,  # snake_case expected by client
        'character_id': created_character.id if created_character else None,
        'character': created_character.to_dict() if created_character else None
    })
    set_shared_session_cookie(response, access_token)
    return response

## Get a user's profile information
@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    try:
        username = get_jwt_identity()
        user = User.query.filter_by(username=username).first()
        campaignID = request.headers.get('CampaignID')
        if campaignID:
            character = Character.query.filter_by(userID=user.id, campaignID=campaignID).first()
            if character:
                return jsonify({'username': user.username, 'id': user.id, 'character': character.to_dict()})
            else:
                return jsonify({'username': user.username, 'id': user.id, 'character': None})
        else:
            return jsonify({'username': user.username, 'id': user.id})
    except InvalidTokenError:
        return jsonify({'error': 'InvalidTokenError- GET /api/profile'}), 401
    except ExpiredSignatureError:
        return jsonify({'error': 'Expired token'}), 401

## Get all users in a campaign
@app.route('/api/campaigns', methods=['GET', 'POST'])
@jwt_required()
def campaigns():
    if request.method == 'GET':
        username = get_jwt_identity()
        user = User.query.filter_by(username=username).first()
        campaigns = user.campaigns
        campaign_list = [campaign.to_dict() for campaign in campaigns]
        app.logger.debug("CAMPAIGNS- campaigns: %s", campaign_list)
        return jsonify(campaign_list)
    
    elif request.method == 'POST':
        data = request.get_json()
        username = get_jwt_identity()
        app.logger.debug("CAMPAIGN- username: %s", username)
    
        user = User.query.filter_by(username=username).first()
        app.logger.debug("CAMPAIGN- user: %s", user.to_dict())
    
        requested_system = str(data.get('system') or 'D&D').strip()
        requested_ruleset = str(data.get('ruleset') or '5e').strip()
        if requested_system == 'D&D 5e':
            requested_system, requested_ruleset = 'D&D', '5e'
        if requested_system == 'D&D' and requested_ruleset not in DND_RULESET_SYSTEMS:
            return jsonify({'message': 'Choose a supported D&D ruleset'}), 400

        # Create a new campaign with all necessary values
        campaign = Campaign(
            name=data['name'],
            system=requested_system,
            ruleset=requested_ruleset if requested_system == 'D&D' else None,
            module=data.get('module'),
            owner_id=user.id,
            dm_id=user.id,
            icon=data.get('icon', None),
            description=data.get('description', None),
            scribes=data.get('scribes', [])
        )
        db.session.add(campaign)
        db.session.flush()  # Ensure the campaign ID is generated

        if not seed_campaign_world(campaign):
            db.session.add(WorldAtlasLocation(
                campaign_id=campaign.id,
                name='New Settlement',
                map_key=uuid4().hex,
                is_primary=True,
            ))
    
        app.logger.debug("Creating new campaign %s", campaign.to_dict())
    
        seed_campaign_wiki(campaign, data.get('module'))

        initial_definition = module_definition(data.get('module'))
        if initial_definition:
            ensure_module_calendar(campaign, initial_definition, strategy='use_module')
            seed_module_npcs(campaign, initial_definition)
            record_module_installation(
                campaign, initial_definition, user.id,
                settlement_strategy='override', calendar_strategy='use_module',
            )
        elif data.get('calendar_enabled'):
            format_slug = str(data.get('calendar_format') or 'gregorian').strip().lower()
            format_element = ensure_calendar_format(format_slug)
            if not format_element:
                db.session.rollback()
                return jsonify({'message': 'Unsupported calendar format'}), 400
            try:
                calendar_year = int(data.get('calendar_year', 1))
                calendar_month_index = int(data.get('calendar_month', 1)) - 1
                calendar_day = int(data.get('calendar_day', 1))
            except (TypeError, ValueError):
                db.session.rollback()
                return jsonify({'message': 'Calendar year, month, and day must be whole numbers'}), 400
            months = (format_element.data or {}).get('months', [])
            if calendar_month_index < 0 or calendar_month_index >= len(months):
                db.session.rollback()
                return jsonify({'message': 'The selected calendar month is invalid'}), 400
            max_day = int(months[calendar_month_index].get('length', 0))
            if calendar_day < 1 or calendar_day > max_day:
                db.session.rollback()
                return jsonify({'message': f'Calendar day must be between 1 and {max_day}'}), 400
            db.session.add(Calendar(
                name=f'{campaign.name} Calendar',
                description=f'Calendar for {campaign.name}',
                campaign_id=campaign.id,
                format_id=format_element.id,
                format_slug=format_slug,
                current_year=calendar_year,
                current_month_index=calendar_month_index,
                current_day=calendar_day,
                current_hour=0,
                current_minute=0,
                epoch_year=1,
                epoch_month_index=0,
                epoch_day=1,
            ))
    
        # Add the campaign creator as a member of their own campaign
        app.logger.debug("Adding user %s to campaign %s", user.id, campaign.id)
        db.session.execute(campaign_members.insert().values(userID=user.id, campaignID=campaign.id))
    
        # Get all users except the current user
        other_users = User.query.filter(User.id != user.id).all()
        app.logger.debug("other_users- %s", other_users)
        for other_user in other_users:
            # Add each user to the campaign's members
            db.session.execute(campaign_members.insert().values(userID=other_user.id, campaignID=campaign.id))
    
        db.session.commit()
        return jsonify(campaign.to_dict()), 201


def campaign_modules_payload(campaign):
    installations = CampaignModuleInstallation.query.filter_by(campaign_id=campaign.id).order_by(
        CampaignModuleInstallation.installed_at, CampaignModuleInstallation.id
    ).all()
    installed_keys = {installation.module_key for installation in installations}
    calendar = Calendar.query.filter_by(campaign_id=campaign.id).first()
    return {
        'campaign': campaign.to_dict(),
        'installed_modules': [installation.to_dict() for installation in installations],
        'available_modules': [
            {**definition, 'installed': definition['key'] in installed_keys}
            for definition in module_catalog()
        ],
        'calendar': ({
            'name': calendar.name,
            'format_slug': calendar.format_slug,
            'current_year': calendar.current_year,
            'current_month_index': calendar.current_month_index,
            'current_day': calendar.current_day,
        } if calendar else None),
        'profile_icon_presets': CAMPAIGN_ICON_PRESETS,
    }


@app.route('/api/profile-image-presets', methods=['GET'])
@jwt_required()
def get_profile_image_presets():
    return jsonify({
        'campaign_icons': CAMPAIGN_ICON_PRESETS,
        'character_avatars': CHARACTER_AVATAR_PRESETS,
    }), 200


@app.route('/api/campaigns/<int:campaign_id>/ruleset', methods=['PATCH'])
@jwt_required()
def update_campaign_ruleset(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may change its ruleset'}), 403

    data = request.get_json(silent=True) or {}
    ruleset = str(data.get('ruleset') or '').strip()
    if ruleset not in DND_RULESET_SYSTEMS:
        return jsonify({'message': 'Choose a supported D&D ruleset'}), 400

    campaign.system = 'D&D'
    campaign.ruleset = ruleset
    db.session.commit()
    return jsonify({'campaign': campaign.to_dict()}), 200


@app.route('/api/campaigns/<int:campaign_id>/name', methods=['PATCH'])
@jwt_required()
def update_campaign_name(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may change its name'}), 403

    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify({'message': 'Campaign name is required'}), 400
    if len(name) > 100:
        return jsonify({'message': 'Campaign names must be 100 characters or fewer'}), 400

    # Wiki routes currently use the display name as their URL segment. Preventing
    # ambiguous names keeps those routes deterministic while all stored campaign
    # content and relationships continue to use the immutable campaign ID.
    conflict = Campaign.query.filter(
        Campaign.id != campaign.id,
        func.lower(Campaign.name) == name.casefold(),
    ).first()
    if conflict:
        return jsonify({'message': 'Another campaign already uses that name'}), 409

    campaign.name = name
    db.session.commit()
    return jsonify({'campaign': campaign.to_dict()}), 200


@app.route('/api/campaigns/<int:campaign_id>/profile-icon', methods=['PATCH', 'POST'])
@jwt_required()
def update_campaign_profile_icon(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may change its profile icon'}), 403

    if request.method == 'PATCH':
        data = request.get_json(silent=True) or {}
        if data.get('reset'):
            campaign.icon = None
        else:
            preset = campaign_icon_preset(str(data.get('preset_key') or ''))
            if not preset:
                return jsonify({'message': 'Choose a valid campaign icon preset'}), 400
            campaign.icon = preset['url']
    else:
        if request.content_length and request.content_length > 5 * 1024 * 1024:
            return jsonify({'message': 'Campaign icon uploads must be 5 MB or smaller'}), 413
        uploaded = request.files.get('icon')
        if not uploaded or not uploaded.filename:
            return jsonify({'message': 'Choose an image to upload'}), 400
        if not allowed_avatar_file(uploaded.filename):
            return jsonify({'message': 'Campaign icons must be PNG, JPEG, or WebP images'}), 400
        try:
            campaign.icon = save_campaign_icon(uploaded, campaign.id)
        except (OSError, ValueError):
            app.logger.exception('Invalid campaign icon upload for campaign %s', campaign.id)
            return jsonify({'message': 'The uploaded file is not a valid image'}), 400

    db.session.commit()
    return jsonify({'campaign': campaign.to_dict()}), 200


@app.route('/api/campaigns/<int:campaign_id>/modules', methods=['GET'])
@jwt_required()
def get_campaign_modules(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may manage modules'}), 403
    return jsonify(campaign_modules_payload(campaign)), 200


@app.route('/api/campaigns/<int:campaign_id>/modules/preview', methods=['POST'])
@jwt_required()
def preview_campaign_module(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may manage modules'}), 403
    data = request.get_json(silent=True) or {}
    definition = module_definition(data.get('module_key'))
    if not definition:
        return jsonify({'message': 'Unknown module'}), 404
    installed = CampaignModuleInstallation.query.filter_by(
        campaign_id=campaign.id, module_key=definition['key']
    ).first()
    template = campaign_module_template(definition['key'], MEDIA_ROOT)
    conflicts = []
    if template:
        incoming_name = template['name'].strip().casefold()
        for location in WorldAtlasLocation.query.filter_by(campaign_id=campaign.id).all():
            if location.map_key == template['map_key'] or location.name.strip().casefold() == incoming_name:
                conflicts.append({
                    'settlement_id': location.id,
                    'existing_name': location.name,
                    'incoming_name': template['name'],
                    'map_key': location.map_key,
                })
    calendar = Calendar.query.filter_by(campaign_id=campaign.id).first()
    current_year = calendar.current_year if calendar else None
    module_year = definition.get('starting_year')
    public_definition = next(item for item in module_catalog() if item['key'] == definition['key'])
    return jsonify({
        'module': public_definition,
        'already_installed': installed is not None,
        'settlement_template_available': template is not None,
        'settlement_conflicts': conflicts,
        'calendar': {
            'exists': calendar is not None,
            'current_year': current_year,
            'current_format': calendar.format_slug if calendar else None,
            'module_year': module_year,
            'module_format': definition.get('calendar', {}).get('slug'),
            'year_mismatch': current_year is not None and module_year is not None and current_year != module_year,
            'format_mismatch': calendar is not None and calendar.format_slug != definition.get('calendar', {}).get('slug'),
        },
    }), 200


@app.route('/api/campaigns/<int:campaign_id>/modules', methods=['POST'])
@jwt_required()
def install_campaign_module(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may manage modules'}), 403
    data = request.get_json(silent=True) or {}
    definition = module_definition(data.get('module_key'))
    if not definition:
        return jsonify({'message': 'Unknown module'}), 404
    if CampaignModuleInstallation.query.filter_by(campaign_id=campaign.id, module_key=definition['key']).first():
        return jsonify({'message': 'That module is already installed in this campaign'}), 409

    settlement_strategy = data.get('settlement_strategy', 'merge')
    calendar_strategy = data.get('calendar_strategy', 'keep_current')
    if settlement_strategy not in {'merge', 'keep', 'override'}:
        return jsonify({'message': 'Settlement strategy must be merge, keep, or override'}), 400
    if calendar_strategy not in {'keep_current', 'use_module'}:
        return jsonify({'message': 'Calendar strategy must be keep_current or use_module'}), 400

    user = User.query.filter_by(username=get_jwt_identity()).first()
    try:
        template = campaign_module_template(definition['key'], MEDIA_ROOT)
        settlement_result = 'none'
        location = None
        if template:
            location, settlement_result = import_module_settlement(campaign, template, settlement_strategy)
        calendar = ensure_module_calendar(campaign, definition, strategy=calendar_strategy)
        wiki_pages_added = seed_module_wiki_pages(campaign, definition['name'])
        module_npcs_added = seed_module_npcs(campaign, definition)
        installation = record_module_installation(
            campaign, definition, user.id if user else None, settlement_strategy, calendar_strategy
        )
        if not campaign.module:
            campaign.module = definition['name']
        campaign_atlas_config(campaign)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to install module %s into campaign %s', definition['key'], campaign.id)
        return jsonify({'message': 'The module import failed and no changes were saved'}), 500

    if location:
        socketio.emit(
            'world_atlas_updated',
            {'action': settlement_result, 'settlement': location.atlas_dict()},
            to=f'campaign:{campaign.id}',
        )
    emit_calendar_updated(campaign.id)
    return jsonify({
        'installation': installation.to_dict(),
        'settlement_result': settlement_result,
        'wiki_pages_added': wiki_pages_added,
        'npcs_added': len(module_npcs_added),
        'calendar': calendar.to_dict() if calendar else None,
        **campaign_modules_payload(campaign),
    }), 201


@app.route('/api/campaigns/<int:campaign_id>/modules/<module_key>/refresh', methods=['POST'])
@jwt_required()
def refresh_campaign_module(campaign_id, module_key):
    """Idempotently import new preset material added after module installation."""
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may refresh modules'}), 403
    definition = module_definition(module_key)
    if not definition:
        return jsonify({'message': 'Unknown module'}), 404
    installation = CampaignModuleInstallation.query.filter_by(
        campaign_id=campaign.id, module_key=definition['key']
    ).first()
    if not installation:
        return jsonify({'message': 'Install that module before refreshing it'}), 409

    data = request.get_json(silent=True) or {}
    settlement_strategy = data.get('settlement_strategy', 'merge')
    if settlement_strategy not in {'merge', 'keep', 'override'}:
        return jsonify({'message': 'Settlement strategy must be merge, keep, or override'}), 400

    try:
        template = campaign_module_template(definition['key'], MEDIA_ROOT)
        location = None
        settlement_result = 'none'
        if template:
            location, settlement_result = import_module_settlement(campaign, template, settlement_strategy)
        wiki_pages_added = seed_module_wiki_pages(campaign, definition['name'])
        module_npcs_added = seed_module_npcs(campaign, definition)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Unable to refresh module %s in campaign %s', definition['key'], campaign.id)
        return jsonify({'message': 'The module refresh failed and no changes were saved'}), 500

    if location:
        socketio.emit(
            'world_atlas_updated',
            {'action': settlement_result, 'settlement': location.atlas_dict()},
            to=f'campaign:{campaign.id}',
        )
    return jsonify({
        'module_key': definition['key'],
        'settlement_result': settlement_result,
        'wiki_pages_added': wiki_pages_added,
        'npcs_added': len(module_npcs_added),
        'npc_total': NPC.query.filter_by(campaign_id=campaign.id).count(),
    }), 200



@app.route('/api/characters', methods=['GET', 'POST'])
@jwt_required()
def get_user_characters():
    if request.method == 'GET':
        username = get_jwt_identity()
        app.logger.debug("Request from %s", username)

        user = User.query.filter_by(username=username).first()
        app.logger.debug("Located user %s in database", user.to_dict())

        characters = Character.query.filter_by(userID=user.id).all()
        character_list = [character.to_dict() for character in characters]
        # app.logger.debug("Character List:, %s", character_list)
        
        return jsonify(character_list)
    
    elif request.method == 'POST':
        data = request.get_json()
        username = get_jwt_identity()
        user = User.query.filter_by(username=username).first()

        # Map fields for the Character model using fuzzy matching
        data = map_fields(data, Character)

        # Validate required fields
        required_fields = ['character_name', 'Class', 'Background', 'Race', 'Alignment', 'ExperiencePoints', 
                           'strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma']
        for field in required_fields:
            if field not in data:
                return jsonify({'message': f'{field} is required!'}), 400

        # Create a new character
        new_character = Character(
            icon=data.get('icon'),
            system=data.get('system', 'D&D 5e'),  # Default to 'D&D 5e' if not provided
            userID=user.id,
            campaignID=data.get('campaignID'),
            character_name=data['character_name'],
            Class=data['Class'],
            Background=data['Background'],
            Race=data['Race'],
            Alignment=data['Alignment'],
            ExperiencePoints=data['ExperiencePoints'],
            strength=data['strength'],
            dexterity=data['dexterity'],
            constitution=data['constitution'],
            intelligence=data['intelligence'],
            wisdom=data['wisdom'],
            charisma=data['charisma'],
            PersonalityTraits=data.get('PersonalityTraits'),
            Ideals=data.get('Ideals'),
            Bonds=data.get('Bonds'),
            Flaws=data.get('Flaws'),
            Feats=json.dumps(data.get('Feats', [])),
            Proficiencies=json.dumps(data.get('Proficiencies', [])),
            CurrentHitPoints=data.get('CurrentHitPoints', 0),
            cp=data.get('cp', 0),
            sp=data.get('sp', 0),
            ep=data.get('ep', 0),
            gp=data.get('gp', 0),
            pp=data.get('pp', 0)
        )

        # Add the new character to the session and commit
        db.session.add(new_character)
        db.session.flush()

        if new_character.campaignID:
            membership = db.session.execute(
                select(campaign_members).where(
                    campaign_members.c.userID == user.id,
                    campaign_members.c.campaignID == new_character.campaignID
                )
            ).first()
            if membership:
                db.session.execute(
                    campaign_members.update().where(
                        campaign_members.c.userID == user.id,
                        campaign_members.c.campaignID == new_character.campaignID
                    ).values(characterID=new_character.id)
                )
            else:
                db.session.execute(campaign_members.insert().values(
                    userID=user.id,
                    campaignID=new_character.campaignID,
                    characterID=new_character.id
                ))

        db.session.commit()

        return jsonify(new_character.to_dict()), 201


@app.route('/api/campaign_characters', methods=['GET'])
@jwt_required()
def get_campaign_characters():
    """Return all characters for a given campaign (DM view / character switcher).

    Expects `CampaignID` header. Returns 400 if missing. Only returns characters
    linked via campaign_members to keep scope bounded to the campaign.
    """
    campaign_id = request.headers.get('CampaignID')
    if not campaign_id:
        return jsonify({'error': 'CampaignID header is required'}), 400

    try:
        # Find character IDs linked to the campaign via association table
        stmt = select(campaign_members.c.characterID).where(campaign_members.c.campaignID == campaign_id)
        character_ids = [row.characterID for row in db.session.execute(stmt) if row.characterID]

        if not character_ids:
            return jsonify([])

        characters = Character.query.filter(Character.id.in_(character_ids)).all()
        return jsonify([c.to_dict() for c in characters])
    except Exception:
        app.logger.exception('Error fetching campaign characters')
        return jsonify({'error': 'internal server error'}), 500


@app.route('/api/characterSheet')
def get_characterSheet():
    # Determine the System in use
    campaignID = request.headers.get('CampaignID')
    campaign = Campaign.query.filter_by(id=campaignID).first()
    system = campaign.rules_system if campaign else 'D&D 5e'

    characterSheet = GameElement.query.filter_by(element_type='character_sheet', system=system).first()
    if not characterSheet:
        app.logger.debug("CharacterSheet: none found for system %s", system)
        return jsonify({})
    app.logger.debug("CharacterSheet- %s", characterSheet.data)
    return jsonify(characterSheet.data)

@app.route('/api/classes')
def get_class_listing():
    # Determine the System in use: explicit override, then campaign, else warn
    system, campaign = resolve_system_from_request()
    if not system:
        app.logger.warning("System not provided and no CampaignID/system resolution for /api/classes")
        return jsonify({'error': 'System or CampaignID header is required'}), 400

    try:
        classes = GameElement.query.filter_by(element_type='class', system=system).all()
        app.logger.debug("Returning %d classes for system %s", len(classes), system)
        # Return only the name field for listing (not full data) to reduce payload size
        return jsonify([{'name': c.name} for c in classes])
    except Exception:
        app.logger.exception("Error fetching classes")
        return jsonify({'error': 'internal server error'}), 500

@app.route('/api/classes/<class_name>')
def get_class_info(class_name):
    # Determine the System in use: explicit override, then campaign, else warn
    system, campaign = resolve_system_from_request()
    if not system:
        app.logger.warning("System not provided and no CampaignID/system resolution for /api/classes/<class_name>")
        return jsonify({'error': 'System or CampaignID header is required'}), 400

    game_element = GameElement.query.filter_by(name=class_name, element_type='class', system=system).first()
    if game_element:
        return jsonify(game_element.data)
    else:
        return jsonify({"error": f"No class named '{class_name}' found"}), 404

@app.route('/api/races', methods=['GET'])
def get_race_listing():
    # Determine the System in use: explicit override, then campaign, else warn
    system, campaign = resolve_system_from_request()
    if not system:
        app.logger.warning("System not provided and no CampaignID/system resolution for /api/races")
        return jsonify({'error': 'System or CampaignID header is required'}), 400
    
    races = GameElement.query.filter_by(element_type='race', system=system).all()
    # Return only the name field for listing (not full data) to reduce payload size
    return jsonify([{'name': r.name} for r in races])

@app.route('/api/races/<race_name>', methods=['GET'])
def get_race_info(race_name):
    # Determine the System in use: explicit override, then campaign, else warn
    system, campaign = resolve_system_from_request()
    if not system:
        app.logger.warning("System not provided and no CampaignID/system resolution for /api/races/<race_name>")
        return jsonify({'error': 'System or CampaignID header is required'}), 400
    
    game_element = GameElement.query.filter_by(name=race_name, element_type='race', system=system).first()
    if game_element:
        return jsonify(game_element.data)
    else:
        return jsonify({'error': 'Resource not found'}), 404

@app.route('/api/backgrounds', methods=['GET'])
def get_background_listing():
    # Determine the System in use: explicit override, then campaign, else warn
    system, campaign = resolve_system_from_request()
    if not system:
        app.logger.warning("System not provided and no CampaignID/system resolution for /api/backgrounds")
        return jsonify({'error': 'System or CampaignID header is required'}), 400
    
    try:
        backgrounds = GameElement.query.filter_by(element_type='character_background', system=system).all()
        app.logger.debug("Returning %d backgrounds for system %s", len(backgrounds), system)
        # Return only the name field for listing (not full data) to reduce payload size
        return jsonify([{'name': b.name} for b in backgrounds])
    except Exception:
        app.logger.exception("Error fetching backgrounds")
        return jsonify({'error': 'internal server error'}), 500

@app.route('/api/backgrounds/<background_name>', methods=['GET'])
def get_background_info(background_name):
    # Determine the System in use: explicit override, then campaign, else warn
    system, campaign = resolve_system_from_request()
    if not system:
        app.logger.warning("System not provided and no CampaignID/system resolution for /api/backgrounds/<background_name>")
        return jsonify({'error': 'System or CampaignID header is required'}), 400
    
    game_element = GameElement.query.filter_by(name=background_name, element_type='character_background', system=system).first()
    if game_element:
        return jsonify(game_element.data)
    else:
        return jsonify({'error': 'Resource not found'}), 404


## GET Character Profile
@app.route('/api/character', methods=['GET'])
@jwt_required()
def get_character():
    # app.logger.debug("Get Character Profile:", request.headers)
    try:
        username = get_jwt_identity()
        user = User.query.filter_by(username=username).first()
        campaignID = request.headers.get('CampaignID')
        
        app.logger.info("[DEBUG] GET /api/character - username=%s, campaignID=%s", username, campaignID)

        stmt = select(campaign_members.c.characterID).where(
            campaign_members.c.campaignID == campaignID, 
            campaign_members.c.userID == user.id
        )

        result = db.session.execute(stmt).first()

        characterID = result.characterID if result else None
        app.logger.info("[DEBUG] GET /api/character - characterID=%s", characterID)

        character = Character.query.filter_by(id=characterID).first()
        character_data = character.to_dict() if character else None
        app.logger.info("[DEBUG] GET /api/character - character data: %s", character_data)
        
        if character is None:
            app.logger.warning("[DEBUG] GET /api/character - Character not found for user in campaign")
            return jsonify({'error': 'Character not found for user in this campaign.'}), 404

        app.logger.info("[DEBUG] GET /api/character - Returning character: %s", character.character_name)
        return jsonify(character.to_dict()), 200

    except InvalidTokenError:
        app.logger.error("[DEBUG] GET /api/character - InvalidTokenError")
        return jsonify({'error': 'InvalidTokenError- GET /api/character'}), 401
    except ExpiredSignatureError:
        app.logger.error("[DEBUG] GET /api/character - ExpiredSignatureError")
        return jsonify({'error': 'Expired token'}), 401


## GET Character Profile by name (campaign-scoped)
@app.route('/api/character_by_name', methods=['GET'])
@jwt_required()
def get_character_by_name():
    """Return a character by name for the active campaign.

    Expects:
      - `CampaignID` header
      - `name` query param (character name)

    Only returns characters linked to the campaign via `campaign_members`.
    """
    try:
        campaign_id = request.headers.get('CampaignID')
        character_name = request.args.get('name')
        
        app.logger.debug("[DEBUG] GET /api/character_by_name - campaign_id=%s, name=%s", campaign_id, character_name)
        
        if not campaign_id:
            app.logger.warning("[DEBUG] GET /api/character_by_name - Missing CampaignID header")
            return jsonify({'error': 'CampaignID header is required'}), 400

        if not character_name:
            app.logger.warning("[DEBUG] GET /api/character_by_name - Missing name query param")
            return jsonify({'error': 'name query param is required'}), 400

        # Ensure the requested character is part of this campaign
        stmt = select(campaign_members.c.characterID).where(campaign_members.c.campaignID == campaign_id)
        character_ids = [row.characterID for row in db.session.execute(stmt) if row.characterID]
        app.logger.debug("[DEBUG] GET /api/character_by_name - Found %d characters in campaign", len(character_ids))
        
        if not character_ids:
            app.logger.warning("[DEBUG] GET /api/character_by_name - No characters found in campaign")
            return jsonify({'error': 'Character not found'}), 404

        character = Character.query.filter(
            Character.id.in_(character_ids),
            Character.character_name == character_name
        ).first()

        if not character:
            app.logger.warning("[DEBUG] GET /api/character_by_name - Character '%s' not found in campaign", character_name)
            return jsonify({'error': 'Character not found'}), 404

        app.logger.debug("[DEBUG] GET /api/character_by_name - Found character: %s (ID: %s)", character.character_name, character.id)
        return jsonify(character.to_dict()), 200
    except InvalidTokenError:
        app.logger.error("[DEBUG] GET /api/character_by_name - InvalidTokenError")
        return jsonify({'error': 'InvalidTokenError- GET /api/character_by_name'}), 401
    except ExpiredSignatureError:
        app.logger.error("[DEBUG] GET /api/character_by_name - ExpiredSignatureError")
        return jsonify({'error': 'Expired token'}), 401
    except Exception:
        app.logger.exception("[DEBUG] GET /api/character_by_name - Exception")
        return jsonify({'error': 'internal server error'}), 500

## Update a user's Character Profile
@app.route('/api/character', methods=['PUT'])
@jwt_required()
def update_character():
    try:
        data = request.json
        
        # If character ID is provided in payload, use it directly (for character switching)
        # Otherwise fall back to userID-based lookup (for original character)
        characterID = data.get('id')
        
        if not characterID:
            userID = request.headers.get('userID')
            campaignID = request.headers.get('CampaignID')

            # app.logger.debug("UPDATE CHARACTER- userID: %s", userID)
            # app.logger.debug("UPDATE CHARACTER- campaignID: %s", campaignID)

            stmt = select(campaign_members.c.characterID).where(
                campaign_members.c.campaignID == campaignID, 
                campaign_members.c.userID == userID
            )

            result = db.session.execute(stmt).first()
            characterID = result.characterID if result else None
        else:
            app.logger.debug("UPDATE CHARACTER- using character ID from payload: %s", characterID)

        character = Character.query.filter_by(id=characterID).first()

        if not character:
            return jsonify({'error': 'Character not found'}), 404

        requested_avatar_mode = data.get('avatar_mode')
        if requested_avatar_mode is not None and requested_avatar_mode not in {
            'initials', 'image', 'preset'
        }:
            return jsonify({'error': 'Invalid avatar mode'}), 400

        requested_avatar_preset = data.get('avatar_preset_key')
        if (
            requested_avatar_preset is not None
            and requested_avatar_preset
            and character_avatar_preset(requested_avatar_preset) is None
        ):
            return jsonify({'error': 'Invalid avatar preset'}), 400

        effective_avatar_mode = requested_avatar_mode or character.avatar_mode
        effective_avatar_preset = (
            requested_avatar_preset
            if requested_avatar_preset is not None
            else character.avatar_preset_key
        )
        if effective_avatar_mode == 'preset' and not effective_avatar_preset:
            return jsonify({'error': 'Choose a preloaded portrait first'}), 400

        # app.logger.debug("Character from database- %s", character.to_dict())
        # app.logger.debug("UPDATE CHARACTER- Character JSON for Updating keys: %s", list(data.keys()))
        # app.logger.debug("UPDATE CHARACTER- incoming Wealth: %s", data.get('Wealth'))

        # Hardcode the mapping
        character.system = data.get('system')
        character.Class = data.get('Class')
        character.Subclass = data.get('Subclass')
        character.Background = data.get('Background')
        character.Race = data.get('Race')
        character.Alignment = data.get('Alignment')
        # Safely coerce numeric fields to integers when present
        if data.get('ExperiencePoints') is not None:
            try:
                character.ExperiencePoints = int(data.get('ExperiencePoints'))
            except (TypeError, ValueError):
                character.ExperiencePoints = character.ExperiencePoints or 0

        if data.get('CurrentHitPoints') is not None:
            try:
                character.CurrentHitPoints = int(data.get('CurrentHitPoints'))
            except (TypeError, ValueError):
                character.CurrentHitPoints = character.CurrentHitPoints or 0

        # Temporary hit points (may not exist on older DBs yet)
        if data.get('TemporaryHitPoints') is not None:
            try:
                character.TemporaryHitPoints = int(data.get('TemporaryHitPoints'))
            except (TypeError, ValueError):
                character.TemporaryHitPoints = character.TemporaryHitPoints or 0

        ability_scores = data.get('abilityScores') or data.get('ability_scores') or {}

        def _get_score_obj(key):
            # Try several common casings for incoming keys (e.g., 'strength', 'Strength')
            if not isinstance(ability_scores, dict):
                return None
            for k in (key, key.lower(), key.capitalize(), key.title(), key.upper()):
                if k in ability_scores and ability_scores[k] is not None:
                    return ability_scores[k]
            return None

        def _to_int(val):
            try:
                return int(val)
            except (TypeError, ValueError):
                return 0

        character.strength = _to_int(_get_score_obj('strength'))
        character.dexterity = _to_int(_get_score_obj('dexterity'))
        character.constitution = _to_int(_get_score_obj('constitution'))
        character.intelligence = _to_int(_get_score_obj('intelligence'))
        character.wisdom = _to_int(_get_score_obj('wisdom'))
        character.charisma = _to_int(_get_score_obj('charisma'))

        wealth = data.get('Wealth', {})
        character.cp = int(wealth.get('cp')) if wealth.get('cp') else 0
        character.sp = int(wealth.get('sp')) if wealth.get('sp') else 0
        character.ep = int(wealth.get('ep')) if wealth.get('ep') else 0
        character.gp = int(wealth.get('gp')) if wealth.get('gp') else 0
        character.pp = int(wealth.get('pp')) if wealth.get('pp') else 0

        character.PersonalityTraits = data.get('PersonalityTraits')
        character.Ideals = data.get('Ideals')
        character.Bonds = data.get('Bonds')
        character.Flaws = data.get('Flaws')
        character.Feats = json.dumps(data.get('Feats', []))
        # Persist Proficiencies (ensure we store a clean list)
        profs = data.get('Proficiencies') or data.get('proficiencies') or []
        cleaned_profs = []
        if isinstance(profs, str):
            try:
                parsed = json.loads(profs)
                if isinstance(parsed, list):
                    profs = parsed
                else:
                    profs = [parsed]
            except Exception:
                profs = [profs]

        if isinstance(profs, (list, tuple)):
            cleaned_profs = [p for p in profs if p and str(p).strip()]

        character.Proficiencies = json.dumps(cleaned_profs)


        if requested_avatar_mode is not None:
            character.avatar_mode = requested_avatar_mode

        if data.get('avatar_color') is not None:
            character.avatar_color = data.get('avatar_color')

        if data.get('avatar_text_color') is not None:
            character.avatar_text_color = data.get('avatar_text_color')

        if requested_avatar_preset is not None:
            character.avatar_preset_key = requested_avatar_preset

        if data.get('avatar_shape') is not None:
            character.avatar_shape = data.get('avatar_shape')

        # allow explicit null
        if 'avatar_frame_color' in data:
            character.avatar_frame_color = data.get('avatar_frame_color')

        db.session.commit()
        app.logger.debug("Updated character: %s", character.to_dict())
        return jsonify(character.to_dict()), 200

    except InvalidTokenError:
        return jsonify({'error': 'InvalidTokenError- PUT /api/character'}), 401
    except ExpiredSignatureError:
        return jsonify({'error': 'Expired token'}), 401


@app.route("/api/character/avatar", methods=["POST"])
@jwt_required()
def upload_character_avatar():
    if request.content_length and request.content_length > 5 * 1024 * 1024:
        return jsonify({"error": "Avatar uploads must be 5 MB or smaller."}), 413

    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()
    if user is None:
        return jsonify({"error": "User not found."}), 404

    campaign_id = request.headers.get("CampaignID")
    if campaign_id is None:
        return jsonify({"error": "Campaign ID not provided in request header."}), 400

    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaign_id,
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()
    if result is None:
        return jsonify({"error": "Character not found."}), 404

    character = Character.query.filter_by(id=result.characterID).first()
    if character is None:
        return jsonify({"error": "Character not found."}), 404

    file = request.files.get("avatar")
    if not file or not file.filename:
        return jsonify({"error": "No avatar file uploaded."}), 400

    if not allowed_avatar_file(file.filename):
        return jsonify({"error": "Unsupported file type."}), 400

    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[1].lower()
    unique_stem = f"{character.id}_{uuid4().hex}"
    filename = f"{unique_stem}.{ext}"
    thumb_filename = f"{unique_stem}_thumb.webp"

    user_root, thumb_root = ensure_avatar_dirs(user.id)
    image_path = user_root / filename
    thumb_path = thumb_root / thumb_filename

    file.save(image_path)
    make_avatar_thumbnail(image_path, thumb_path)

    image_url, thumb_url = build_avatar_urls(user.id, filename, thumb_filename)

    character.avatar_mode = "image"
    character.avatar_image_url = image_url
    character.avatar_thumb_url = thumb_url

    db.session.commit()


    return jsonify({
        "message": "Avatar uploaded successfully.",
        "avatar": {
            "mode": character.avatar_mode,
            "initials": None,
            "color": character.avatar_color,
            "text_color": character.avatar_text_color,
            "image_url": character.avatar_image_url,
            "thumb_url": character.avatar_thumb_url,
            "preset_key": character.avatar_preset_key,
            "shape": character.avatar_shape,
            "frame_color": character.avatar_frame_color,
        },
        "avatar_image_url": character.avatar_image_url,
        "avatar_thumb_url": character.avatar_thumb_url,
        "avatar_mode": character.avatar_mode,
    }), 200


@app.route('/api/users', methods=['GET'])
@jwt_required()
def get_users():
    campaignID = request.headers.get('CampaignID')
    users = User.query.join(campaign_members, User.id == campaign_members.c.userID).filter(campaign_members.c.campaignID == campaignID).all()
    return jsonify({'users': [user.character_name for user in users]})

@app.route('/api/players', methods=['GET'])
@jwt_required()
def get_players():
    app.logger.debug("GET PLAYERS- Called")
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        app.logger.error("User not found.")
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')

    if campaignID is None:
        app.logger.error("Campaign ID not provided in the request header: %s", request.headers)
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400
    
    # Find the character associated with the user and the campaign
    stmt = select(campaign_members.c.characterID, campaign_members.c.userID).where(
        campaign_members.c.campaignID == campaignID
    )
    result = db.session.execute(stmt).all()

    # Separate the character IDs and user IDs into two lists
    characterIDs, userIDs = zip(*result)

    # Get the DM's user ID
    dm_id = Campaign.query.filter_by(id=campaignID).first().dm_id

    # Filter out invalid character IDs
    valid_characterIDs = [characterID for characterID in characterIDs if characterID != user.id and characterID != dm_id and characterID is not None]

    # Get the players for the valid character IDs
    players = [User.query.get(userID) for userID in userIDs]
    app.logger.debug("GET PLAYERS- players: %s", players)

    # Get the character name for each player
    players_info = []
    for i, characterID in enumerate(characterIDs):
        player = players[i]
        if player is not None:
            # app.logger.debug("player: %s", player.to_dict())
            character = Character.query.filter_by(id=characterID).first()
            character_name = character.character_name if character else "DM"
            players_info.append({
                'username': player.username,
                'character_name': character_name,
                'id': characterID,
                'userID': player.id  # Add userID to the response
            })

    return jsonify({'players': players_info if players_info else []})

## GET basic item info for the DM and POST new items
@app.route('/api/items', methods=['GET', 'POST'])
@jwt_required()
def items():
    if request.method == 'GET':
        app.logger.info("FLASK- Getting items for the DM")
        try:
            items = Item.query.all()

            item_data = []
            # item_data_list = []

            for item in items:
                item_data.append(item.to_dict())

            #     if item.type == 'Weapon':
            #         weapon = Weapon.query.filter_by(itemID=item.id).first()
            #         if weapon:
            #             item_data.update(weapon.to_dict())
            #     elif item.type == 'Armor':
            #         armor = Armor.query.filter_by(itemID=item.id).first()
            #         if armor:
            #             item_data.update(armor.to_dict())
            #     elif item.type == 'MountVehicle':
            #         mountVehicle = MountVehicle.query.filter_by(itemID=item.id).first()
            #         if mountVehicle:
            #             item_data.update(mountVehicle.to_dict())
            #     # elif item.type in ['Ring', 'Wand', 'Scroll']:
            #     #     magic_item = SpellItem.query.filter_by(itemID=item.id).first()
            #     #     if magic_item:
            #     #         item_data.update(magic_item.to_dict())

            #     item_data_list.append(item_data)

            # return jsonify({'items': item_data_list}), 200
            return jsonify({'items': item_data}), 200

        except Exception as e:
            app.logger.error(f"Error getting items: {e}")
            return jsonify({'error': 'Server error: ' + str(e)}), 500

    elif request.method == 'POST':
        data = request.get_json()
        # print("POST to items- data:", data)
        app.logger.info("POST to items- data: %s", data)

        try:
            # Validate required fields
            required_fields = ['name', 'type', 'cost', 'currency', 'weight', 'description']
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")
            
            name = data.get('name')
            type = data.get('type')
            cost = data.get('cost')
            currency = data.get('currency')
            weight = data.get('weight')
            description = data.get('description')
            
            # Define the range for PostgreSQL INTEGER type
            INTEGER_MIN = -2147483648
            INTEGER_MAX = 2147483647
            
            # Validate cost and weight
            if not (INTEGER_MIN <= int(cost) <= INTEGER_MAX):
                raise ValueError(f"Cost value {cost} is out of range for type integer. Must be between {INTEGER_MIN} and {INTEGER_MAX}")
            if not (INTEGER_MIN <= float(weight) <= INTEGER_MAX):
                raise ValueError(f"Weight value {weight} is out of range for type integer. Must be between {INTEGER_MIN} and {INTEGER_MAX}")
            
            item = Item(name=name, type=type, cost=cost, currency=currency, weight=weight, description=description)
            db.session.add(item)
            db.session.flush()
            app.logger.debug(f"New item ID: {item.id}")

        
            if type == 'Weapon':
                weapon = Weapon.query.filter_by(itemID=item.id).first()
                damage = data.get('damage')
                damage_type = data.get('damageType')
                weapon_type = data.get('weaponType')
                weapon_range = data.get('weaponRange')
                if weapon:
                    weapon.damage = damage
                    weapon.damage_type = damage_type
                    weapon.weapon_type = weapon_type
                    weapon.weapon_range = weapon_range
                else:
                    weapon = Weapon(itemID=item.id, damage=damage, damage_type=damage_type, weapon_type=weapon_type, weapon_range=weapon_range)
                    db.session.add(weapon)
                # db.session.commit()
            elif type == 'Armor':
                armor = Armor.query.filter_by(itemID=item.id).first()
                ac = data.get('ac')
                armor_type = data.get('armorType')
                stealth_disadvantage = data.get('stealthDisadvantage', False)
                strength_needed = data.get('strengthNeeded', None)
            
                # Validate strength_needed
                if strength_needed is not None:
                    try:
                        strength_needed = int(strength_needed)
                    except ValueError:
                        strength_needed = None  # Set to None if not a valid integer
            
                if armor:
                    # Update existing record
                    armor.armor_class = ac
                    armor.armor_type = armor_type
                    armor.stealth_disadvantage = stealth_disadvantage
                    armor.strength_needed = strength_needed
                else:
                    # Insert new record
                    armor = Armor(
                        itemID=item.id,
                        armor_class=ac,
                        armor_type=armor_type,
                        stealth_disadvantage=stealth_disadvantage,
                        strength_needed=strength_needed
                    )
                    db.session.add(armor)
                # db.session.commit()
            # elif type in ['Ring', 'Wand', 'Scroll']:
            #     spellItem = SpellItem.query.filter_by(itemID=item.id).first()
            #     spell = data.get('spell')
            #     charges = data.get('charges')
            #     if spellItem:
            #         spellItem.spell = spell
            #         spellItem.charges = charges
            #     else:
            #         magic_item = SpellItem(itemID=item.id, spell=spell, charges=charges)
            #         db.session.add(magic_item)
            #     db.session.commit()
            elif type == 'MountVehicle':  # Handle MountVehicle items
                mountVehicle = MountVehicle.query.filter_by(itemID=item.id).first()
                speed = data.get('speed')
                speed_unit = data.get('speedUnit')
                capacity = data.get('capacity')
                if mountVehicle:
                    mountVehicle.speed = speed
                    mountVehicle.speed_unit = speed_unit
                    mountVehicle.capacity = capacity
                else:
                    mount_vehicle = MountVehicle(itemID=item.id, speed=speed, speed_unit=speed_unit, capacity=capacity)
                    db.session.add(mount_vehicle)
                db.session.commit()
            
            db.session.commit()
            return jsonify({'item': item.to_dict()}), 201
        except IntegrityError as ie:
            # Rollback the session if any operation fails
            db.session.rollback()
            app.logger.error(f"Integrity Error while attempting to create new item: {ie}")
            return jsonify({'message': str(ie)}), 400
        except ValueError as ve:
            app.logger.error(f"Validation error: {ve}")
            return jsonify({'message': str(ve)}), 400
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error creating item: {e}")
            return jsonify({'error': 'Server error: ' + str(e)}), 500


## Update details for an Item entry
@app.route('/api/items/<int:itemID>', methods=['PUT'])
@jwt_required()
def update_item(itemID):
    data = request.get_json()
    item = Item.query.get(itemID)
    # item = Item.query.filter_by(id=itemID).first()
    if not item:
        return jsonify({'message': 'Item not found!'}), 404
    item.name = data.get('name', item.name)
    item.type = data.get('type', item.type)
    item.cost = data.get('cost', item.cost)
    item.currency = data.get('currency', item.currency)
    item.description = data.get('description', item.description)
    db.session.commit()
    return jsonify({'message': 'Item updated!', 'item': item.to_dict()})

## Delete a specific Item entry
@app.route('/api/items/<int:itemID>', methods=['DELETE'])
@jwt_required()
def delete_item(itemID):
    app.logger.info("Deleting Item: %s", itemID)
    item = Item.query.get(itemID)
    if not item:
        return jsonify({'message': 'Item not found!'}), 404
    
    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({'message': 'Item deleted!'})
    except Exception as e:
        app.logger.error(f"Error deleting item: {e}")
        db.session.rollback()
        return jsonify({'error': 'Server error: ' + str(e)}), 500
    
## Upload CSV for bulk item creation
@app.route('/api/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        return 'No file part', 400
    file = request.files['file']
    csv_data = csv.reader(file.stream)
    items = [row for row in csv_data]

## Save items from a CSV
@app.route('/api/save_items', methods=['POST'])
def save_items():
    data = request.get_json()

    if not data or not isinstance(data, dict):
        return jsonify(error='Invalid JSON'), 400

    items = data.get('items')
    if not items or not isinstance(items, list):
        return jsonify(error='Invalid items'), 400

    try:
        for item in items:
            # Map fields for the Item model using fuzzy matching
            item = map_fields(item, Item)
            app.logger.debug("SAVE CSV- Mapped item: %s", item)

            if not all(k in item for k in ('name', 'type', 'cost', 'currency')):  # Match mapped keys
                return jsonify(error='Missing item fields'), 400

            existing_item = Item.query.filter_by(name=item['name']).first()

            if existing_item is None:
                new_item = Item(name=item['name'], type=item['type'], cost=item['cost'], currency=item['currency'],
                                weight=item.get('weight'), description=item.get('description'))
                app.logger.debug("SAVE CSV- Adding new item: %s", new_item.to_dict())
                db.session.add(new_item)
                db.session.commit()

                item_name = item['name']
                item_type = item['type']    # Save the item type for further processing cause it's about to get removed from the item dict
                itemID = new_item.id

                ## Remove the fields that are already saved in the Item model
                item.pop('name', None)
                item.pop('type', None)
                item.pop('cost', None)
                item.pop('currency', None)
                item.pop('weight', None)
                item.pop('description', None)

                if item_type == 'Weapon':
                    app.logger.debug("SAVE CSV- %s is Weapon", item_name)
                    # Map fields for the Weapon model
                    weapon_data = map_fields(item, Weapon)
                    app.logger.debug("SAVE CSV- Weapon Data: %s", weapon_data)
                    weapon = Weapon(itemID=itemID, damage=weapon_data.get('damage'),
                                    damage_type=weapon_data.get('damage_type'),
                                    weapon_type=weapon_data.get('weapon_type'),
                                    weapon_range=weapon_data.get('range'))
                    db.session.add(weapon)

                elif item_type == 'Armor':
                    app.logger.debug("SAVE CSV- %s is Armor", item_name)
                    # Map fields for the Armor model
                    armor_data = map_fields(item, Armor)
                    app.logger.debug("SAVE CSV- Armor Data: %s", armor_data)
                    armor = Armor(itemID=itemID, armor_class=armor_data.get('armor_class'),
                                  armor_type=armor_data.get('armor_type'),
                                  stealth_disadvantage=armor_data.get('stealth'),
                                  strength_needed=armor_data.get('strength'))
                    db.session.add(armor)

                elif item_type in ['Ring', 'Wand', 'Scroll']:
                    app.logger.debug("SAVE CSV- %s is a Magic Item", item_name)
                    # Map fields for the SpellItem model
                    spell_data = map_fields(item, SpellItem)
                    magic_item = SpellItem(itemID=itemID, spell=spell_data.get('spell'),
                                           charges=spell_data.get('charges'))
                    db.session.add(magic_item)

                elif item_type == 'Mounts and Vehicles':
                    app.logger.debug("SAVE CSV- %s is a Mount or Vehicle", item_name)
                    # Map fields for the MountVehicle model
                    mount_data = map_fields(item, MountVehicle)
                    mount_vehicle = MountVehicle(itemID=itemID, speed=mount_data.get('speed'),
                                                 speed_unit=mount_data.get('speed_unit'),
                                                 capacity=mount_data.get('capacity'),
                                                 vehicle_type=mount_data.get('vehicle_type'))
                    db.session.add(mount_vehicle)

                db.session.commit()
            else:
                app.logger.debug("SAVE CSV- Item %s already exists in the database. Skipping...", item['name'])

        emit('items_updated')
        return jsonify(message='Items saved'), 200

    except Exception as e:
        app.logger.exception("Failed to save items")
        return jsonify(error=str(e)), 400

@app.route('/api/inventory', methods=['GET', 'POST'], endpoint='inventory')
@jwt_required()
def inventory():
    if request.method == 'GET':
        app.logger.info("**** Getting Inventory ****")
        # app.logger.info("GET INVENTORY- headers: %s", request.headers)

        if request.headers.get('Character-ID'):
            inventory_items = InventoryItem.query.filter_by(characterID=request.headers.get('Character-ID')).all()
            inventory = []

            for inventory_item in inventory_items:
                item = Item.query.get(inventory_item.itemID)
                if item is not None:
                    item_details = {
                        'id': inventory_item.itemID,
                        'name': inventory_item.name,
                        'type': item.type,
                        'cost': item.cost,
                        'currency': item.currency,
                        'quantity': inventory_item.quantity,
                        'description': item.description,
                        'weight': item.weight,
                        'equipped': inventory_item.equipped if inventory_item.equipped is not None else False
                    }

                    # Get additional item details based on item type
                    if item.type == 'Weapon':
                        weapon = Weapon.query.get(item.id)
                        if weapon is not None:
                            item_details.update({
                                'damage': weapon.damage,
                                'damage_type': weapon.damage_type,
                                'weapon_range': weapon.weapon_range
                            })
                    elif item.type == 'Armor':
                        armor = Armor.query.get(item.id)
                        if armor is not None:
                            item_details.update({
                                'armor_class': armor.armor_class,
                                'armor_type': armor.armor_type,
                                'strength_needed': armor.strength_needed,
                                'stealth_disadvantage': armor.stealth_disadvantage
                            })
                    elif item.type == 'SpellItem':
                        spellItem = SpellItem.query.get(item.id)
                        if spellItem is not None:
                            item_details.update({
                                'charges': spellItem.charges,
                                'spell_id': spellItem.spell_id
                            })
                    elif item.type == 'MountVehicle':
                        mountVehicle = MountVehicle.query.get(item.id)
                        if mountVehicle is not None:
                            item_details.update({
                                'speed': mountVehicle.speed,
                                'speed_unit': mountVehicle.speed_unit,
                                'capacity': mountVehicle.capacity
                            })

                    inventory.append(item_details)

            return jsonify({'inventory': inventory})

        else:    
            username = get_jwt_identity()
            user = User.query.filter_by(username=username).first()

            if user is None:
                return jsonify({'error': 'User not found.'}), 404
            
            app.logger.info("GET INVENTORY- user from JWT: %s", user.to_dict())

            campaignID = request.headers.get('CampaignID')

            if campaignID is None:
                return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400
            
            app.logger.info("GET INVENTORY- campaignID: %s", campaignID)
            
            # Find the character associated with the user and the campaign
            stmt = select(campaign_members.c.characterID).where(
                campaign_members.c.campaignID == campaignID, 
                campaign_members.c.userID == user.id
            )
            result = db.session.execute(stmt).first()

            if result is None:
                return jsonify({'error': 'Character not found.'}), 404

            characterID = result.characterID if result else None

            app.logger.debug("GET INVENTORY- characterID based on JWT: %s", characterID)

            inventory_items = InventoryItem.query.filter_by(characterID=characterID).all()
            inventory = []

            for inventory_item in inventory_items:
                item = Item.query.get(inventory_item.itemID)
                if item is not None:
                    item_details = {
                        'id': inventory_item.itemID,
                        'name': inventory_item.name,
                        'type': item.type,
                        'cost': item.cost,
                        'currency': item.currency,
                        'quantity': inventory_item.quantity,
                        'description': item.description,
                        'weight': item.weight,
                        'equipped': inventory_item.equipped if inventory_item.equipped is not None else False
                    }

                    # Get additional item details based on item type
                    if item.type == 'Weapon':
                        weapon = Weapon.query.get(item.id)
                        if weapon is not None:
                            item_details.update({
                                'damage': weapon.damage,
                                'damage_type': weapon.damage_type,
                                'weapon_range': weapon.weapon_range
                            })
                    elif item.type == 'Armor':
                        armor = Armor.query.get(item.id)
                        if armor is not None:
                            item_details.update({
                                'armor_class': armor.armor_class,
                                'armor_type': armor.armor_type,
                                'strength_needed': armor.strength_needed,
                                'stealth_disadvantage': armor.stealth_disadvantage
                            })
                    elif item.type == 'SpellItem':
                        spellItem = SpellItem.query.get(item.id)
                        if spellItem is not None:
                            item_details.update({
                                'charges': spellItem.charges,
                                'spell_id': spellItem.spell_id
                            })
                    elif item.type == 'MountVehicle':
                        mountVehicle = MountVehicle.query.get(item.id)
                        if mountVehicle is not None:
                            item_details.update({
                                'speed': mountVehicle.speed,
                                'speed_unit': mountVehicle.speed_unit,
                                'capacity': mountVehicle.capacity
                            })

                    inventory.append(item_details)

            return jsonify({'inventory': inventory})

    elif request.method == 'POST':
        print("**** Giving Item to Player ****")
        data = request.get_json()
        app.logger.debug("POST INVENTORY- data: %s", data)

        current_user = User.query.filter_by(username=get_jwt_identity()).first()

        if 'characterID' in data and current_user.character_name != 'DM':
            return jsonify({'message': 'Only DMs can issue items to other players!'}), 403
        characterID = data['characterID']

        character = Character.query.filter_by(id=characterID).first()
        app.logger.debug("POST ITEM to Player- character:", character.character_name)
        if character is None:
            return jsonify({'message': 'Character not found'}), 404

        item = Item.query.get(data['itemID'])
        print("FLASK- item:", item.name)
        if item is None:
            return jsonify({'message': 'Item not found'}), 404

        inventory_item = InventoryItem.query.filter_by(characterID=character.id, itemID=item.id).first()
        if inventory_item:
            inventory_item.quantity += int(data['quantity'])
        else:
            inventory_item = InventoryItem(characterID=character.id, itemID=item.id, quantity=data['quantity'])
            db.session.add(inventory_item)
        db.session.commit()

        print("FLASK- Emitting inventory update")
        emit('inventory_update', {'character_name': character.character_name, 'itemID': data['itemID'], 'quantity': data['quantity']}, to=character.user.sid)

        return jsonify({'message': 'Item added to inventory!'})


@app.route('/api/inventory/<int:itemID>', methods=['GET'])
@jwt_required()
def get_inventoryItem(itemID):
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')

    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400
    
    # Get the DM's user ID
    dm_id = Campaign.query.filter_by(id=campaignID).first().dm_id
    admin_id = Campaign.query.filter_by(id=campaignID).first().owner_id
    app.logger.debug("Admin ID: %s", admin_id)

    if user.id != dm_id and user.id != admin_id:
        # Find the character associated with the user and the campaign
        stmt = select(campaign_members.c.characterID).where(
            campaign_members.c.campaignID == campaignID, 
            campaign_members.c.userID == user.id
        )
        result = db.session.execute(stmt).first()

        if result is None:
            return jsonify({'error': 'Character not found.'}), 404

        characterID = result.characterID if result else None

        inventory_item = InventoryItem.query.filter_by(characterID=characterID, itemID=itemID).first()
        if not inventory_item:
            return jsonify({'message': 'Item not found in inventory!'}), 404

        item = Item.query.get(itemID)

        if item is None:
            return jsonify({'message': 'Item not found!'}), 404

        item_details = {
            'id': itemID,
            'name': inventory_item.name,
            'type': item.type,
            'cost': item.cost,
            'currency': item.currency,
            'quantity': inventory_item.quantity,
            'description': item.description,
            'weight': item.weight,
            'equipped': inventory_item.equipped if inventory_item.equipped is not None else False
        }

    else: ## If the user is the DM
        item = Item.query.get(itemID)

        if item is None:
            return jsonify({'message': 'Item not found!'}), 404

        item_details = {
            'id': itemID,
            'name': item.name,
            'type': item.type,
            'cost': item.cost,
            'currency': item.currency,
            'description': item.description,
            'weight': item.weight,
        }

    # Get additional item details based on item type
    if item.type == 'Weapon':
        weapon = Weapon.query.get(item.id)
        if weapon is not None:
            item_details.update({
                'damage': weapon.damage,
                'damage_type': weapon.damage_type,
                'weapon_range': weapon.weapon_range
            })
    elif item.type == 'Armor':
        armor = Armor.query.get(item.id)
        if armor is not None:
            item_details.update({
                'armor_class': armor.armor_class,
                'armor_type': armor.armor_type,
                'strength_needed': armor.strength_needed,
                'stealth_disadvantage': armor.stealth_disadvantage
            })
    elif item.type == 'SpellItem':
        spellItem = SpellItem.query.get(item.id)
        if spellItem is not None:
            item_details.update({
                'charges': spellItem.charges,
                'spell_id': spellItem.spell_id
            })
    elif item.type == 'MountVehicle':
        mountVehicle = MountVehicle.query.get(item.id)
        if mountVehicle is not None:
            item_details.update({
                'speed': mountVehicle.speed,
                'speed_unit': mountVehicle.speed_unit,
                'capacity': mountVehicle.capacity
            })


    return jsonify({'item': item_details})


## When a player wants to nickname or equip an item from their inventory
@app.route('/api/inventory/<int:itemID>', methods=['PUT'])
@jwt_required()
def update_inventoryItem(itemID):
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')

    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400
    
    # Find the character associated with the user and the campaign
    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID, 
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return jsonify({'error': 'Character not found.'}), 404

    characterID = result.characterID if result else None

    inventory_item = InventoryItem.query.filter_by(characterID=characterID, itemID=itemID).first()
    if not inventory_item:
        return jsonify({'message': 'Item not found in inventory!'}), 404

    data = request.get_json()
    nickname = data.get('name')
    equipped = data.get('equipped')

    app.logger.info("UPDATE INVENTORY ITEM- nickname: %s", nickname)

    if nickname is not None:
        if nickname == "None":
            # Populate with the original item name
            original_item = Item.query.filter_by(id=inventory_item.itemID).first()
            if original_item:
                app.logger.debug("Original item found: %s", original_item.name)
                inventory_item.name = original_item.name
            else:
                app.logger.error("Original item not found for itemID: %s", inventory_item.itemID)
        else:
            inventory_item.name = nickname
    if equipped is not None:
        inventory_item.equipped = equipped

    db.session.add(inventory_item)
    db.session.commit()
    return jsonify({'message': 'Item updated!'})

@app.route('/api/inventory/<int:itemID>', methods=['DELETE'])
@jwt_required()
def drop_item(itemID):
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'User not found.'}), 404
    
    app.logger.info("DROP ITEM- user from JWT: %s", user.to_dict())

    campaignID = request.headers.get('CampaignID')

    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400
    
    app.logger.info("DROP ITEM- campaignID: %s", campaignID)
    
    # Find the character associated with the user and the campaign
    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID, 
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return jsonify({'error': 'Character not found.'}), 404

    characterID = result.characterID if result else None

    app.logger.debug("DROP ITEM- characterID based on JWT: %s", characterID)
    
    app.logger.debug("DROP ITEM- campaignID: %s", campaignID)
    app.logger.debug("DROP ITEM- characterID: %s", characterID)

    character = Character.query.filter_by(id=characterID).first()
    
    if not character:
        return jsonify({'message': 'Character not found!'}), 404
    
    inventory_item = InventoryItem.query.filter_by(characterID=characterID, itemID=itemID).first()
    if not inventory_item:
        return jsonify({'message': 'Item not found in inventory!'}), 404

    drop_quantity = request.get_json().get('quantity', 1)
    drop_quantity = int(drop_quantity)
    
    if inventory_item.quantity > drop_quantity:
        inventory_item.quantity -= drop_quantity
    else:
        db.session.delete(inventory_item)
    
    db.session.commit()
    return jsonify({'message': 'Item dropped!'})

@app.route('/api/equipment', methods=['GET'])
@jwt_required()
def get_equipment():
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    campaignID = request.headers.get('CampaignID')

    print('Equipment: campaignID:', campaignID)
    print("Equipment: userID:", user.id)

    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID, 
        campaign_members.c.userID == user.id
    )

    result = db.session.execute(stmt).first()

    characterID = result.characterID if result else None

    equippedItems = InventoryItem.query.filter_by(characterID=characterID, equipped=True).all()

    # Convert the SQLAlchemy objects to dictionaries
    equippedItems = [item.to_dict() for item in equippedItems]

    return jsonify({'equipment': equippedItems})


##************************##
## **   Journal stuff  ** ##
##************************##
def get_user_and_character_for_campaign():
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return None, None, jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')
    if campaignID is None:
        return None, None, jsonify({'error': 'Campaign ID not provided in the request header.'}), 400

    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID,
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return user, None, jsonify({'error': 'Character not found.'}), 404

    return user, result.characterID, int(campaignID), None

@app.route('/api/journal', methods=['POST'])
@jwt_required()
def create_journal_entry():
    data = request.get_json() or {}
    if 'title' not in data or 'entry' not in data:
        return jsonify({'message': 'Title and Entry are required!'}), 400

    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()
    if user is None:
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')
    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400

    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID,
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return jsonify({'error': 'Character not found.'}), 404

    characterID = result.characterID
    journal_date = data.get('journal_date')

    calendar = Calendar.query.filter_by(campaign_id=campaignID).first()

    new_journal_entry = Journal(
        userID=user.id,
        campaignID=campaignID,
        characterID=characterID,
        title=data['title'],
        entry=data['entry'],
        date_created=datetime.utcnow(),
        date_modified=datetime.utcnow(),
        calendar_id=calendar.id if (journal_date and calendar) else None,
        journal_year=journal_date.get('year') if journal_date else None,
        journal_month_index=journal_date.get('month_index') if journal_date else None,
        journal_day=journal_date.get('day') if journal_date else None,
        journal_hour=journal_date.get('hour') if journal_date else None,
        journal_minute=journal_date.get('minute') if journal_date else None,
    )

    db.session.add(new_journal_entry)
    db.session.commit()

    return jsonify({
        'message': 'New journal entry created!',
        'entry': new_journal_entry.to_dict()
    }), 201

@app.route('/api/journal', methods=['GET'])
@jwt_required()
def get_journal_entries():
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')
    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400

    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID,
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return jsonify({'error': 'Character not found.'}), 404

    characterID = result.characterID

    entries = Journal.query.filter_by(characterID=characterID).order_by(Journal.date_created.desc()).all()
    return jsonify({'entries': [entry.to_dict() for entry in entries]})


@app.route('/api/journal/<entry_id>', methods=['PUT'])
@jwt_required()
def update_journal_entry(entry_id):
    data = request.get_json() or {}
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')
    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400

    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID,
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return jsonify({'error': 'Character not found.'}), 404

    characterID = result.characterID
    entry = Journal.query.filter_by(id=entry_id, characterID=characterID).first()

    if entry is None:
        return jsonify({'message': 'Journal entry not found'}), 404

    if 'title' in data:
        entry.title = data['title']
    if 'entry' in data:
        entry.entry = data['entry']

    journal_date = data.get('journal_date')
    if journal_date:
        calendar = Calendar.query.filter_by(campaign_id=campaignID).first()
        entry.calendar_id = calendar.id if calendar else None
        entry.journal_year = journal_date.get('year')
        entry.journal_month_index = journal_date.get('month_index')
        entry.journal_day = journal_date.get('day')
        entry.journal_hour = journal_date.get('hour')
        entry.journal_minute = journal_date.get('minute')
    else:
        entry.calendar_id = None
        entry.journal_year = None
        entry.journal_month_index = None
        entry.journal_day = None
        entry.journal_hour = None
        entry.journal_minute = None

    entry.date_modified = datetime.utcnow()

    db.session.commit()
    return jsonify({
        'message': 'Journal entry updated',
        'entry': entry.to_dict()
    }), 200


@app.route('/api/journal/<entry_id>', methods=['DELETE'])
@jwt_required()
def delete_journal_entry(entry_id):
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify({'error': 'User not found.'}), 404

    campaignID = request.headers.get('CampaignID')

    if campaignID is None:
        return jsonify({'error': 'Campaign ID not provided in the request header.'}), 400
    
    # Find the character associated with the user and the campaign
    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID, 
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()

    if result is None:
        return jsonify({'error': 'Character not found.'}), 404

    characterID = result.characterID if result else None

    entry = Journal.query.filter_by(id=entry_id, characterID=characterID).first()

    if entry is None:
        return jsonify({'message': 'Journal entry not found'}), 404

    db.session.delete(entry)
    db.session.commit()
    return jsonify({'message': 'Journal entry deleted'}), 200


## Library Stuff
@app.route('/api/library', methods=['GET', 'POST'])
def library():
    campaign_id = request.headers.get('CampaignID')
    if not campaign_id:
        return jsonify({'error': 'Campaign ID is required'}), 400

    if request.method == 'GET':
        # Query the database for all documents
        documents = Document.query.filter_by(campaignID=campaign_id).all()
        app.logger.debug('Found %d documents in the database', len(documents))
        
        # Construct the file information
        file_info = []
        for document in documents:
            fileName, fileType = os.path.splitext(document.name)
            displayName = fileName.replace("_", " ")
            file_info.append({
                'name': displayName,
                'type': fileType[1:],  # fileType[1:] to remove the leading dot
                'originalName': document.name,
                'id': document.id  # Include the ID for future reference
            })
        
        return { 'files': file_info }, 200

    elif request.method == 'POST':
        # Save the uploaded file to the Documents table        
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        new_file = Document(
            name=file.filename,
            data=file.read(),
            mimetype=file.mimetype,
            campaignID=campaign_id
        )
        db.session.add(new_file)
        db.session.commit()

        # emit an event to all connected clients
        emit('library_update')

        return { 'file': { 'name': file.filename } }, 201

@app.route('/api/library/<int:file_id>', methods=['GET'])
def get_file_by_id(file_id):
    app.logger.debug("GET FILE BY ID: %s", file_id)

    campaign_id = request.headers.get('CampaignID')
    # app.logger.debug("GET FILE BY ID- headers: %s", request.headers)
    if not campaign_id:
        app.logger.error("GET FILE BY ID- Campaign ID is required")
        return jsonify({'error': 'Campaign ID is required'}), 400
    else:
        app.logger.debug("GET FILE BY ID- campaignID: %s", campaign_id)

    try:
        # Log the request for the file
        app.logger.debug('Getting file with ID %d from the database', file_id)

        # Query the database for the document
        document = Document.query.filter_by(id=file_id, campaignID=campaign_id).first()

        if document is None:
            app.logger.error('File not found in the database: %d', file_id)
            return jsonify({'error': 'File not found'}), 404

        # Send the requested file
        return send_file(
            io.BytesIO(document.data),
            mimetype=document.mimetype,
            as_attachment=True,
            download_name=document.name
        )
    except Exception as e:
        app.logger.error('Error getting file with ID %d: %s', file_id, str(e))
        return jsonify({'error': 'Server error: ' + str(e)}), 500

@app.route('/api/library/<int:file_id>', methods=['DELETE'])
def delete_file_by_id(file_id):
    campaign_id = request.headers.get('CampaignID')
    if not campaign_id:
        return jsonify({'error': 'Campaign ID is required'}), 400

    try:
        # Log the request for the file
        app.logger.debug('Deleting file with ID %d from the database', file_id)

        # Query the database for the document
        document = Document.query.filter_by(id=file_id, campaignID=campaign_id).first()

        if document is None:
            app.logger.error('File not found in the database: %d', file_id)
            return jsonify({'error': 'File not found'}), 404

        # Delete the document
        db.session.delete(document)
        db.session.commit()

        # emit an event to all connected clients
        emit('library_update')

        return jsonify({'message': 'File deleted successfully'})
    except Exception as e:
        app.logger.error('Error deleting file with ID %d: %s', file_id, str(e))
        return jsonify({'error': 'Server error: ' + str(e)}), 500


##************************##
## **      Spells      ** ##
##************************##
@app.route('/api/spellbook', methods=['GET'])
@jwt_required()
def get_spellbook():
    ## Get a player's spellbook
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    if not character:
        return jsonify({"error": "Character not found"}), 404

    spellbook_items = Spellbook.query.filter_by(characterID=character.id).all()
    return jsonify({"spellbook": [item.to_dict() for item in spellbook_items]})

@app.route('/api/spells', methods=['GET'])
@jwt_required()
def get_all_spells():
    ## Get all the defined spells for the DM
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    if character.character_name != 'DM':
        return jsonify({"error": "Unauthorized"}), 403

    spells = Spell.query.all()
    return jsonify([spell.to_dict() for spell in spells])

@app.route('/api/prepared_spells', methods=['GET'])
@jwt_required()
def get_prepared_spells():
    try:
        campaignID = request.headers.get('CampaignID')
        username = get_jwt_identity()
        user = User.query.filter_by(username=username).first()

        userID = request.headers.get('userID')

        stmt = select(campaign_members.c.characterID).where(
            campaign_members.c.campaignID == campaignID, 
            campaign_members.c.userID == user.id
        )

        result = db.session.execute(stmt).first()

        characterID = result.characterID if result else None


        preparedSpells = Spellbook.query.filter_by(characterID=characterID, equipped=True).all()

        # Convert the SQLAlchemy objects to dictionaries
        preparedSpells = [spell.to_dict() for spell in preparedSpells]

        return jsonify({'spells': preparedSpells})

    except InvalidTokenError:
        return jsonify({'error': 'InvalidTokenError- GET /api/prepared_spells'}), 401
    except ExpiredSignatureError:
        return jsonify({'error': 'Expired token'}), 401

@app.route('/api/spells', methods=['POST'])
@jwt_required()
def create_spell():
    # Create a new spell
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    if character.character_name != 'DM':
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json

    # Convert lists to unique lists (to remove duplicates)
    data['components'] = list(set(data['components']))
    data['Classes'] = list(set(data['Classes']))

    # Convert lists to CSV strings for specific keys
    if 'components' in data:
        data['components'] = ",".join(data['components'])
        print('components:', data['components'])
        app.logger.info('components: %s', data['components'])
    if 'Classes' in data:
        data['Classes'] = ",".join(data['Classes'])
        print('Classes:', data['Classes'])
        app.logger.info('Classes: %s', data['Classes'])

    new_spell = Spell(
        name=data['name'],
        level=data['level'],
        casting_time=data['casting_time'],
        range=data['range'],
        components=data['components'],  # Use the value from the data dictionary
        duration=data['duration'],
        description=data['description'],
        classes=data['Classes'],       # Use the value from the data dictionary
        school=data['school']
    )


    db.session.add(new_spell)
    db.session.commit()
    return jsonify(new_spell.to_dict()), 201

@app.route('/api/save_spells', methods=['POST'])
@jwt_required()
def save_spells_to_spellbook():
    # Saves to Spellbook
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    data = request.json
    spells = data['spells']
    for spell_data in spells:
        spellbook_item = Spellbook(
            userID=userID,
            spell_id=spell_data['spell_id'],
            quantity=spell_data.get('quantity', 1)  # Defaults to 1 if not provided
        )
        db.session.add(spellbook_item)
    db.session.commit()
    return jsonify({"message": "Spells saved successfully"}), 201

@app.route('/api/spellbook/<int:spellID>', methods=['DELETE'])
@jwt_required()
def drop_spell_from_spellbook(spellID):
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    spellbook_item = Spellbook.query.filter_by(userID=userID).first()
    if not spellbook_item or spellbook_item.userID != userID:
        return jsonify({"error": "Spellbook item not found or unauthorized"}), 404

    data = request.json
    quantity_to_remove = data.get('quantity', 1)  # Defaults to removing 1 if not provided
    spellbook_item = Spellbook.query.get(spellID)
    if not spellbook_item:
        return jsonify({"error": "Spellbook item not found"}), 404
    if spellbook_item.quantity <= quantity_to_remove:
        db.session.delete(spellbook_item)
    else:
        spellbook_item.quantity -= quantity_to_remove
    db.session.commit()
    return jsonify({"message": "Spell removed successfully"})

@app.route('/api/spells/<int:spellID>', methods=['DELETE'])
@jwt_required()
def delete_spell(spellID):
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    if character.character_name != 'DM':
        return jsonify({"error": "Unauthorized"}), 403

    spell = Spell.query.get(spellID)
    if not spell:
        return jsonify({"error": "Spell not found"}), 404
    db.session.delete(spell)
    db.session.commit()
    return jsonify({"message": "Spell deleted successfully"})

@app.route('/api/spells/<int:spellID>', methods=['PUT'])
@jwt_required()
def update_spell(spellID):
    ## Used for the DM to update a spell's details
    campaignID = request.headers.get('CampaignID')
    userID = request.headers.get('userID')
    character = campaign_members.query.filter_by(campaignID=campaignID, userID=userID).first().character

    if character.character_name != 'DM':
        return jsonify({"error": "Unauthorized"}), 403

    spell = Spell.query.get(spellID)
    if not spell:
        return jsonify({"error": "Spell not found"}), 404
    data = request.json

    # Convert lists to unique lists (to remove duplicates)
    data['components'] = list(set(data['components']))
    data['Classes'] = list(set(data['Classes']))

    # Convert lists to CSV strings for specific keys
    if 'components' in data:
        data['components'] = ",".join(data['components'])
    if 'Classes' in data:
        data['Classes'] = ",".join(data['Classes'])

    for key, value in data.items():
        setattr(spell, key, value)
    db.session.commit()
    return jsonify(spell.to_dict())


@app.route('/api/spellbook/<int:spellID>', methods=['PUT'])
@jwt_required()
def update_spellbook_item(spellID):
    ## Isn't this so the DM can give spells to a player? Or is this for updating spells?
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()

    spellbook_item = Spellbook.query.filter_by(userID=user.id).first()
    if not spellbook_item or spellbook_item.userID != user.id:
        return jsonify({"error": "Spellbook item not found or unauthorized"}), 404

    data = request.json
    spellbook_item.name = data['name']
    spellbook_item.equipped = data['equipped']
    db.session.commit()
    return jsonify(spellbook_item.to_dict())


##************************##
## **    Loot Boxes    ** ##
##************************##
def catalog_campaign_context(require_editor=False):
    """Resolve and authorize the campaign catalog selected by the client."""
    try:
        campaign_id = int(request.headers.get('CampaignID'))
    except (TypeError, ValueError):
        return None, None, (jsonify({'message': 'CampaignID is required'}), 400)
    campaign = Campaign.query.get(campaign_id)
    user = User.query.filter_by(username=get_jwt_identity()).first()
    if not campaign or not user:
        return None, None, (jsonify({'message': 'Campaign not found'}), 404)
    is_editor = user.id in {campaign.owner_id, campaign.dm_id}
    is_member = is_editor or db.session.execute(select(campaign_members.c.userID).where(
        campaign_members.c.campaignID == campaign.id,
        campaign_members.c.userID == user.id,
    )).first() is not None
    if not is_member or (require_editor and not is_editor):
        return None, None, (jsonify({'message': 'You do not have access to this campaign catalog'}), 403)
    return campaign, user, None


def installed_module_keys(campaign_id):
    return {row.module_key for row in CampaignModuleInstallation.query.filter_by(campaign_id=campaign_id).all()}


def catalog_record_visible(record, campaign, modules=None):
    if record.campaign_id == campaign.id:
        return True
    if not record.is_preset or record.campaign_id is not None or record.system != campaign.rules_system:
        return False
    return not record.module_key or record.module_key in (modules if modules is not None else installed_module_keys(campaign.id))


def validate_catalog_module(campaign, module_key):
    module_key = str(module_key or '').strip()[:120] or None
    if module_key and module_key not in installed_module_keys(campaign.id):
        return None, (jsonify({'message': 'The selected module is not installed in this campaign'}), 400)
    return module_key, None


@app.route('/api/lootboxes', methods=['GET'])
@jwt_required()
def get_all_loot_boxes():
    campaign, _user, error = catalog_campaign_context()
    if error:
        return error
    modules = installed_module_keys(campaign.id)
    loot_boxes = [box for box in LootBox.query.order_by(LootBox.name).all() if catalog_record_visible(box, campaign, modules)]
    installations = CampaignModuleInstallation.query.filter_by(campaign_id=campaign.id).order_by(CampaignModuleInstallation.module_name).all()
    return jsonify({'lootBoxes': [box.to_dict() for box in loot_boxes], 'modules': [row.to_dict() for row in installations]})

@app.route('/api/lootboxes', methods=['POST'])
@jwt_required()
def create_loot_box():
    campaign, user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    loot_box_name = str(data.get('name') or '').strip()[:80]
    items = data.get('items') if isinstance(data.get('items'), list) else []
    if not loot_box_name:
        return jsonify({'message': 'Loot box name is required'}), 400
    module_key, error = validate_catalog_module(campaign, data.get('module_key'))
    if error:
        return error

    loot_box = LootBox(name=loot_box_name, campaign_id=campaign.id, system=campaign.rules_system,
                       module_key=module_key, is_preset=False, created_by_id=user.id)
    db.session.add(loot_box)
    db.session.flush()

    for item in items:
        itemID = item.get('id')
        try:
            quantity = max(1, int(item.get('quantity', 1)))
        except (TypeError, ValueError):
            continue
        itemDB = Item.query.filter_by(id=itemID).first()
        if itemDB:
            association = loot_box_items.insert().values(loot_boxID=loot_box.id, itemID=itemDB.id, quantity=quantity)
            db.session.execute(association)
    db.session.commit()

    return jsonify({'message': 'Loot box created successfully', 'lootBox': loot_box.to_dict()}), 201

## Save a Loot Box
@app.route('/api/lootboxes/<int:box_id>', methods=['PUT'])
@jwt_required()
def update_loot_box(box_id):
    campaign, _user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    # print("data:", data)
    app.logger.info("data: %s", data)
    loot_box_name = data['name']
    items = data['items']

    # Get the LootBox
    # loot_box = LootBox.query.get(box_id)
    loot_box = LootBox.query.filter_by(id=box_id, campaign_id=campaign.id, is_preset=False).first()
    if loot_box is None:
        return jsonify({'message': 'Loot box not found'}), 404
    module_key, error = validate_catalog_module(campaign, data.get('module_key'))
    if error:
        return error

    # Update the name
    loot_box.name = loot_box_name
    loot_box.module_key = module_key

    # Clear the current items
    loot_box.items = []

    db.session.execute(loot_box_items.delete().where(loot_box_items.c.loot_boxID == box_id))
    # Add the new items
    for item in items:
        itemID = item['id']
        quantity = item['quantity']
        # itemDB = Item.query.get(itemID)
        itemDB = Item.query.filter_by(id=itemID).first()
        if itemDB:
            association = loot_box_items.insert().values(loot_boxID=loot_box.id, itemID=itemDB.id, quantity=quantity)
            db.session.execute(association)
    db.session.commit()

    return jsonify({'message': 'Loot box updated successfully'})

@app.route('/api/lootboxes/<int:box_id>', methods=['DELETE'])
@jwt_required()
def delete_loot_box(box_id):
    campaign, _user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    loot_box = LootBox.query.filter_by(id=box_id, campaign_id=campaign.id, is_preset=False).first()
    if loot_box is None:
        return jsonify({'message': 'Loot box not found'}), 404

    db.session.delete(loot_box)
    db.session.commit()

    return jsonify({'message': 'Loot box deleted successfully'})

## Get list of loot in a lootbox
@app.route('/api/lootboxes/<int:box_id>', methods=['GET'])
@jwt_required()
def get_loot_box(box_id):
    campaign, _user, error = catalog_campaign_context()
    if error:
        return error
    loot_box = LootBox.query.filter_by(id=box_id).first()
    if loot_box and catalog_record_visible(loot_box, campaign):
        # Use the association table to get the items in this loot box along with their quantities
        items_with_quantities = db.session.query(Item, loot_box_items.c.quantity).filter(
            loot_box_items.c.loot_boxID == loot_box.id,
            loot_box_items.c.itemID == Item.id
        ).all()
        return jsonify({**loot_box.to_dict(), 'items': [{'id': item.id, 'name': item.name, 'quantity': quantity} for item, quantity in items_with_quantities]})
    else:
        return jsonify({'message': 'Loot box not found'}), 404

## Issue loot box to player
@app.route('/api/lootboxes/<int:box_id>', methods=['POST'])
@jwt_required()
def issue_loot_box(box_id):
    app.logger.debug("ISSUE LOOT BOX- box_id: %s", box_id)
    app.logger.debug("ISSUE LOOT BOX- request json: %s", request.json)
    
    campaign, _user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    selectedPlayer = (request.json or {}).get('player') or {}
    character_id = selectedPlayer.get('id')
    character_name = selectedPlayer.get('character_name')
    username = selectedPlayer.get('username')
    campaignID = request.headers.get('CampaignID')

    # Get the LootBox instance
    loot_box = LootBox.query.filter_by(id=box_id).first()
    if loot_box is None or not catalog_record_visible(loot_box, campaign):
        return jsonify({'message': 'Loot box not found.'}), 404
    character = Character.query.filter_by(id=character_id, campaignID=campaign.id).first()
    if not character:
        return jsonify({'message': 'The selected character is not in this campaign.'}), 400

    # Use the association table to get the items in this loot box along with their quantities
    items_with_quantities = db.session.query(Item, loot_box_items.c.quantity).filter(
        loot_box_items.c.loot_boxID == box_id,
        loot_box_items.c.itemID == Item.id
    ).all()

    for item, quantity in items_with_quantities:
        # Update recipient's inventory
        recipient_inventory_item = InventoryItem.query.filter_by(characterID=character_id, itemID=item.id).first()
        if recipient_inventory_item:
            recipient_inventory_item.quantity += quantity
        else:
            new_inventory_item = InventoryItem(characterID=character_id, itemID=item.id, name=item.name, quantity=quantity)
            db.session.add(new_inventory_item)

    db.session.commit()

    # Emit an inventory_update event to the recipient
    emit('inventory_update', {'character_name': character_name, 'items': [item.to_dict() for item, _ in items_with_quantities]}, to=selectedPlayer.get('sid'))

    # Send a message to the recipient that they got a new loot box
    reception_message = {
        'type': 'text_message',
        'text': f'You received {loot_box.name}!',
        'sender': 'System',
        'recipients': [character_name],
    }
    emit('message', reception_message, to=selectedPlayer.get('sid'))

    return jsonify({'message': 'Loot box issued successfully.'})


##************************##
## **       NPCs       ** ##
##************************##
@app.route('/api/npcs/generation-options', methods=['GET'])
@jwt_required()
def get_npc_generation_options():
    campaign, _user, error = catalog_campaign_context()
    if error:
        return error
    return jsonify({**supported_generation_options(), 'campaign_id': campaign.id}), 200


@app.route('/api/npcs/generate', methods=['POST'])
@jwt_required()
def generate_npcs():
    campaign, _user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        count = int(data.get('count', 1))
    except (TypeError, ValueError):
        return jsonify({'message': 'Count must be a whole number'}), 400
    if count < 1 or count > 50:
        return jsonify({'message': 'Generate between 1 and 50 NPCs at a time'}), 400

    save = data.get('save', True) is not False
    base_seed = data.get('seed')
    records = []
    try:
        for index in range(count):
            seed = f'{base_seed}:{index}' if base_seed is not None else None
            records.append(generated_npc(
                seed=seed,
                ancestry=data.get('ancestry') or data.get('race'),
                gender=data.get('gender'),
                occupation=data.get('occupation'),
                alignment=data.get('alignment'),
            ))
    except ValueError as exc:
        return jsonify({'message': str(exc), 'options': supported_generation_options()}), 400

    if save:
        models = [npc_from_record(campaign.id, record) for record in records]
        db.session.add_all(models)
        db.session.commit()
        response_npcs = [npc.to_dict() | {'generation': record['generation']} for npc, record in zip(models, records)]
    else:
        response_npcs = [record | {'campaign_id': campaign.id} for record in records]

    return jsonify({'npcs': response_npcs, 'saved': save, 'count': len(response_npcs)}), 201 if save else 200


@app.route('/api/npcs', methods=['POST'])
@jwt_required()
def create_npc():
    data = request.json
    campaignID = request.headers.get('CampaignID')
    # app.logger.debug("CREATE NPC- campaignID from headers: %s", campaignID)
    
    name = data.get('name')
    description = data.get('description')
    size = data.get('size')
    creature_type = data.get('creatureType')
    creature_subtype = data.get('creatureSubtype')
    alignment = data.get('alignment')
    ac = data.get('ac')
    hp = data.get('hp')
    speed = data.get('speed')
    strength = data.get('strength')
    dexterity = data.get('dexterity')
    constitution = data.get('constitution')
    intelligence = data.get('intelligence')
    wisdom = data.get('wisdom')
    charisma = data.get('charisma')
    saving_throws = data.get('saving_throws')
    skills = data.get('skills')
    immunities = data.get('immunities')
    resistance = data.get('resistance')
    senses = data.get('senses')
    languages = data.get('languages')
    challenge = data.get('challenge')
    traits = data.get('traits')
    actions = data.get('actions')

    new_npc = NPC(
        campaign_id=campaignID,
        name=name,
        description=description,
        size=size,
        creature_type=creature_type,
        creature_subtype=creature_subtype,
        alignment=alignment,
        ac=ac,
        hp=hp,
        speed=speed,
        strength=strength,
        dexterity=dexterity,
        constitution=constitution,
        intelligence=intelligence,
        wisdom=wisdom,
        charisma=charisma,
        saving_throws=saving_throws,
        skills=skills,
        immunities=immunities,
        resistance=resistance,
        senses=senses,
        languages=languages,
        challenge=challenge,
        traits=traits,
        actions=actions
    )
    db.session.add(new_npc)
    db.session.commit()

    return jsonify(new_npc.to_dict()), 201

@app.route('/api/npcs', methods=['GET'])
@jwt_required()
def get_npcs():
    campaignID = request.headers.get('CampaignID')
    npcs = NPC.query.filter_by(campaign_id=campaignID).all()
    return jsonify([npc.to_dict() for npc in npcs]), 200

##************************##
## **  Random Tables   ** ##
##************************##

## Create a new table
@app.route('/api/random_tables', methods=['POST'])
@jwt_required()
def create_random_table():
    campaign, user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    data = request.json or {}
    app.logger.debug("CREATE RANDOM TABLE- data: %s", data)
    name = data.get('name')
    description = data.get('description')
    dice_type = data.get('diceType')
    entries_data = data.get('entries', [])

    if not name or not dice_type:
        return jsonify({'error': 'Name and dice_type are required'}), 400

    module_key, error = validate_catalog_module(campaign, data.get('moduleKey') or data.get('module_key'))
    if error:
        return error
    new_random_table = RandomTable(
        name=name,
        description=description,
        dice_type=dice_type,
        campaign_id=campaign.id,
        system=campaign.rules_system,
        module_key=module_key,
        is_preset=False,
        created_by_id=user.id,
    )
    db.session.add(new_random_table)
    db.session.flush()  # Ensure new_random_table.id is available

    # Create and add table entries
    for entry_data in entries_data:
        min_roll = entry_data.get('min_roll')
        max_roll = entry_data.get('max_roll')
        result = entry_data.get('result')

        if min_roll is None or max_roll is None or result is None:
            return jsonify({'error': 'Each table entry must have min_roll, max_roll, and result'}), 400

        new_entry = TableEntry(
            table_id=new_random_table.id,
            min_roll=min_roll,
            max_roll=max_roll,
            result=result
        )
        db.session.add(new_entry)

    db.session.commit()

    app.logger.debug("New Table created: %s", new_random_table.to_dict())
    return jsonify(new_random_table.to_dict()), 201

## Update existing table
@app.route('/api/random_tables/<int:table_id>', methods=['PUT'])
@jwt_required()
def update_random_table(table_id):
    campaign, _user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    data = request.json or {}
    app.logger.debug("UPDATE RANDOM TABLE- data: %s", data)
    name = data.get('name')
    description = data.get('description')
    dice_type = data.get('diceType')
    entries_data = data.get('entries', [])

    if not name or not dice_type:
        return jsonify({'error': 'Name and dice_type are required'}), 400

    # Fetch the existing table
    random_table = RandomTable.query.filter_by(id=table_id, campaign_id=campaign.id, is_preset=False).first_or_404()
    module_key, error = validate_catalog_module(campaign, data.get('moduleKey') or data.get('module_key'))
    if error:
        return error
    random_table.name = name
    random_table.description = description
    random_table.dice_type = dice_type
    random_table.module_key = module_key

    # Clear existing entries
    TableEntry.query.filter_by(table_id=table_id).delete()

    # Create and add new table entries
    for entry_data in entries_data:
        min_roll = entry_data.get('min_roll')
        max_roll = entry_data.get('max_roll')
        result = entry_data.get('result')
    
        if min_roll is None or result is None:
            return jsonify({'error': 'Each table entry must have min_roll, max_roll, and result'}), 400
        
        # Set max_roll to None if it is an empty string
        if max_roll == '':
            max_roll = None
    
        new_entry = TableEntry(
            table_id=table_id,
            min_roll=min_roll,
            max_roll=max_roll,
            result=result
        )
        db.session.add(new_entry)

    db.session.commit()

    app.logger.debug("Table updated: %s", random_table.to_dict())
    return jsonify(random_table.to_dict()), 200

@app.route('/api/random_tables', methods=['GET'])
@jwt_required()
def get_random_tables():
    campaign, _user, error = catalog_campaign_context()
    if error:
        return error
    modules = installed_module_keys(campaign.id)
    random_tables = [table for table in RandomTable.query.order_by(RandomTable.name).all() if catalog_record_visible(table, campaign, modules)]
    return jsonify([{
        'id': table.id,
        'name': table.name,
        'description': table.description,
        'dice_type': table.dice_type,
        'campaign_id': table.campaign_id,
        'system': table.system,
        'module_key': table.module_key,
        'is_preset': table.is_preset,
        'editable': not table.is_preset,
        'scope': 'module_preset' if table.is_preset and table.module_key else ('system_preset' if table.is_preset else 'campaign'),
    } for table in random_tables]), 200

@app.route('/api/random_tables/<int:table_id>', methods=['GET'])
@jwt_required()
def get_random_table_entries(table_id):
    campaign, _user, error = catalog_campaign_context()
    if error:
        return error
    random_table = RandomTable.query.get_or_404(table_id)
    if not catalog_record_visible(random_table, campaign):
        return jsonify({'message': 'Random table not found'}), 404
    return jsonify(random_table.to_dict()), 200

@app.route('/api/random_tables/<int:table_id>', methods=['DELETE'])
@jwt_required()
def delete_random_table(table_id):
    campaign, _user, error = catalog_campaign_context(require_editor=True)
    if error:
        return error
    random_table = RandomTable.query.filter_by(id=table_id, campaign_id=campaign.id, is_preset=False).first_or_404()
    app.logger.debug("DELETE RANDOM TABLE- table_id: %s", table_id)

    # Delete associated table entries
    TableEntry.query.filter_by(table_id=table_id).delete()

    # Delete the random table
    db.session.delete(random_table)
    db.session.commit()

    app.logger.debug("Table deleted: %s", random_table.to_dict())
    return jsonify({'message': 'Table deleted successfully'}), 200

##************************##
## **    Wiki Stuff    ** ##
##************************##
@app.route('/wiki/health', methods=['GET'])
def wiki_health():
    return jsonify({'ok': True, 'service': 'kachhapa-wiki'}), 200


@app.route('/wiki-static/<path:filename>', methods=['GET'])
def wiki_static(filename):
    """Serve wiki-only assets without colliding with the React /static tree."""
    return send_from_directory(app.static_folder, filename)


@app.route('/api/campaigns/<int:campaign_id>/wiki', methods=['GET'])
@app.route('/api/campaigns/<int:campaign_id>/wiki/pages', methods=['GET'])
def campaign_wiki_pages(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    pages = Page.query.filter_by(wiki_id=campaign.id).order_by(Page.id).all()
    return jsonify([page.to_dict() for page in pages])

@app.route('/wiki/<campaign_name>/search', methods=['GET'])
def search(campaign_name):
    app.logger.debug("campaign_name: %s", campaign_name)
    app.logger.debug("request: %r", request)
    query = request.args.get('q')
    app.logger.debug("search query: %s", query)
    if not query:
        app.logger.warning("No query provided")
        return jsonify([])

    campaign = Campaign.query.filter_by(name=campaign_name).first_or_404()
    search_query = db.session.query(Page).filter(
        Page.wiki_id == campaign.id,
        Page.tsv.match(query)
    ).all()
    results = [{'id': page.id, 'title': page.title} for page in search_query]
    app.logger.debug("search results: %s", results)

    if not results:
        return jsonify({'message': 'No results found', 'create_option': True})

    return jsonify(results) 

import re

def preprocess_content(content):
    # This regular expression matches Markdown links like [display text](URL)
    pattern = r'\[(.*?)\]\((.*?)\)'
    # This function will be used to replace each match
    def replacer(match):
        display_text = match.group(1)
        return f'[{display_text}]({display_text})'
    # Use the sub function to replace each match
    return re.sub(pattern, replacer, content)

@app.route('/wiki/<campaign_name>/<page_title>', methods=['GET'])
def wiki_page(campaign_name, page_title):
    app.logger.debug("campaign_name: %s", campaign_name)
    app.logger.debug("page_title: %s", page_title)

    # Get the campaign ID from the campaign name
    campaign = Campaign.query.filter_by(name=campaign_name).first()
    if campaign is None:
        return "Campaign not found", 404
    app.logger.debug("campaign ID: %s", campaign.id)

    # Get the page using the Campaign ID and the page title
    page = Page.query.filter_by(wiki_id=campaign.id, title=page_title).first()

    if page is None:
        app.logger.error("Page %s not found", page_title)
        # Call the create_page function directly
        return create_page(campaign_name, page_title)

    preprocessed_content = preprocess_content(page.content)
    html_content = markdown.markdown(preprocessed_content)

    return render_template('page.html', campaign_name=campaign_name, content=html_content, page_title=page.title)

@app.route('/wiki/<campaign_name>/<page_title>/create', methods=['GET', 'POST'])
def create_page(campaign_name, page_title):
    app.logger.debug("Creating %s page for %s wiki", page_title, campaign_name)
    # Get the campaign ID from the campaign name
    campaign = Campaign.query.filter_by(name=campaign_name).first()
    if campaign is None:
        return "Campaign not found", 404

    existing_page = Page.query.filter_by(wiki_id=campaign.id, title=page_title).first()
    if existing_page is not None:
        if request.method == 'GET':
            return redirect(url_for(
                'edit_page',
                campaign_name=campaign_name,
                page_title=page_title
            ))
        return "Page already exists", 409

    # # Ensure the sequence is correctly set
    # max_id_result = db.session.execute(text("SELECT MAX(id) FROM page"))
    # max_id = max_id_result.scalar()
    # db.session.execute(text(f"SELECT setval('page_id_seq', {max_id + 1})"))
    # db.session.commit()

    if request.method == 'POST':
        content = request.form['content']

        try:
            # Create a new page entry with the provided content
            new_page = Page(title=page_title, content=content, wiki_id=campaign.id)
            db.session.add(new_page)
            db.session.commit()

            # Redirect to the editable version of the new page
            return redirect(url_for('edit_page', campaign_name=campaign_name, page_title=page_title))
        except SQLAlchemyError as e:
            db.session.rollback()
            return f"An error occurred while creating the page: {str(e)}", 500

    try:
        # Create a blank page in the database
        new_page = Page(title=page_title, content='', wiki_id=campaign.id)
        db.session.add(new_page)
        db.session.commit()

        # Redirect to the edit page
        app.logger.info("Redirecting client to edit page")
        return render_template('edit_page.html', campaign_name=campaign_name, content=f"<h1>{page_title}</h1><p><br></p>", page_title=page_title)
    except SQLAlchemyError as e:
        db.session.rollback()
        return f"An error occurred while creating the page: {str(e)}", 500
    
@app.route('/wiki/<campaign_name>/<page_title>/edit', methods=['GET', 'POST'])
def edit_page(campaign_name, page_title):
    campaign = Campaign.query.filter_by(name=campaign_name).first()
    if campaign is None:
        return "Campaign not found", 404
    page = Page.query.filter_by(wiki_id=campaign.id, title=page_title).first()
    if not page:
        return "Page not found", 404

    # Handle POST request for saving edits
    if request.method == "POST":
        app.logger.info("Edit Page POST: %s", request)
        content = request.form.get('content')
        userID = request.headers.get('userID')
        app.logger.info("Edit Page- userID: %s", userID)

        # Save the current state of the page to the Revisions table
        new_revision = Revisions(
            page_id=page.id,
            content=page.content,
            user_id=userID  # Store the user ID
        )
        db.session.add(new_revision)

        # Update the page content
        page.content = content

        try:
            db.session.commit()
            app.logger.info(f"Database commit successful for page_id: {page.id}, user_id: {userID}")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Database commit failed for page_id: {page.id}, user_id: {userID}. Error: {e}")
            raise

        # Send a response with success: true
        return jsonify(success=True)

    # Handle GET request for displaying the edit page
    elif request.method == "GET":
        html_content = markdown.markdown(page.content)
        return render_template('edit_page.html', campaign_name=campaign_name, content=html_content, page_title=page.title)


##************************##
## **  Calendar Stuff  ** ##
##************************##
def emit_calendar_updated(campaign_id, payload=None):
    base_payload = {"campaign_id": campaign_id}
    if payload:
        base_payload.update(payload)

    socketio.emit(
        'calendar_updated',
        base_payload,
        to=f'campaign:{campaign_id}'
    )

def get_calendar_format(calendar):
    if not calendar.format_element:
        return {}
    return calendar.format_element.data or {}

def get_months(calendar):
    format_data = get_calendar_format(calendar)
    return format_data.get('months', [])

def get_weekdays(calendar):
    format_data = get_calendar_format(calendar)
    return format_data.get('weekdays', [])

def get_moons(calendar):
    format_data = get_calendar_format(calendar)
    return format_data.get('moons', [])

def get_holidays(calendar):
    format_data = get_calendar_format(calendar)
    return format_data.get('holidays', [])


def is_leap_year(calendar, year):
    format_data = get_calendar_format(calendar)
    rule = format_data.get('leap_rule')

    if not rule:
        return False

    rule_type = rule.get('type')

    if rule_type == 'gregorian':
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    if rule_type == 'every_n_years':
        interval = rule.get('interval', 4)
        return year % interval == 0

    if rule_type == 'harptos_shieldmeet':
        return year % 4 == 0

    return False


def days_in_month(calendar, year, month_index):
    months = get_months(calendar)

    if month_index < 0 or month_index >= len(months):
        raise IndexError("month_index out of range")

    month = months[month_index]

    if is_leap_year(calendar, year) and month.get('leap_length') is not None:
        return month['leap_length']

    return month.get('length', 30)


def date_to_ordinal(calendar, year, month_index, day):
    months = get_months(calendar)

    if not months:
        raise ValueError("Calendar format has no months defined")

    ordinal = 0
    start_year = calendar.epoch_year or 1

    for y in range(start_year, year):
        for i in range(len(months)):
            ordinal += days_in_month(calendar, y, i)

    for i in range(month_index):
        ordinal += days_in_month(calendar, year, i)

    ordinal += (day - 1)
    return ordinal


def ordinal_to_date(calendar, ordinal):
    months = get_months(calendar)

    if not months:
        raise ValueError("Calendar format has no months defined")

    year = calendar.epoch_year or 1

    while True:
        year_length = sum(days_in_month(calendar, year, i) for i in range(len(months)))
        if ordinal < year_length:
            break
        ordinal -= year_length
        year += 1

    month_index = 0
    while True:
        dim = days_in_month(calendar, year, month_index)
        if ordinal < dim:
            break
        ordinal -= dim
        month_index += 1

    day = ordinal + 1
    return year, month_index, day



def advance_date(calendar, current_date, delta_days=0, delta_hours=0, delta_minutes=0):
    hours_in_day = calendar.get_hours_in_day() or 24
    minutes_in_hour = calendar.get_minutes_in_hour() or 60

    total_minutes = (
        current_date['hour'] * minutes_in_hour
        + current_date['minute']
        + delta_hours * minutes_in_hour
        + delta_minutes
    )

    extra_days, remaining_minutes = divmod(total_minutes, hours_in_day * minutes_in_hour)

    if remaining_minutes < 0:
        extra_days -= 1
        remaining_minutes += hours_in_day * minutes_in_hour

    new_hour, new_minute = divmod(remaining_minutes, minutes_in_hour)

    start_ordinal = date_to_ordinal(
        calendar,
        current_date['year'],
        current_date['month_index'],
        current_date['day']
    )

    new_ordinal = start_ordinal + delta_days + extra_days
    new_year, new_month_index, new_day = ordinal_to_date(calendar, new_ordinal)

    return {
        'year': new_year,
        'month_index': new_month_index,
        'day': new_day,
        'hour': new_hour,
        'minute': new_minute,
    }


def get_moon_phase(moon_data, ordinal_day):
    cycle_length = moon_data.get('cycle_length_days', 30)
    phase_offset = moon_data.get('phase_offset', 0)

    phase_index = (ordinal_day + phase_offset) % cycle_length
    return phase_index_to_name(phase_index, cycle_length)

def phase_index_to_name(phase_index, cycle_length):
    ratio = phase_index / cycle_length

    if ratio < 0.125:
        return 'new'
    if ratio < 0.25:
        return 'waxing-crescent'
    if ratio < 0.375:
        return 'first-quarter'
    if ratio < 0.5:
        return 'waxing-gibbous'
    if ratio < 0.625:
        return 'full'
    if ratio < 0.75:
        return 'waning-gibbous'
    if ratio < 0.875:
        return 'last-quarter'
    return 'waning-crescent'

def get_holidays_for_month(calendar, year, month_index):
    holidays = get_holidays(calendar)

    results = []
    for holiday in holidays:
        if holiday.get('month_index') != month_index:
            continue

        if holiday.get('leap_only') and not is_leap_year(calendar, year):
            continue

        results.append(holiday)

    return results

def get_settlement_simulation_state(campaign_id, persist=True):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    minute_of_day = (calendar.current_hour * 60 + calendar.current_minute) if calendar else 720
    routes = LamplighterRoute.query.filter_by(campaign_id=campaign_id, active=True).order_by(LamplighterRoute.id).all()
    route_states = []
    changed = False

    for route in routes:
        lamps = StreetLamp.query.filter_by(route_id=route.id).order_by(StreetLamp.route_order).all()
        state = calculate_lamplighter_state(route, lamps, minute_of_day)
        lit_by_id = {lamp['id']: lamp['lit'] for lamp in state['lamps']}
        for lamp in lamps:
            new_lit = lit_by_id.get(lamp.id, False)
            if lamp.lit != new_lit:
                lamp.lit = new_lit
                changed = True
        route_states.append({
            'id': route.id,
            'name': route.name,
            'phase': state['phase'],
            'lamplighter_position': state['position'],
            'next_lamp_id': state['next_lamp_id'],
            'lamps': state['lamps'],
        })

    if changed and persist:
        db.session.commit()

    return {
        'campaign_id': campaign_id,
        'time': {
            'year': calendar.current_year if calendar else 1,
            'month_index': calendar.current_month_index if calendar else 0,
            'day': calendar.current_day if calendar else 1,
            'hour': calendar.current_hour if calendar else 12,
            'minute': calendar.current_minute if calendar else 0,
        },
        'routes': route_states,
    }


def emit_settlement_simulation_updated(campaign_id):
    state = get_settlement_simulation_state(campaign_id)
    socketio.emit('settlement_simulation_updated', state, to=f'campaign:{campaign_id}')
    return state


SETTLEMENT_BUILDING_ASSETS = [
    {
        'key': 'timber_cottage', 'name': 'Timber Cottage', 'category': 'residential',
        'width_feet': 42, 'depth_feet': 32, 'height_feet': 28, 'model_url': None,
        'color': '#b87742', 'roof_color': '#513a30',
        'rooms': ['Common room', 'Kitchen', 'Bedroom', 'Pantry', 'Loft'],
    },
    {
        'key': 'stone_townhouse', 'name': 'Stone Townhouse', 'category': 'residential',
        'width_feet': 36, 'depth_feet': 46, 'height_feet': 36, 'model_url': None,
        'color': '#8f8373', 'roof_color': '#3d4650',
        'rooms': ['Entry hall', 'Parlor', 'Kitchen', 'Primary bedroom', 'Bedroom', 'Study', 'Cellar'],
    },
    {
        'key': 'shop_house', 'name': 'Shop House', 'category': 'commercial',
        'width_feet': 52, 'depth_feet': 40, 'height_feet': 32, 'model_url': None,
        'color': '#a76d43', 'roof_color': '#4c352b',
        'rooms': ['Shop floor', 'Workshop', 'Stockroom', 'Kitchen', 'Owner bedroom', 'Cellar'],
    },
    {
        'key': 'coaching_inn', 'name': 'Coaching Inn', 'category': 'hospitality',
        'width_feet': 88, 'depth_feet': 62, 'height_feet': 40, 'model_url': None,
        'color': '#9a633b', 'roof_color': '#463128',
        'rooms': ['Common room', 'Taproom', 'Kitchen', 'Pantry', 'Office', 'Six guest rooms', 'Stable', 'Cellar'],
    },
    {
        'key': 'storehouse', 'name': 'Storehouse', 'category': 'industrial',
        'width_feet': 64, 'depth_feet': 48, 'height_feet': 30, 'model_url': None,
        'color': '#87603e', 'roof_color': '#3f342d',
        'rooms': ['Receiving floor', 'Main storage', 'Secure cage', 'Clerk office', 'Loading bay'],
    },
]


def default_settlement_map_design(campaign_id):
    return SettlementMapDesign(campaign_id=campaign_id)


def ensure_campaign_settlement(campaign_id, commit=True):
    location = WorldAtlasLocation.query.filter_by(campaign_id=campaign_id).order_by(
        WorldAtlasLocation.is_primary.desc(), WorldAtlasLocation.id
    ).first()
    if location:
        return location
    legacy = SettlementMapDesign.query.filter_by(campaign_id=campaign_id).first()
    has_legacy_content = bool(legacy and any((legacy.terrain_strokes, legacy.roads, legacy.buildings, legacy.reference_layers)))
    location = WorldAtlasLocation(
        campaign_id=campaign_id,
        name='Pinewater Crossing' if has_legacy_content else 'New Settlement',
        map_key=uuid4().hex,
        is_primary=True,
        terrain_strokes=(legacy.terrain_strokes or []) if legacy else [],
        roads=(legacy.roads or []) if legacy else [],
        buildings=(legacy.buildings or []) if legacy else [],
        reference_layers=(legacy.reference_layers or []) if legacy else [],
    )
    db.session.add(location)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return location


def resolve_settlement(campaign_id, supplied_id=None):
    settlement_id = supplied_id or request.args.get('settlement_id')
    if settlement_id:
        try:
            return WorldAtlasLocation.query.filter_by(id=int(settlement_id), campaign_id=campaign_id).first()
        except (TypeError, ValueError):
            return None
    return ensure_campaign_settlement(campaign_id)


def campaign_atlas_config(campaign):
    installed_settings = {
        value.setting_key for value in CampaignModuleInstallation.query.filter_by(campaign_id=campaign.id).all()
        if value.setting_key
    }
    module_name = (campaign.module or '').lower()
    faerun_terms = ('faerun', 'forgotten realms', 'waterdeep', 'neverwinter', 'baldur', 'icewind', 'chult', 'sword coast')
    is_faerun = 'forgotten_realms' in installed_settings or any(term in module_name for term in faerun_terms)
    setting_key = 'faerun' if is_faerun else 'custom'
    setting_default = SettingWorldAtlas.query.filter_by(setting_key=setting_key).first()
    stored = CampaignWorldAtlas.query.filter_by(campaign_id=campaign.id).first()
    if stored:
        if is_faerun and stored.setting_key != 'faerun':
            stored.setting_key = 'faerun'
            stored.coordinate_space_key = 'faerun-v1'
            stored.name = 'Faerûn'
        if not stored.image_asset_id and setting_default and setting_default.image_asset_id:
            stored.image_asset_id = setting_default.image_asset_id
            stored.attribution = setting_default.attribution
            stored.source_name = setting_default.source_name
        return stored.to_dict()
    atlas = CampaignWorldAtlas(
        campaign_id=campaign.id,
        setting_key=setting_key,
        coordinate_space_key='faerun-v1' if is_faerun else f'campaign-{campaign.id}-v1',
        name='Faerûn' if is_faerun else 'Campaign World',
        image_asset_id=setting_default.image_asset_id if setting_default else None,
        attribution=setting_default.attribution if setting_default else None,
        source_name=setting_default.source_name if setting_default else None,
    )
    db.session.add(atlas)
    db.session.flush()
    return atlas.to_dict()


@app.route('/api/map-media/<public_id>', methods=['GET'])
def get_map_media(public_id):
    """Serve an opaque database asset URL usable by Three.js texture loaders."""
    asset = MapMediaAsset.query.filter_by(public_id=public_id).first_or_404()
    response = send_file(io.BytesIO(asset.data), mimetype=asset.mimetype, download_name=asset.original_filename)
    response.headers['Cache-Control'] = 'private, max-age=604800, immutable'
    response.set_etag(asset.sha256)
    response.make_conditional(request)
    return response


@app.route('/api/world-atlas/<int:campaign_id>/image', methods=['POST'])
@jwt_required()
def upload_world_atlas_image(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may change its atlas'}), 403
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({'message': 'Choose a licensed atlas image to upload'}), 400
    if not allowed_map_reference_file(uploaded.filename):
        return jsonify({'message': 'Atlas images must be PNG, JPEG, or WebP'}), 400
    data = uploaded.read()
    if len(data) > 60 * 1024 * 1024:
        return jsonify({'message': 'Atlas images must be 60 MB or smaller'}), 413
    try:
        with Image.open(io.BytesIO(data)) as image:
            pixel_width, pixel_height = image.size
            image.verify()
    except Exception:
        return jsonify({'message': 'The uploaded file is not a valid image'}), 400
    atlas = CampaignWorldAtlas.query.filter_by(campaign_id=campaign.id).first()
    if not atlas:
        campaign_atlas_config(campaign)
        atlas = CampaignWorldAtlas.query.filter_by(campaign_id=campaign.id).first()
    setting_default = request.form.get('setting_default', 'true').lower() in {'1', 'true', 'yes', 'on'} and atlas.setting_key == 'faerun'
    asset = store_map_media_asset(
        None if setting_default else campaign.id, data, secure_filename(uploaded.filename), uploaded.mimetype,
        purpose='world_atlas', name=request.form.get('name') or atlas.name,
        pixel_width=pixel_width, pixel_height=pixel_height,
    )
    atlas.image_asset_id = asset.id
    atlas.name = (request.form.get('name') or atlas.name or 'Campaign World').strip()[:160]
    atlas.source_name = secure_filename(uploaded.filename)[:255]
    atlas.attribution = (request.form.get('attribution') or '').strip()
    atlas.updated_at = datetime.now(timezone.utc)
    if setting_default:
        shared = SettingWorldAtlas.query.filter_by(setting_key=atlas.setting_key).first()
        if not shared:
            shared = SettingWorldAtlas(
                setting_key=atlas.setting_key, coordinate_space_key=atlas.coordinate_space_key, name=atlas.name,
            )
            db.session.add(shared)
        shared.image_asset_id = asset.id
        shared.name = atlas.name
        shared.source_name = atlas.source_name
        shared.attribution = atlas.attribution
        shared.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(atlas.to_dict()), 201


WORLD_SETTLEMENT_TYPES = {'hamlet', 'village', 'town', 'city', 'fortress', 'port', 'ruin', 'other'}


def settlement_generation_context(campaign):
    """Campaign-scoped choices used to make a new place feel like the same world."""
    existing = WorldAtlasLocation.query.filter_by(campaign_id=campaign.id).all()
    inherited_races = []
    inherited_factions = []
    for location in existing:
        config = location.generation_config or {}
        inherited_races.extend(item.get('name') for item in config.get('race_distribution', []) if item.get('name'))
        inherited_factions.extend(config.get('factions', []))
    try:
        rules_races = [item.name for item in GameElement.query.filter_by(element_type='race', system=campaign.rules_system).limit(80).all()]
        rules_factions = [item.name for item in GameElement.query.filter_by(element_type='faction', system=campaign.rules_system).limit(80).all()]
    except (AttributeError, SQLAlchemyError):
        rules_races, rules_factions = [], []
    race_names = list(dict.fromkeys([*inherited_races, *rules_races, 'Human', 'Elf', 'Dwarf', 'Halfling', 'Gnome']))
    faction_names = list(dict.fromkeys([*inherited_factions, *rules_factions]))
    return {
        'settlement_presets': SETTLEMENT_PRESETS,
        'governments': GOVERNMENTS, 'biomes': BIOMES, 'resources': RESOURCES,
        'races': race_names[:100], 'factions': faction_names[:100],
        'inherited': {'races': inherited_races[:20], 'factions': inherited_factions[:20]},
    }


@app.route('/api/world-atlas/<int:campaign_id>', methods=['GET'])
@jwt_required()
def get_world_atlas(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    ensure_campaign_settlement(campaign_id)
    locations = WorldAtlasLocation.query.filter_by(campaign_id=campaign_id).order_by(
        WorldAtlasLocation.is_primary.desc(), WorldAtlasLocation.name
    ).all()
    atlas_config = campaign_atlas_config(campaign)
    db.session.commit()
    return jsonify({'campaign': campaign.to_dict(), 'atlas': atlas_config,
                    'locations': [location.atlas_dict() for location in locations]}), 200


@app.route('/api/world-atlas/<int:campaign_id>/generation-options', methods=['GET'])
@jwt_required()
def get_settlement_generation_options(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    return jsonify(settlement_generation_context(campaign)), 200


@app.route('/api/world-atlas/<int:campaign_id>/settlements', methods=['POST'])
@jwt_required()
def create_world_atlas_settlement(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may create settlements'}), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or 'New Settlement').strip()[:120]
    settlement_type = str(data.get('settlement_type') or 'town').lower()
    if settlement_type not in WORLD_SETTLEMENT_TYPES:
        return jsonify({'message': 'Unknown settlement type'}), 400
    try:
        population = None if data.get('population') in (None, '') else max(0, int(data['population']))
        atlas_x = None if data.get('atlas_x') is None else min(1.0, max(0.0, float(data['atlas_x'])))
        atlas_y = None if data.get('atlas_y') is None else min(1.0, max(0.0, float(data['atlas_y'])))
    except (TypeError, ValueError):
        return jsonify({'message': 'Population and atlas coordinates must be numbers'}), 400
    environment = data.get('environment') if isinstance(data.get('environment'), dict) else {}
    should_generate = data.get('generate', True) is not False and not data.get('blank_canvas', False)
    generated = generate_settlement({
        **data, 'name': name, 'settlement_type': settlement_type,
        'population': population if population is not None else SETTLEMENT_PRESETS.get(settlement_type, SETTLEMENT_PRESETS['other'])['population'],
        'environment': environment,
    }) if should_generate else {
        'population': population, 'environment': environment, 'generation_config': {'generator': 'blank-canvas'},
        'terrain_strokes': [], 'roads': [], 'water_bodies': [], 'buildings': [], 'reference_layers': [],
    }
    location = WorldAtlasLocation(
        campaign_id=campaign_id, name=name or 'New Settlement', map_key=uuid4().hex,
        settlement_type=settlement_type, population=generated['population'],
        notes=str(data.get('notes') or '').strip()[:4000], atlas_x=atlas_x, atlas_y=atlas_y,
        environment=generated['environment'], generation_config=generated['generation_config'],
        terrain_strokes=generated['terrain_strokes'], roads=generated['roads'],
        water_bodies=generated['water_bodies'], buildings=generated['buildings'],
        reference_layers=generated['reference_layers'],
    )
    if not WorldAtlasLocation.query.filter_by(campaign_id=campaign_id).first():
        location.is_primary = True
    db.session.add(location)
    db.session.commit()
    socketio.emit('world_atlas_updated', {'action': 'created', 'settlement': location.atlas_dict()}, to=f'campaign:{campaign_id}')
    return jsonify(location.atlas_dict()), 201


@app.route('/api/world-atlas/<int:campaign_id>/settlements/<int:settlement_id>', methods=['PATCH', 'DELETE'])
@jwt_required()
def edit_world_atlas_settlement(campaign_id, settlement_id):
    campaign = Campaign.query.get(campaign_id)
    location = WorldAtlasLocation.query.filter_by(id=settlement_id, campaign_id=campaign_id).first()
    if not campaign or not location:
        return jsonify({'message': 'Settlement not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may edit settlements'}), 403
    if request.method == 'DELETE':
        if request.args.get('reason') != 'mistake':
            return jsonify({'message': 'Permanent deletion requires reason=mistake; mark a settlement destroyed for an in-world event'}), 400
        deleted = location.atlas_dict()
        was_primary = location.is_primary
        db.session.delete(location)
        db.session.flush()
        replacement = WorldAtlasLocation.query.filter_by(campaign_id=campaign_id).order_by(WorldAtlasLocation.id).first()
        if not replacement:
            replacement = WorldAtlasLocation(campaign_id=campaign_id, name='New Settlement', map_key=uuid4().hex, is_primary=True)
            db.session.add(replacement)
            db.session.flush()
        elif was_primary:
            replacement.is_primary = True
        db.session.commit()
        socketio.emit('world_atlas_updated', {'action': 'deleted', 'settlement': deleted}, to=f'campaign:{campaign_id}')
        return jsonify({'deleted_id': settlement_id, 'active_settlement': replacement.atlas_dict()}), 200
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = str(data['name']).strip()[:120]
        if not name:
            return jsonify({'message': 'Settlement name cannot be blank'}), 400
        location.name = name
    if 'settlement_type' in data:
        settlement_type = str(data['settlement_type']).lower()
        if settlement_type not in WORLD_SETTLEMENT_TYPES:
            return jsonify({'message': 'Unknown settlement type'}), 400
        location.settlement_type = settlement_type
    if 'status' in data:
        status = str(data['status']).lower()
        if status not in {'active', 'destroyed'}:
            return jsonify({'message': 'Settlement status must be active or destroyed'}), 400
        location.status = status
        location.destroyed_at = datetime.now(timezone.utc) if status == 'destroyed' else None
    if 'notes' in data:
        location.notes = str(data['notes'] or '').strip()[:4000]
    if 'environment' in data:
        if not isinstance(data['environment'], dict):
            return jsonify({'message': 'Environment must be an object'}), 400
        location.environment = data['environment']
    try:
        if 'population' in data:
            location.population = None if data['population'] in (None, '') else max(0, int(data['population']))
        for field in ('atlas_x', 'atlas_y'):
            if field in data:
                setattr(location, field, None if data[field] is None else min(1.0, max(0.0, float(data[field]))))
    except (TypeError, ValueError):
        return jsonify({'message': 'Population and atlas coordinates must be numbers'}), 400
    if data.get('is_primary'):
        WorldAtlasLocation.query.filter_by(campaign_id=campaign_id).update({'is_primary': False})
        location.is_primary = True
    location.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    socketio.emit('world_atlas_updated', {'action': 'updated', 'settlement': location.atlas_dict()}, to=f'campaign:{campaign_id}')
    return jsonify(location.atlas_dict()), 200


def user_can_edit_campaign(campaign):
    user = User.query.filter_by(username=get_jwt_identity()).first()
    return bool(user and user.id in {campaign.dm_id, campaign.owner_id})


@app.route('/api/settlement-map/<int:campaign_id>', methods=['GET'])
@jwt_required()
def get_settlement_map_design(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    design = resolve_settlement(campaign_id)
    if not design:
        return jsonify({'message': 'Settlement not found'}), 404
    migrated = persist_reference_layer_media(campaign_id, {'reference_layers': design.reference_layers or []})
    if migrated['reference_layers'] != (design.reference_layers or []):
        design.reference_layers = migrated['reference_layers']
        design.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    return jsonify({**design.to_map_dict(), 'asset_catalog': SETTLEMENT_BUILDING_ASSETS}), 200


@app.route('/api/settlement-map/<int:campaign_id>/reference-layers', methods=['POST'])
@jwt_required()
def upload_settlement_reference_layer(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may edit this map'}), 403
    if request.content_length and request.content_length > 61 * 1024 * 1024:
        return jsonify({'message': 'Reference images must be 60 MB or smaller'}), 413

    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({'message': 'A reference image is required'}), 400
    if not allowed_map_reference_file(uploaded.filename):
        return jsonify({'message': 'Reference images must be PNG, JPEG, or WebP'}), 400

    uploaded.stream.seek(0, 2)
    uploaded_size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    if uploaded_size > 60 * 1024 * 1024:
        return jsonify({'message': 'Reference images must be 60 MB or smaller'}), 413

    try:
        with Image.open(uploaded.stream) as image:
            pixel_width, pixel_height = image.size
            if image.format not in {'PNG', 'JPEG', 'WEBP'}:
                return jsonify({'message': 'Reference images must be PNG, JPEG, or WebP'}), 400
            if pixel_width * pixel_height > 300_000_000:
                return jsonify({
                    'message': 'Reference images may contain at most 300 megapixels.'
                }), 400
            image.verify()
        uploaded.stream.seek(0)
    except Image.DecompressionBombError:
        return jsonify({
            'message': (
                'The image has too many pixels to process safely on the server.'
            )
        }), 400
    except Exception:
        return jsonify({'message': 'The uploaded file is not a valid image'}), 400

    def form_float(name, default, minimum=None, maximum=None):
        try:
            value = float(request.form.get(name, default))
        except (TypeError, ValueError):
            value = float(default)
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    requested_width = form_float('width_feet', pixel_width, 1)
    requested_height = form_float('height_feet', requested_width * pixel_height / max(pixel_width, 1), 1)
    layer_id = uuid4().hex
    uploaded.stream.seek(0)
    original_bytes = uploaded.read()
    preview_buffer = io.BytesIO()
    try:
        with Image.open(io.BytesIO(original_bytes)) as source:
            if source.format == 'JPEG':
                source.draft('RGB', (5500, 5500))
            source.thumbnail((5500, 5500), Image.Resampling.LANCZOS)
            if source.mode != 'RGB':
                flattened = Image.new('RGB', source.size, 'white')
                if 'A' in source.getbands():
                    flattened.paste(source, mask=source.getchannel('A'))
                else:
                    flattened.paste(source)
                source = flattened
            preview_width, preview_height = source.size
            source.save(preview_buffer, 'JPEG', quality=90, optimize=True)
    except Exception:
        app.logger.exception('Unable to generate map reference viewer image')
        return jsonify({'message': 'The original was valid, but a viewer image could not be generated'}), 500

    original_asset = store_map_media_asset(
        campaign_id, original_bytes, secure_filename(uploaded.filename), uploaded.mimetype,
        purpose='map_reference_original', name=request.form.get('name'),
        pixel_width=pixel_width, pixel_height=pixel_height,
    )
    preview_asset = store_map_media_asset(
        campaign_id, preview_buffer.getvalue(), f'{Path(uploaded.filename).stem}-viewer.jpg', 'image/jpeg',
        purpose='map_reference_preview', name=request.form.get('name'),
        pixel_width=preview_width, pixel_height=preview_height,
    )

    layer = {
        'id': layer_id,
        'name': request.form.get('name', '').strip()[:120] or Path(uploaded.filename).stem[:120],
        'image_url': preview_asset.content_url,
        'image_asset_id': preview_asset.id,
        'original_image_url': original_asset.content_url,
        'original_image_asset_id': original_asset.id,
        'source_bytes': uploaded_size,
        'preview_pixel_width': preview_width,
        'preview_pixel_height': preview_height,
        'rendering_mode': 'viewer_derivative',
        'visible': True,
        'project_to_terrain': True,
        'opacity': form_float('opacity', 0.7, 0, 1),
        'origin_x': form_float('origin_x', 0),
        'origin_y': form_float('origin_y', 0),
        'width_feet': requested_width,
        'height_feet': requested_height,
        'rotation_degrees': form_float('rotation_degrees', 0, -360, 360),
        'pixel_width': pixel_width,
        'pixel_height': pixel_height,
        'feet_per_pixel': requested_width / max(pixel_width, 1),
        'feet_per_pixel_x': requested_width / max(pixel_width, 1),
        'feet_per_pixel_y': requested_height / max(pixel_height, 1),
        'layer_order': 0,
        'scope': request.form.get('scope', 'city') if request.form.get('scope') in {'city', 'building', 'battle'} else 'city',
        'linked_building_id': request.form.get('linked_building_id') or None,
        'sync_exterior': request.form.get('sync_exterior', '').lower() in {'1', 'true', 'yes', 'on'},
    }

    design = resolve_settlement(campaign_id, request.form.get('settlement_id'))
    if not design:
        return jsonify({'message': 'Settlement not found'}), 404
    if layer['sync_exterior'] and layer['linked_building_id']:
        linked = next((building for building in (design.buildings or []) if str(building.get('id')) == str(layer['linked_building_id'])), None)
        if linked:
            linked_width = float(linked.get('width_feet', layer['width_feet']))
            linked_height = float(linked.get('depth_feet', layer['height_feet']))
            layer.update({
                'origin_x': float(linked.get('x', 0)), 'origin_y': float(linked.get('y', 0)),
                'width_feet': linked_width, 'height_feet': linked_height,
                'feet_per_pixel': linked_width / max(pixel_width, 1),
                'feet_per_pixel_x': linked_width / max(pixel_width, 1),
                'feet_per_pixel_y': linked_height / max(pixel_height, 1),
                'rotation_degrees': float(linked.get('rotation', 0)) * 180 / 3.141592653589793,
            })
    design.reference_layers = [*(design.reference_layers or []), layer]
    design.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    payload = {**design.to_map_dict(), 'asset_catalog': SETTLEMENT_BUILDING_ASSETS}
    socketio.emit('settlement_map_updated', payload, to=f'campaign:{campaign_id}')
    return jsonify({'layer': layer, 'map': payload}), 201


@app.route('/api/settlement-map/<int:campaign_id>', methods=['PUT'])
@jwt_required()
def save_settlement_map_design(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may edit this map'}), 403

    data = request.get_json(silent=True) or {}
    terrain_strokes = data.get('terrain_strokes')
    roads = data.get('roads')
    water_bodies = data.get('water_bodies', [])
    buildings = data.get('buildings')
    reference_layers = data.get('reference_layers', [])
    environment = data.get('environment')
    if not all(isinstance(value, list) for value in (terrain_strokes, roads, water_bodies, buildings, reference_layers)):
        return jsonify({'message': 'terrain_strokes, roads, water_bodies, buildings, and reference_layers must be arrays'}), 400
    if environment is not None and (not isinstance(environment, dict) or not isinstance(environment.get('regions', []), list)):
        return jsonify({'message': 'environment must be an object and environment.regions must be an array'}), 400
    if environment is not None and len(environment.get('regions', [])) > 250:
        return jsonify({'message': 'Map design exceeds the region limit'}), 413
    if len(terrain_strokes) > 1500 or len(roads) > 500 or len(water_bodies) > 250 or len(buildings) > 5000 or len(reference_layers) > 100:
        return jsonify({'message': 'Map design exceeds the editor limits'}), 413
    if len(json.dumps(data)) > 2_000_000:
        return jsonify({'message': 'Map design payload exceeds 2 MB'}), 413

    design = resolve_settlement(campaign_id, data.get('settlement_id'))
    if not design:
        return jsonify({'message': 'Settlement not found'}), 404
    design.terrain_strokes = terrain_strokes
    design.roads = roads
    design.water_bodies = water_bodies
    design.buildings = buildings
    design.reference_layers = reference_layers
    if environment is not None:
        design.environment = environment
    design.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    payload = {**design.to_map_dict(), 'asset_catalog': SETTLEMENT_BUILDING_ASSETS}
    socketio.emit('settlement_map_updated', payload, to=f'campaign:{campaign_id}')
    return jsonify(payload), 200


@app.route('/api/settlement-simulation/<int:campaign_id>', methods=['GET'])
def settlement_simulation_state(campaign_id):
    if not Campaign.query.get(campaign_id):
        return jsonify({'message': 'Campaign not found'}), 404
    return jsonify(get_settlement_simulation_state(campaign_id)), 200


@app.route('/api/settlement-simulation/<int:campaign_id>/bootstrap', methods=['POST'])
def bootstrap_settlement_simulation(campaign_id):
    if not Campaign.query.get(campaign_id):
        return jsonify({'message': 'Campaign not found'}), 404
    location = ensure_campaign_settlement(campaign_id)
    blank_settlement = not any((location.terrain_strokes, location.roads, location.water_bodies, location.buildings, location.reference_layers))
    existing = LamplighterRoute.query.filter_by(campaign_id=campaign_id).first()
    if not existing and not blank_settlement:
        route = LamplighterRoute(campaign_id=campaign_id, name='Pinewater evening circuit')
        db.session.add(route)
        db.session.flush()
        stops = [(-550, 0), (-350, 260), (-80, 360), (220, 300), (410, 80), (320, -260), (40, -380), (-320, -310)]
        for order, (x, y) in enumerate(stops):
            db.session.add(StreetLamp(
                campaign_id=campaign_id,
                route_id=route.id,
                name=f'Pinewater lamp {order + 1}',
                x=x,
                y=y,
                elevation=0,
                route_order=order,
                fuel_remaining=100,
            ))
        db.session.commit()
    party_position = PartyMapPosition.query.filter_by(campaign_id=campaign_id).first()
    if not party_position:
        db.session.add(PartyMapPosition(campaign_id=campaign_id, map_key=location.map_key, x=0, y=0, road_access=True))
    if not blank_settlement and not MapPointOfInterest.query.filter_by(campaign_id=campaign_id).first():
        points = [
            ('Timber Hall', 'civic', -100, 0, False, True),
            ('River Landing', 'dock', 560, 40, True, True),
            ('North Gate', 'gate', -420, 330, False, True),
            ('Sunfield Farm', 'farm', -500, -500, False, True),
        ]
        for name, point_type, x, y, water_access, road_access in points:
            db.session.add(MapPointOfInterest(campaign_id=campaign_id, map_key='pinewater', name=name,
                                              point_type=point_type, x=x, y=y, water_access=water_access,
                                              road_access=road_access))
    db.session.commit()
    bootstrap_settlement_economy(campaign_id)
    state = emit_settlement_simulation_updated(campaign_id)
    return jsonify(state), 201 if not existing else 200


@app.route('/api/travel/<int:campaign_id>/context', methods=['GET'])
def get_travel_context(campaign_id):
    position = PartyMapPosition.query.filter_by(campaign_id=campaign_id).first()
    if not position:
        return jsonify({'message': 'Party position has not been set'}), 404
    points = MapPointOfInterest.query.filter_by(campaign_id=campaign_id).order_by(MapPointOfInterest.name).all()
    return jsonify({'party_position': position.to_dict(), 'points_of_interest': [point.to_dict() for point in points]}), 200


@app.route('/api/travel/<int:campaign_id>/party-position', methods=['PATCH'])
def update_party_map_position(campaign_id):
    data = request.json or {}
    position = PartyMapPosition.query.filter_by(campaign_id=campaign_id).first()
    if not position:
        position = PartyMapPosition(campaign_id=campaign_id)
        db.session.add(position)
    for field in ('map_key', 'x', 'y', 'elevation', 'water_access', 'road_access'):
        if field in data:
            setattr(position, field, data[field])
    position.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    socketio.emit('party_position_updated', position.to_dict(), to=f'campaign:{campaign_id}')
    return jsonify(position.to_dict()), 200


@app.route('/api/travel/<int:campaign_id>/calculate', methods=['POST'])
def calculate_travel(campaign_id):
    data = request.json or {}
    origin_record = PartyMapPosition.query.filter_by(campaign_id=campaign_id).first()
    if not origin_record:
        return jsonify({'message': 'Party position has not been set'}), 404

    destination = data.get('destination')
    poi_id = data.get('poi_id')
    if poi_id is not None:
        poi = MapPointOfInterest.query.filter_by(id=poi_id, campaign_id=campaign_id).first()
        if not poi:
            return jsonify({'message': 'Point of interest not found'}), 404
        destination = poi.to_dict()
    if not destination or destination.get('x') is None or destination.get('y') is None:
        return jsonify({'message': 'A destination point or poi_id is required'}), 400

    origin = origin_record.to_dict()
    destination.setdefault('map_key', origin['map_key'])
    try:
        estimate = estimate_travel_options(
            origin,
            destination,
            party_size=max(1, int(data.get('party_size', 1))),
            route_distance_miles=data.get('route_distance_miles'),
        )
    except (TypeError, ValueError) as error:
        return jsonify({'message': str(error)}), 400
    return jsonify({'origin': origin, 'destination': destination, **estimate}), 200


def bootstrap_settlement_economy(campaign_id):
    state = SettlementEconomyState.query.filter_by(campaign_id=campaign_id).first()
    if not state:
        db.session.add(SettlementEconomyState(campaign_id=campaign_id, day_index=0))
        location = ensure_campaign_settlement(campaign_id)
        if not any((location.terrain_strokes, location.roads, location.water_bodies, location.buildings, location.reference_layers)):
            db.session.commit()
            return
    elif not any((CommodityMarket.query.filter_by(campaign_id=campaign_id).first(),
                  SettlementBusiness.query.filter_by(campaign_id=campaign_id).first(),
                  OccupationDefinition.query.filter_by(campaign_id=campaign_id).first(),
                  SettlementEconomicAgent.query.filter_by(campaign_id=campaign_id).first())):
        return
    if not CommodityMarket.query.filter_by(campaign_id=campaign_id).first():
        markets = [
            ('ale','Ale',8,420,38,38,140), ('grain','Grain',2,900,72,72,300),
            ('timber','Timber',12,300,22,22,120), ('basic_food','Basic food',5,760,65,65,260),
        ]
        for key,name,price,target,demand,supply,imports in markets:
            db.session.add(CommodityMarket(campaign_id=campaign_id,commodity_key=key,name=name,base_price_cp=price,
                current_price_cp=price,stock=target,target_stock=target,daily_demand=demand,daily_supply=supply,
                import_threshold=.32,import_quantity=imports,elasticity=.65))
    if not SettlementBusiness.query.filter_by(campaign_id=campaign_id).first():
        businesses = [
            ('Trollskull Manor','tavern',0,0,1.15,1.05,1.0,50000,120,45,650,.38,True),
            ("Frewn's Brews",'tavern',240,80,.76,.82,.95,9000,75,36,520,.4,False),
            ('The Yawning Portal','tavern',1350,-900,1.4,1.3,1.0,140000,180,55,1100,.36,False),
        ]
        for name,btype,x,y,traffic,quality,access,reserves,capacity,sale,overhead,cogs,owned in businesses:
            db.session.add(SettlementBusiness(campaign_id=campaign_id,name=name,business_type=btype,x=x,y=y,
                foot_traffic=traffic,quality=quality,accessibility=access,cash_reserves_cp=reserves,daily_capacity=capacity,
                average_sale_cp=sale,daily_overhead_cp=overhead,cost_of_goods_rate=cogs,player_owned=owned))
    if not OccupationDefinition.query.filter_by(campaign_id=campaign_id).first():
        occupations=[
            ('laborer','Laborer',{'strength':.55,'constitution':.35,'dexterity':.1},3,18,'timber'),
            ('hauler','Hauler',{'strength':.65,'constitution':.25,'wisdom':.1},2,20,None),
            ('sales','Salesperson',{'charisma':.6,'wisdom':.25,'intelligence':.15},3,26,None),
            ('performer','Performer',{'charisma':.6,'dexterity':.25,'wisdom':.15},2,28,None),
            ('artisan','Artisan',{'dexterity':.4,'intelligence':.3,'wisdom':.2,'constitution':.1},3,32,None),
            ('farmer','Farmer',{'constitution':.4,'strength':.3,'wisdom':.3},4,20,'basic_food'),
            ('scholar','Scholar',{'intelligence':.6,'wisdom':.3,'charisma':.1},2,38,None),
            ('manager','Manager',{'intelligence':.35,'charisma':.35,'wisdom':.3},2,45,None),
        ]
        for key,name,weights,target,wage,commodity in occupations:
            db.session.add(OccupationDefinition(campaign_id=campaign_id,occupation_key=key,name=name,ability_weights=weights,target_workers=target,base_wage_cp=wage,produces_commodity_key=commodity))
    if not SettlementEconomicAgent.query.filter_by(campaign_id=campaign_id).first():
        ability_sets=[(17,10,16,8,9,8),(18,9,17,8,10,7),(16,12,15,9,11,8),(9,14,10,13,12,18),(8,16,10,11,13,19),(10,17,12,15,13,9),(12,15,13,16,14,10),(14,10,17,9,15,8),(13,11,16,10,17,9),(8,10,9,18,17,13),(9,13,10,17,15,14),(11,14,12,12,13,17),(15,13,15,10,12,11),(10,12,11,14,16,15)]
        for index,values in enumerate(ability_sets):
            db.session.add(SettlementEconomicAgent(campaign_id=campaign_id,name=f'Pinewater resident {index+1}',strength=values[0],dexterity=values[1],constitution=values[2],intelligence=values[3],wisdom=values[4],charisma=values[5],occupation_key='laborer',economic_autonomy=True,simulation_generated=True))
        family=NobleFamily(campaign_id=campaign_id,name='House Rosznar',wealth_cp=250000,investment_risk=.55)
        db.session.add(family);db.session.flush()
        db.session.add(SettlementEconomicAgent(campaign_id=campaign_id,name='Lady Rosznar',strength=8,dexterity=11,constitution=10,intelligence=16,wisdom=15,charisma=18,economic_autonomy=True,story_locked=True,simulation_generated=False,social_class='noble',noble_family_id=family.id,wealth_cp=20000))
    db.session.commit()


def run_workforce_rebalance(campaign_id,state,markets):
    occupations=OccupationDefinition.query.filter_by(campaign_id=campaign_id).all()
    agents=SettlementEconomicAgent.query.filter_by(campaign_id=campaign_id).all()
    price_by_key={market.commodity_key:market.current_price_cp/market.base_price_cp for market in markets}
    demand={occupation.occupation_key:min(1.6,max(.75,price_by_key.get(occupation.produces_commodity_key,1))) for occupation in occupations}
    businesses=SettlementBusiness.query.filter_by(campaign_id=campaign_id,closed=False).all()
    recent_profit=0;recent_overhead=0
    for business in businesses:
        rows=BusinessDailyLedger.query.filter(BusinessDailyLedger.business_id==business.id,BusinessDailyLedger.day_index>state.day_index-10).all()
        recent_profit+=sum(row.profit_cp for row in rows);recent_overhead+=business.daily_overhead_cp*max(1,len(rows))
    service_demand=min(1.45,max(.7,1+(recent_profit/max(1,recent_overhead))*.25))
    for key in ('sales','performer','manager'):
        if key in demand: demand[key]=service_demand
    agent_dicts=[agent.simulation_dict() for agent in agents]
    result=rebalance_workforce(agent_dicts,[occupation.simulation_dict() for occupation in occupations],state.day_index,demand)
    agents_by_id={agent.id:agent for agent in agents}
    for change in result['changes']:
        agent=agents_by_id[change['agent_id']];agent.occupation_key=change['to'];agent.career_cooldown_until_day=state.day_index+30
        db.session.add(EmploymentHistory(agent_id=agent.id,day_index=state.day_index,from_occupation=change['from'],to_occupation=change['to'],reason=change['reason']))
    return result


def run_noble_investment_meetings(campaign_id,state,businesses):
    decisions=[]
    for family in NobleFamily.query.filter_by(campaign_id=campaign_id,active=True).all():
        investments=NobleInvestment.query.filter_by(family_id=family.id).all()
        for investment in investments:
            business=next((item for item in businesses if item.id==investment.business_id),None)
            if not business: continue
            recent=BusinessDailyLedger.query.filter(BusinessDailyLedger.business_id==business.id,BusinessDailyLedger.day_index>state.day_index-10).all()
            profit=sum(row.profit_cp for row in recent);ownership=investment.principal_cp/max(1,investment.principal_cp+max(0,business.cash_reserves_cp))
            dividend=min(max(0,business.cash_reserves_cp),round(max(0,profit)*.15*ownership))
            if dividend:
                business.cash_reserves_cp-=dividend;family.wealth_cp+=dividend;investment.total_dividends_cp+=dividend
                db.session.add(NobleDecisionLedger(family_id=family.id,day_index=state.day_index,decision_type='dividend',business_id=business.id,amount_cp=dividend,summary=f'{family.name} received a dividend from {business.name}.'))
        recent_profit={}
        for business in businesses:
            rows=BusinessDailyLedger.query.filter(BusinessDailyLedger.business_id==business.id,BusinessDailyLedger.day_index>state.day_index-10).all()
            recent_profit[business.id]=sum(row.profit_cp for row in rows)
        choice=choose_noble_investment(family.to_dict(),[{**business.simulation_dict(),'desired_investment_cp':12000} for business in businesses],recent_profit,max_fraction=.05+.1*family.investment_risk)
        if choice:
            business=next(item for item in businesses if item.id==choice['business_id']);amount=min(choice['amount_cp'],family.wealth_cp)
            investment=NobleInvestment.query.filter_by(family_id=family.id,business_id=business.id).first()
            if not investment: investment=NobleInvestment(family_id=family.id,business_id=business.id);db.session.add(investment)
            investment.principal_cp+=amount;family.wealth_cp-=amount;business.cash_reserves_cp+=amount
            summary=f'{family.name} invested {amount} cp in {business.name} after its tenday meeting.'
            db.session.add(NobleDecisionLedger(family_id=family.id,day_index=state.day_index,decision_type='investment',business_id=business.id,amount_cp=amount,summary=summary));decisions.append(summary)
    return decisions


def economy_dashboard(campaign_id):
    state = SettlementEconomyState.query.filter_by(campaign_id=campaign_id).first()
    markets = CommodityMarket.query.filter_by(campaign_id=campaign_id).order_by(CommodityMarket.name).all()
    businesses = SettlementBusiness.query.filter_by(campaign_id=campaign_id).order_by(SettlementBusiness.name).all()
    history = {}
    for business in businesses:
        ledgers = BusinessDailyLedger.query.filter_by(business_id=business.id).order_by(BusinessDailyLedger.day_index).all()
        history[str(business.id)] = [ledger.to_dict() for ledger in ledgers[-40:]]
    agents=SettlementEconomicAgent.query.filter_by(campaign_id=campaign_id).all();occupations=OccupationDefinition.query.filter_by(campaign_id=campaign_id).all()
    counts={occupation.occupation_key:0 for occupation in occupations}
    for agent in agents:
        if agent.occupation_key in counts: counts[agent.occupation_key]+=1
    families=NobleFamily.query.filter_by(campaign_id=campaign_id).all();family_data=[]
    for family in families:
        investments=NobleInvestment.query.filter_by(family_id=family.id).all();decisions=NobleDecisionLedger.query.filter_by(family_id=family.id).order_by(NobleDecisionLedger.day_index.desc()).limit(10).all()
        family_data.append({**family.to_dict(),'investments':[item.to_dict() for item in investments],'recent_decisions':[{'day_index':item.day_index,'type':item.decision_type,'amount_cp':item.amount_cp,'summary':item.summary} for item in decisions]})
    return {'day_index':state.day_index if state else 0,'markets':[market.to_dict() for market in markets],
            'businesses':[business.to_dict() for business in businesses],'history':history,
            'workforce':{'occupations':[{**occupation.to_dict(),'workers':counts[occupation.occupation_key]} for occupation in occupations],'agents':[agent.to_dict() for agent in agents]},'noble_families':family_data}


def run_economy(campaign_id, days):
    bootstrap_settlement_economy(campaign_id)
    state = SettlementEconomyState.query.filter_by(campaign_id=campaign_id).first()
    markets = CommodityMarket.query.filter_by(campaign_id=campaign_id).all()
    for _ in range(days):
        state.day_index += 1
        for market in markets:
            result = simulate_commodity_day({'base_price_cp':market.base_price_cp,'stock':market.stock,
                'target_stock':market.target_stock,'elasticity':market.elasticity,'daily_demand':market.daily_demand,
                'daily_supply':market.daily_supply,'import_threshold':market.import_threshold,'import_quantity':market.import_quantity})
            market.stock=result['stock'];market.current_price_cp=result['price_cp'];market.last_imported=result['imported']
        businesses = SettlementBusiness.query.filter_by(campaign_id=campaign_id).all()
        by_type = {}
        for business in businesses: by_type.setdefault(business.business_type,[]).append(business)
        for business in businesses:
            result = simulate_business_day(business.simulation_dict(),[item.simulation_dict() for item in by_type[business.business_type]],state.day_index)
            business.cash_reserves_cp=result['cash_reserves_cp'];business.slump_days=result['slump_days'];business.closed=result['closed']
            db.session.add(BusinessDailyLedger(business_id=business.id,day_index=state.day_index,customers=result['customers'],
                revenue_cp=result['revenue_cp'],costs_cp=result['costs_cp'],profit_cp=result['profit_cp'],
                cash_reserves_cp=result['cash_reserves_cp'],market_share=result.get('market_share')))
        if state.day_index % 10 == 0:
            run_workforce_rebalance(campaign_id,state,markets)
            run_noble_investment_meetings(campaign_id,state,businesses)
    db.session.commit()
    dashboard=economy_dashboard(campaign_id)
    socketio.emit('settlement_economy_updated',dashboard,to=f'campaign:{campaign_id}')
    return dashboard


@app.route('/api/economy/<int:campaign_id>',methods=['GET'])
def get_economy(campaign_id):
    bootstrap_settlement_economy(campaign_id)
    return jsonify(economy_dashboard(campaign_id)),200


@app.route('/api/economy/<int:campaign_id>/simulate',methods=['POST'])
def simulate_economy(campaign_id):
    days=max(1,min(40,int((request.json or {}).get('days',1))))
    return jsonify(run_economy(campaign_id,days)),200


@app.route('/api/economy/<int:campaign_id>/commodities/<commodity_key>/purchase',methods=['POST'])
def purchase_market_commodity(campaign_id,commodity_key):
    market=CommodityMarket.query.filter_by(campaign_id=campaign_id,commodity_key=commodity_key).first()
    if not market: return jsonify({'message':'Commodity not found'}),404
    quantity=max(1,float((request.json or {}).get('quantity',1)))
    purchased=min(quantity,market.stock);market.stock-=purchased
    market.current_price_cp=commodity_price(market.base_price_cp,market.stock,market.target_stock,market.elasticity)
    db.session.commit()
    dashboard=economy_dashboard(campaign_id)
    socketio.emit('settlement_economy_updated',dashboard,to=f'campaign:{campaign_id}')
    return jsonify({'purchased':purchased,'total_cost_cp':round(purchased*market.current_price_cp),'market':market.to_dict(),'dashboard':dashboard}),200


@app.route('/api/economy/<int:campaign_id>/agents/link-npc/<int:npc_id>',methods=['POST'])
def link_npc_to_economy(campaign_id,npc_id):
    npc=NPC.query.filter_by(id=npc_id,campaign_id=campaign_id).first()
    if not npc: return jsonify({'message':'NPC not found'}),404
    existing=SettlementEconomicAgent.query.filter_by(npc_id=npc_id).first()
    if existing: return jsonify(existing.to_dict()),200
    data=request.json or {};agent=SettlementEconomicAgent(campaign_id=campaign_id,npc_id=npc.id,name=npc.name,
        strength=npc.strength,dexterity=npc.dexterity,constitution=npc.constitution,intelligence=npc.intelligence,wisdom=npc.wisdom,charisma=npc.charisma,
        economic_autonomy=bool(data.get('economic_autonomy',False)),story_locked=bool(data.get('story_locked',True)),simulation_generated=False,
        social_class=data.get('social_class','commoner'),occupation_key=data.get('occupation_key'),noble_family_id=data.get('noble_family_id'),wealth_cp=max(0,int(data.get('wealth_cp',0))))
    if agent.social_class=='noble': agent.occupation_key=None
    db.session.add(agent);db.session.commit()
    return jsonify(agent.to_dict()),201


@app.route('/api/economy/<int:campaign_id>/agents/<int:agent_id>',methods=['PATCH'])
def update_economic_agent(campaign_id,agent_id):
    agent=SettlementEconomicAgent.query.filter_by(id=agent_id,campaign_id=campaign_id).first()
    if not agent: return jsonify({'message':'Economic agent not found'}),404
    data=request.json or {}
    for field in ('economic_autonomy','story_locked','occupation_key','employer_business_id','noble_family_id','social_class','wealth_cp'):
        if field in data: setattr(agent,field,data[field])
    if agent.social_class=='noble': agent.occupation_key=None;agent.employer_business_id=None
    db.session.commit();return jsonify(agent.to_dict()),200


@app.route('/api/economy/<int:campaign_id>/workforce/rebalance',methods=['POST'])
def rebalance_campaign_workforce(campaign_id):
    bootstrap_settlement_economy(campaign_id);state=SettlementEconomyState.query.filter_by(campaign_id=campaign_id).first();markets=CommodityMarket.query.filter_by(campaign_id=campaign_id).all()
    result=run_workforce_rebalance(campaign_id,state,markets);db.session.commit();dashboard=economy_dashboard(campaign_id)
    socketio.emit('settlement_economy_updated',dashboard,to=f'campaign:{campaign_id}')
    return jsonify({'result':result,'dashboard':dashboard}),200


#GET    /api/calendar/<campaign_id>'
@app.route('/api/calendar/<int:campaign_id>', methods=['GET'])
def get_calendar(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()

    if not calendar:
        return jsonify({
            "configured": False,
            "message": f"No calendar found for campaign {campaign_id}",
        }), 200

    return jsonify(calendar.to_dict()), 200


CALENDAR_FORMAT_SOURCES = {
    'gregorian': {
        'name': 'Gregorian Calendar',
        'filename': 'Gregorian.json',
        'system': 'universal',
        'setting': 'Real World',
    },
    'harptos': {
        'name': 'Calendar of Harptos',
        'filename': 'Harptos.json',
        'system': 'D&D 5e',
        'setting': 'Forgotten Realms',
    },
}


def ensure_calendar_format(format_slug):
    source = CALENDAR_FORMAT_SOURCES.get(format_slug)
    if not source:
        return None
    element = GameElement.query.filter_by(
        element_type='calendar_format',
        name=source['name'],
    ).first()
    if element:
        return element
    calendar_path = Path(app.root_path) / source['filename']
    with calendar_path.open('r', encoding='utf-8') as calendar_file:
        format_data = json.load(calendar_file)
    element = GameElement(
        system=source['system'],
        element_type='calendar_format',
        module=None,
        setting=source['setting'],
        name=source['name'],
        data=format_data,
    )
    db.session.add(element)
    db.session.flush()
    return element


@app.route('/api/calendar-formats', methods=['GET'])
@jwt_required()
def get_calendar_formats():
    formats = []
    for slug, source in CALENDAR_FORMAT_SOURCES.items():
        element = GameElement.query.filter_by(
            element_type='calendar_format',
            name=source['name'],
        ).first()
        display_name = (element.data or {}).get('display_name') if element else source['name']
        formats.append({
            'slug': slug,
            'name': source['name'],
            'display_name': display_name or source['name'],
            'system': source['system'],
        })
    return jsonify({'formats': formats}), 200


@app.route('/api/calendar/<int:campaign_id>', methods=['POST'])
@jwt_required()
def create_campaign_calendar(campaign_id):
    campaign = Campaign.query.get(campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if not user_can_edit_campaign(campaign):
        return jsonify({'message': 'Only the campaign DM or owner may set up its calendar'}), 403
    existing = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if existing:
        return jsonify(existing.to_dict()), 200

    data = request.get_json(silent=True) or {}
    format_slug = str(data.get('format_slug') or 'gregorian').strip().lower()
    format_element = ensure_calendar_format(format_slug)
    if not format_element:
        return jsonify({'message': 'Unsupported calendar format'}), 400

    try:
        current_year = int(data.get('year', 1))
        current_month_index = int(data.get('month_index', 0))
        current_day = int(data.get('day', 1))
    except (TypeError, ValueError):
        return jsonify({'message': 'Year, month, and day must be whole numbers'}), 400

    months = (format_element.data or {}).get('months', [])
    if not months or current_month_index < 0 or current_month_index >= len(months):
        return jsonify({'message': 'The selected month is not valid for this calendar'}), 400
    max_day = int(months[current_month_index].get('length', 0))
    if current_day < 1 or current_day > max_day:
        return jsonify({'message': f'Day must be between 1 and {max_day}'}), 400

    calendar = Calendar(
        name=str(data.get('name') or f'{campaign.name} Calendar').strip()[:100],
        description=str(data.get('description') or f'Calendar for {campaign.name}').strip(),
        campaign_id=campaign.id,
        format_id=format_element.id,
        format_slug=format_slug,
        current_year=current_year,
        current_month_index=current_month_index,
        current_day=current_day,
        current_hour=0,
        current_minute=0,
        epoch_year=1,
        epoch_month_index=0,
        epoch_day=1,
    )
    db.session.add(calendar)
    db.session.commit()
    emit_calendar_updated(campaign_id, {'kind': 'calendar_created'})
    return jsonify(calendar.to_dict()), 201

#POST   /api/calendar/<campaign_id>/date/set
@app.route('/api/calendar/<int:campaign_id>/date/set', methods=['POST'])
def set_calendar_date(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    data = request.json or {}

    year = data.get('year')
    month_index = data.get('month_index')
    day = data.get('day')
    hour = data.get('hour', 0)
    minute = data.get('minute', 0)

    if year is None or month_index is None or day is None:
        return jsonify({"message": "year, month_index, and day are required"}), 400

    total_days = days_in_month(calendar, year, month_index)
    if day < 1 or day > total_days:
        return jsonify({"message": f"day must be between 1 and {total_days}"}), 400

    calendar.current_year = year
    calendar.current_month_index = month_index
    calendar.current_day = day
    calendar.current_hour = hour
    calendar.current_minute = minute

    db.session.commit()

    emit_settlement_simulation_updated(campaign_id)

    return jsonify(calendar.to_dict()), 200

#POST   /api/calendar/<campaign_id>/date/advance
@app.route('/api/calendar/<int:campaign_id>/date/advance', methods=['POST'])
def advance_calendar_date(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    data = request.json or {}

    delta_days = data.get('days', 0)
    delta_hours = data.get('hours', 0)
    delta_minutes = data.get('minutes', 0)

    current_date = {
        'year': calendar.current_year,
        'month_index': calendar.current_month_index,
        'day': calendar.current_day,
        'hour': calendar.current_hour,
        'minute': calendar.current_minute,
    }

    new_date = advance_date(calendar, current_date, delta_days, delta_hours, delta_minutes)

    calendar.current_year = new_date['year']
    calendar.current_month_index = new_date['month_index']
    calendar.current_day = new_date['day']
    calendar.current_hour = new_date['hour']
    calendar.current_minute = new_date['minute']

    db.session.commit()

    emit_calendar_updated(
        campaign_id,
        {
            "kind": "current_date",
            "current_date": {
                "year": calendar.current_year,
                "month_index": calendar.current_month_index,
                "day": calendar.current_day,
                "hour": calendar.current_hour,
                "minute": calendar.current_minute,
            }
        }
    )

    emit_settlement_simulation_updated(campaign_id)

    return jsonify(calendar.to_dict()), 200

#GET    /api/calendar/<campaign_id>/date
@app.route('/api/calendar/<int:campaign_id>/date', methods=['GET'])
def get_calendar_date(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    months = get_months(calendar)
    current_month = months[calendar.current_month_index] if 0 <= calendar.current_month_index < len(months) else None

    return jsonify({
        'year': calendar.current_year,
        'month_index': calendar.current_month_index,
        'month_name': current_month.get('name') if current_month else None,
        'month_subtitle': current_month.get('subtitle') if current_month else None,
        'day': calendar.current_day,
        'hour': calendar.current_hour,
        'minute': calendar.current_minute,
    }), 200

#GET    /api/calendar/<campaign_id>/events
@app.route('/api/calendar/<int:campaign_id>/events', methods=['GET'])
def get_calendar_events(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    events = CalendarEvent.query.filter_by(calendar_id=calendar.id).order_by(
        CalendarEvent.start_year,
        CalendarEvent.start_month_index,
        CalendarEvent.start_day,
        CalendarEvent.start_hour,
        CalendarEvent.start_minute
    ).all()

    return jsonify([event.to_dict() for event in events]), 200


#POST   /api/calendar/<campaign_id>/events
@app.route('/api/calendar/<int:campaign_id>/events', methods=['POST'])
def create_calendar_event(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    data = request.json or {}

    event = CalendarEvent(
        calendar_id=calendar.id,
        name=data.get('name'),
        description=data.get('description'),
        color=data.get('color'),
        start_year=data.get('year'),
        start_month_index=data.get('month_index'),
        start_day=data.get('day'),
        start_hour=data.get('hour'),
        start_minute=data.get('minute'),
    )

    db.session.add(event)
    db.session.commit()

    emit_calendar_updated(
        campaign_id,
        {
            "kind": "event",
            "year": event.start_year,
            "month_index": event.start_month_index,
            "day": event.start_day,
        }
    )

    return jsonify(event.to_dict()), 201

#PATCH  /api/calendar/events/<event_id>
@app.route('/api/calendar/events/<int:event_id>', methods=['PATCH'])
def update_calendar_event(event_id):
    event = CalendarEvent.query.get(event_id)
    if not event:
        return jsonify({"message": f"Event {event_id} not found"}), 404

    calendar = event.calendar

    old_year = event.start_year
    old_month_index = event.start_month_index
    old_day = event.start_day

    data = request.json or {}

    if 'name' in data:
        event.name = data['name']
    if 'description' in data:
        event.description = data['description']
    if 'color' in data:
        event.color = data['color']
    if 'year' in data:
        event.start_year = data['year']
    if 'month_index' in data:
        event.start_month_index = data['month_index']
    if 'day' in data:
        event.start_day = data['day']
    if 'hour' in data:
        event.start_hour = data['hour']
    if 'minute' in data:
        event.start_minute = data['minute']

    db.session.commit()

    emit_calendar_updated(
        calendar.campaign_id,
        {
            "kind": "event_updated",
            "old_year": old_year,
            "old_month_index": old_month_index,
            "old_day": old_day,
            "year": event.start_year,
            "month_index": event.start_month_index,
            "day": event.start_day,
        }
    )

    return jsonify(event.to_dict()), 200

#DELETE /api/calendar/events/<event_id>
@app.route('/api/calendar/events/<int:event_id>', methods=['DELETE'])
def delete_calendar_event(event_id):
    event = CalendarEvent.query.get(event_id)
    if not event:
        return jsonify({"message": f"Event {event_id} not found"}), 404

    calendar = event.calendar

    old_year = event.start_year
    old_month_index = event.start_month_index
    old_day = event.start_day
    campaign_id = calendar.campaign_id

    db.session.delete(event)
    db.session.commit()

    emit_calendar_updated(
        campaign_id,
        {
            "kind": "event_deleted",
            "year": old_year,
            "month_index": old_month_index,
            "day": old_day,
        }
    )

    return jsonify({"message": f"Deleted event {event_id}"}), 200

#GET    /api/calendar/<campaign_id>/month-view
@app.route('/api/calendar/<int:campaign_id>/month-view', methods=['GET'])
def get_calendar_month_view(campaign_id):
    '''
    Returns the current month's calendar data for the specified campaign, including events, holidays, and moon phases for each day.
    '''
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    year = request.args.get('year', type=int, default=calendar.current_year)
    month_index = request.args.get('month_index', type=int, default=calendar.current_month_index)

    months = get_months(calendar)
    weekdays = get_weekdays(calendar)
    moons = get_moons(calendar)

    if month_index < 0 or month_index >= len(months):
        return jsonify({"message": "month_index out of range"}), 400

    month = months[month_index]
    total_days = days_in_month(calendar, year, month_index)

    events = CalendarEvent.query.filter_by(
        calendar_id=calendar.id,
        start_year=year,
        start_month_index=month_index
    ).all()

    event_map = {}
    for event in events:
        event_map.setdefault(event.start_day, []).append(event.to_dict())

    holidays_for_month = get_holidays_for_month(calendar, year, month_index)
    holiday_map = {}
    for holiday in holidays_for_month:
        holiday_day = holiday.get('day')
        if holiday_day is not None and 1 <= holiday_day <= total_days:
            holiday_map.setdefault(holiday_day, []).append(holiday)

    days = []
    for day_num in range(1, total_days + 1):
        ordinal = date_to_ordinal(calendar, year, month_index, day_num)

        moon_data = []
        for moon in moons:
            moon_data.append({
                'name': moon.get('name', 'Moon'),
                'phase': get_moon_phase(moon, ordinal)
            })

        days.append({
            'year': year,
            'month_index': month_index,
            'day': day_num,
            'events': event_map.get(day_num, []),
            'holidays': holiday_map.get(day_num, []),
            'moons': moon_data,
            'weather_icon': ''
        })

    return jsonify({
        'year': year,
        'month_index': month_index,
        'month': month,
        'columns': weekdays,
        'days': days,
        'current_date': {
            'year': calendar.current_year,
            'month_index': calendar.current_month_index,
            'month_name': months[calendar.current_month_index].get('name') if 0 <= calendar.current_month_index < len(months) else None,
            'month_subtitle': months[calendar.current_month_index].get('subtitle') if 0 <= calendar.current_month_index < len(months) else None,
            'day': calendar.current_day,
            'hour': calendar.current_hour,
            'minute': calendar.current_minute,
        }
    }), 200


#GET    /api/calendar/<campaign_id>/moon-phases
@app.route('/api/calendar/<int:campaign_id>/moon-phases', methods=['GET'])
def get_calendar_moon_phases(campaign_id):
    return jsonify({"message": f"Moon phases for campaign {campaign_id}"})

#GET    /api/calendar/<campaign_id>/holidays
@app.route('/api/calendar/<int:campaign_id>/holidays', methods=['GET'])
def get_calendar_holidays(campaign_id):
    calendar = Calendar.query.filter_by(campaign_id=campaign_id).first()
    if not calendar:
        return jsonify({"message": f"No calendar found for campaign {campaign_id}"}), 404

    year = request.args.get('year', type=int, default=calendar.current_year)
    month_index = request.args.get('month_index', type=int)

    if month_index is not None:
        holidays = get_holidays_for_month(calendar, year, month_index)
    else:
        holidays = get_holidays(calendar)

    return jsonify(holidays), 200

## Chat Functions (more in SocketIO stuff)
def serialize_message_participant(character):
    if not character:
        return None

    avatar = character.get_avatar_props()

    return {
        'userID': character.userID,
        'characterID': character.id,
        'character_name': character.character_name,
        'name': character.character_name,
        'mode': avatar.get('mode'),
        'initials': avatar.get('initials'),
        'color': avatar.get('color'),
        'text_color': avatar.get('text_color'),
        'image_url': avatar.get('image_url'),
        'preset_key': avatar.get('preset_key'),
        'shape': avatar.get('shape'),
        'frame_color': avatar.get('frame_color'),
    }

@app.route('/api/chat_history', methods=['GET'])
@jwt_required()
def get_chat_history():
    username = get_jwt_identity()
    user = User.query.filter_by(username=username).first()
    campaignID = request.headers.get('CampaignID')

    if user is None:
        return jsonify({'message': 'User not found'}), 404

    if not campaignID:
        return jsonify({'message': 'CampaignID header is required'}), 400

    # Get the current user's character in this campaign
    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID,
        campaign_members.c.userID == user.id
    )
    result = db.session.execute(stmt).first()
    characterID = result.characterID if result else None

    if characterID is None:
        app.logger.error(
            "Character not found for user_id: %s in campaign_id: %s",
            user.id,
            campaignID
        )
        return jsonify({'message': 'Character not found'}), 404

    # Build user -> character map for this campaign
    user_to_character_map = {}
    campaign_memberships = db.session.execute(
        select(campaign_members.c.userID, campaign_members.c.characterID).where(
            campaign_members.c.campaignID == campaignID
        )
    ).fetchall()

    for membership in campaign_memberships:
        user_to_character_map[membership.userID] = membership.characterID

    def get_character_for_user(user_id):
        character_id = user_to_character_map.get(user_id)
        if not character_id:
            return None
        return Character.query.filter_by(id=character_id).first()

    def message_to_client_format(message):
        sender_character = get_character_for_user(message.sender_id)
        sender_name = sender_character.character_name if sender_character else 'Unknown'

        recipient_ids = [
            int(id_str) for id_str in (message.recipient_ids or '').split(',')
            if id_str.strip()
        ]

        recipient_characters = [
            get_character_for_user(recipient_user_id)
            for recipient_user_id in recipient_ids
        ]
        recipient_characters = [character for character in recipient_characters if character is not None]

        recipient_names = [
            character.character_name for character in recipient_characters
        ]

        item = Item.query.filter_by(id=message.item_id).first() if message.item_id else None
        item_details = {'id': item.id, 'name': item.name} if item else None

        self_character = get_character_for_user(user.id)

        return {
            'campaignID': int(campaignID),
            'group_id': message.group_id,
            'item': item_details,
            'recipient_character_names': recipient_names,
            'recipient_avatars': [
                serialize_message_participant(character)
                for character in recipient_characters
            ],
            'recipients': recipient_ids,
            'sender': message.sender_id,
            'sender_character_name': sender_name,
            'sender_avatar': sender_character.get_avatar_props() if sender_character else None,
            'self_avatar': self_character.get_avatar_props() if self_character else None,
            'text': message.message_text,
            'type': message.message_type,
            'timestamp': message.timestamp.isoformat() if message.timestamp else None,
        }

    # Fetch all messages for this user in this campaign
    sent_messages = Message.query.filter_by(
        sender_id=user.id,
        campaign_id=campaignID
    ).all()

    received_messages = Message.query.filter(
        Message.recipient_ids.contains(str(user.id)),
        Message.campaign_id == campaignID
    ).all()

    # De-duplicate in case a message appears in both queries
    all_messages = {message.id: message for message in (sent_messages + received_messages)}
    messages = sorted(all_messages.values(), key=lambda msg: msg.timestamp)

    messages_json = [message_to_client_format(message) for message in messages]

    return jsonify(messages_json), 200

##************************##
## **  SocketIO Stuff  ** ##
##************************##
def emit_active_users(campaign_id, to_sid=None):
    if not campaign_id:
        app.logger.error("ONLINE USERS - Campaign ID is missing")
        return

    app.logger.debug("ONLINE USERS - Fetching active users for campaign_id: %s", campaign_id)

    stmt = (
        db.session.query(
            campaign_members.c.userID,
            campaign_members.c.characterID
        )
        .filter(campaign_members.c.campaignID == campaign_id)
        .subquery()
    )

    active_users_query = (
        db.session.query(User, Character)
        .join(stmt, stmt.c.userID == User.id)
        .join(Character, Character.id == stmt.c.characterID)
        .filter(User.is_online == True)
    )
    active_users = active_users_query.all()

    active_user_info = [
        {
            'username': user.username,
            'character_name': character.character_name,
            'userID': user.id,
            'avatar': character.get_avatar_props(),
        }
        for user, character in active_users
    ]

    if to_sid is False:
        target = f"campaign:{campaign_id}"
    elif to_sid:
        target = to_sid
    else:
        target = request.sid

    app.logger.debug(
        "ONLINE USERS - Emitting %s active users to target %s",
        len(active_user_info),
        target
    )

    socketio.emit('active_users', active_user_info, to=target)

@socketio.on("request_active_users")
@socket_db_session
def handle_request_active_users(data):
    campaign_id = data.get('campaignID')
    app.logger.debug("Request Active Users - campaign_id: %s", campaign_id)
    if campaign_id:
        emit_active_users(campaign_id, to_sid=request.sid)
    else:
        app.logger.error("Request Active Users - Missing campaign ID")

@socketio.on("connect")
@socket_db_session
def connected():
    """event listener when client connects to the server"""
    app.logger.info("Socket Connection Triggered")
    try:
        token = request.args.get('token')  # Get the token from the request arguments
        if not token:
            app.logger.error("CONNECT- No token provided")
            disconnect()
            return

        app.logger.info("CONNECT- Received a token")
        if token and request.args.get("username"):
            username = request.args.get("username")
            if not username:
                app.logger.error("JOIN ROOM- Missing username")
                disconnect()
                return
            
            # Protect access to shared active_connections mapping
            with active_connections_lock:
                if username in active_connections:
                    app.logger.info(f"Disconnecting duplicate connection for user: {username}")
                    disconnect()
                    return

            user = User.query.filter(func.lower(User.username) == username.lower()).first()
            app.logger.info("CONNECT- username: %s", username)
            app.logger.info("CONNECT- user: %s", user)
            if not user:
                app.logger.error("JOIN ROOM- User not found: %s", username)
                disconnect()
                return
            
            if user:
                app.logger.info("CONNECT- setting %s to online", user)
                user.is_online = True
                user.sid = request.sid  # Update the SID associated with this user
                # Persist online state immediately so other threads/handlers can see it
                try:
                    db.session.commit()
                    app.logger.debug("CONNECT- committed online state for user: %s (sid=%s)", user.username, user.sid)
                except Exception as e:
                    app.logger.error("CONNECT- failed to commit user online state: %s", e)
                campaign_id = request.args.get('campaignID')  # Retrieve the campaignID from the request arguments

                if not campaign_id:
                    app.logger.info("CONNECT- No campaign ID provided, requesting from client")
                    emit('request_campaignID')
                else:
                    app.logger.debug("CONNECT- campaign_id: %s", campaign_id)
                    emit_active_users(campaign_id, to_sid=False)
            else:
                app.logger.error("CONNECT- User not found")
                disconnect()
    except jwt.ExpiredSignatureError:
        app.logger.error("CONNECT- Token is expired")
        emit('token_expired')
        disconnect()
    except Exception as e:
        app.logger.error(f"CONNECT- An error occurred: {e}")
        disconnect()

@socketio.on('join_room')
@socket_db_session
def handle_join_room(data):
    username = data.get('username')
    campaign_id = data.get('campaign_id')

    app.logger.debug('JOIN ROOM- User connected: %s', username)

    if not isinstance(username, str) or not username.strip():
        app.logger.error('JOIN ROOM- Missing username')
        disconnect()
        return

    user = User.query.filter(func.lower(User.username) == username.lower()).first()
    if not user:
        app.logger.error("JOIN ROOM- User not found: %s", username)
        disconnect()
        return

    app.logger.debug("JOIN ROOM- user's initial status: %s", user.is_online)

    with active_connections_lock:
        existing_sid = active_connections.get(username)

        if existing_sid and existing_sid != request.sid:
            app.logger.info(
                "JOIN ROOM- Replacing old SID %s with new SID %s for user %s",
                existing_sid, request.sid, username
            )

        user.is_online = True
        user.sid = request.sid
        active_connections[username] = request.sid
        db.session.commit()

    # Join personal room for direct messages
    join_room(f"user:{user.id}")
    app.logger.debug("JOIN ROOM- User %s joined personal room user:%s", user.username, user.id)

    # Join campaign room for broadcasts like active_users
    if campaign_id:
        join_room(f"campaign:{campaign_id}")
        app.logger.debug("JOIN ROOM- User %s joined campaign room campaign:%s", user.username, campaign_id)

        socketio.emit(
            'status',
            {'message': f'User {user.username} joined room {campaign_id}'},
            to=f"campaign:{campaign_id}"
        )

        emit_active_users(campaign_id, to_sid=False)


@socketio.on('settlement_player_command')
@socket_db_session
def handle_settlement_player_command(data):
    """Relay transient, DM-controlled map presentation state to campaign viewers."""
    try:
        identity = decode_token(request.args.get('token') or '')['sub']
    except Exception:
        emit('settlement_player_command_error', {'message': 'The map presentation session is not authenticated.'})
        return
    user = User.query.filter(func.lower(User.username) == str(identity).lower()).first()
    try:
        campaign_id = int((data or {}).get('campaign_id'))
        settlement_id = int((data or {}).get('settlement_id'))
    except (TypeError, ValueError):
        emit('settlement_player_command_error', {'message': 'A campaign and settlement are required.'})
        return

    campaign = Campaign.query.get(campaign_id)
    if not user or not campaign or user.id not in {campaign.owner_id, campaign.dm_id}:
        emit('settlement_player_command_error', {'message': 'Only the campaign DM can control Player View.'})
        return
    if not WorldAtlasLocation.query.filter_by(id=settlement_id, campaign_id=campaign_id).first():
        emit('settlement_player_command_error', {'message': 'That settlement is not part of this campaign.'})
        return

    action = (data or {}).get('action')
    command = {'campaign_id': campaign_id, 'settlement_id': settlement_id, 'action': action}

    def vector(value):
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return None
        try:
            result = [float(component) for component in value]
        except (TypeError, ValueError):
            return None
        return result if all(abs(component) <= 10_000_000 for component in result) else None

    if action == 'camera':
        camera = (data or {}).get('camera') or {}
        position, target = vector(camera.get('position')), vector(camera.get('target'))
        if position is None or target is None:
            return
        command['camera'] = {'position': position, 'target': target}
    elif action == 'focus':
        point = (data or {}).get('point') or {}
        try:
            x, y = float(point.get('x')), float(point.get('y'))
            elevation = float(point.get('elevation') or 0)
        except (TypeError, ValueError):
            return
        if any(abs(value) > 10_000_000 for value in (x, y, elevation)):
            return
        command['point'] = {'x': x, 'y': y, 'elevation': elevation}
    elif action == 'label':
        building_id = str((data or {}).get('building_id') or '')[:120]
        if not building_id:
            return
        command.update({'building_id': building_id, 'visible': bool((data or {}).get('visible'))})
    elif action == 'labels_all':
        command['visible'] = bool((data or {}).get('visible'))
    else:
        return

    socketio.emit('settlement_player_command', command, to=f'campaign:{campaign_id}')


@socketio.on('leave_room')
@socket_db_session
def handle_leave_room(data):
    campaign_id = data.get('campaign_id')  # From the client
    user_id = request.sid
    if campaign_id:
        leave_room(campaign_id)  # Remove the user from the room
        emit('status', {'message': f'User {user_id} left room {campaign_id}'}, to=campaign_id)

@socketio.on('send_campaignID')
@socket_db_session
def handle_send_campaignID(data):
    campaign_id = data.get('campaignID')
    app.logger.info(f"Received campaign ID from client: {campaign_id}")

    if campaign_id:
        user = User.query.filter_by(sid=request.sid).first()
        if user:
            app.logger.info(f"Updating campaign ID for user: {user.username}")
            emit_active_users(campaign_id, to_sid=False)
        else:
            app.logger.error("User not found for the given SID")
            disconnect()
    else:
        app.logger.error("No campaign ID received from client")
        disconnect()


@socketio.on('sendMessage')
@socket_db_session
def handle_send_message(messageObj):
    app.logger.debug("MESSAGE- messageObj: %s", messageObj)

    message = messageObj['text']
    sender = messageObj['sender']   # 'sender' should be the userID
    recipients = messageObj['recipients']

    campaignID = messageObj['campaignID']
    # campaignID = request.headers.get('CampaignID')
    app.logger.debug("MESSAGE- campaignID: %s", campaignID)
    app.logger.debug("MESSAGE- recipients: %s", recipients)

    recipient_characters = []
    
    if isinstance(recipients, dict):
        recipients = [recipients]
    
    for recipient in recipients:
        try:
            app.logger.debug("MESSAGE- Trying: %s", recipient["userID"])
            recipient_character = Character.query.join(User, User.id == Character.userID).join(campaign_members, Character.id == campaign_members.c.characterID).filter(User.id == recipient["userID"], campaign_members.c.campaignID == campaignID).first()
        except:
            app.logger.debug("MESSAGE- Using: %s", recipient)
            recipient_character = Character.query.join(User, User.id == Character.userID).join(campaign_members, Character.id == campaign_members.c.characterID).filter(User.id == recipient, campaign_members.c.campaignID == campaignID).first()
        if recipient_character:
            recipient_characters.append(recipient_character)
    
    app.logger.debug("MESSAGE- sender: %s", sender)
    
    # # Step 1: Get the userID from the User table using the sender's username
    # user = User.query.filter_by(username=sender.lower()).first()
    # if not user:
    #     app.logger.error("MESSAGE- sender user not found")
    #     return jsonify({'message': 'Sender user not found'}), 404
    
    # app.logger.debug("MESSAGE- Sending user found in database: %s", user.to_dict())
    
    # Step 2: Get the characterID from the campaign_members table using userID and campaignID
    campaign_member = db.session.query(campaign_members).filter_by(userID=sender, campaignID=campaignID).first()
    if not campaign_member:
        app.logger.error("MESSAGE- sender character not found in campaign")
        return jsonify({'message': 'Sender character not found in campaign'}), 404
    
    # Step 3: Get the Character entry using the characterID
    stmt = select(campaign_members.c.characterID).where(
        campaign_members.c.campaignID == campaignID, 
        campaign_members.c.userID == sender
    )

    result = db.session.execute(stmt).first()

    characterID = result.characterID if result else None

    app.logger.debug("CharacterID- %s", characterID)
    
    sender_character = Character.query.filter_by(id=characterID).first()
    if not sender_character:
        app.logger.error("MESSAGE- sender character not found")
        return jsonify({'message': 'Sender character not found'}), 404
    
    # app.logger.debug("MESSAGE- sender_character: %s", sender_character.to_dict())
    

    sender_user = User.query.filter_by(id=sender).first()
    app.logger.debug("MESSAGE- sender_user: %s", sender_user.username)


    # Update the messageObj with character names before emitting
    recipient_character_names = [character.character_name for character in recipient_characters]
    messageObj['recipient_character_names'] = recipient_character_names
    messageObj['sender_character_name'] = sender_character.character_name
    messageObj['sender_avatar'] = sender_character.get_avatar_props()
    messageObj['recipient_avatars'] = [
        serialize_message_participant(character)
        for character in recipient_characters
    ]
    messageObj['self_avatar'] = sender_character.get_avatar_props()

    if messageObj['type'] == 'item_transfer':
        handle_item_transfer(messageObj, recipient_character, sender_character)

    elif messageObj['type'] == 'spell_transfer':
        handle_spell_transfer(messageObj, recipient_character, sender_character)

    else:
        recipient_ids = [character.user.id for character in recipient_characters]
        recipient_ids_str = [str(id) for id in recipient_ids]

        group_id = "-".join(sorted([str(sender)] + recipient_ids_str, key=int))

        new_message = Message(
            sender_id=sender,
            campaign_id=campaignID,
            recipient_ids=",".join(recipient_ids_str),
            message_type=messageObj['type'],
            message_text=messageObj['text'],
            group_id=group_id,
            item_id=messageObj['item']['id'] if messageObj['item'] else None,  # Store item_id
        )
        db.session.add(new_message)
        db.session.commit()

        recipient_user_ids = [character.userID for character in recipient_characters]

        for recipient_user_id in recipient_user_ids:
            socketio.emit('message', messageObj, to=f"user:{recipient_user_id}")

        socketio.emit('message', messageObj, to=f"user:{sender}")

def handle_item_transfer(messageObj, recipient_character, sender_character):
    app.logger.debug("MESSAGE- ITEM TRANSFER- messageObj: %s", messageObj)
    campaignID = messageObj['campaignID']

    app.logger.debug("MESSAGE- ITEM TRANSFER- recipient_character: %s", recipient_character.character_name)
    recipient_user = User.query.filter_by(id=recipient_character.userID).first()
    app.logger.debug("MESSAGE- ITEM TRANSFER- recipient_user: %s", recipient_user.username)

    app.logger.debug("MESSAGE- ITEM TRANSFER- sender_character: %s", sender_character.character_name)
    sender_user = User.query.filter_by(id=sender_character.userID).first()
    app.logger.debug("MESSAGE- ITEM TRANSFER- sender_user: %s", sender_user.username)
    
    item = messageObj['item']
    quantity = item['quantity']

    # Update recipient's inventory here
    if recipient_user is None:
        return jsonify({'message': 'User not found'}), 404

    db_item = Item.query.filter_by(id=item['id']).first()
    app.logger.debug("ITEM TRANSFER- Item located in database: %s", db_item.to_dict())
    
    if db_item is None:
        return jsonify({'message': 'Item not found'}), 404
    
    # Update recipient's inventory
    recipient_inventory_item = InventoryItem.query.filter_by(characterID=recipient_character.id, itemID=db_item.id).first()
    app.logger.debug("ITEM TRANSFER- recipient_inventory_item: %s", recipient_inventory_item)
    
    if recipient_inventory_item:
        app.logger.debug("ITEM TRANSFER- old quantity: %s", recipient_inventory_item.quantity)
        recipient_inventory_item.quantity += int(quantity)
        app.logger.debug("ITEM TRANSFER- new quantity: %s", recipient_inventory_item.quantity)
    else: 
        new_inventory_item = InventoryItem(characterID=recipient_character.id, itemID=db_item.id, name=db_item.name, quantity=int(quantity), item=db_item)
        db.session.add(new_inventory_item)
        app.logger.debug("new_inventory_item: %s", new_inventory_item.to_dict())
    
    db.session.commit()

    # Emit an inventory_update event to the recipient
    emit('inventory_update', {'character_name': recipient_character.character_name, 'item': item}, to=recipient_user.sid)

    # Send a message to the recipient that they got a new item
    reception_message = {
        'type': 'text_message',
        'text': f'{sender_character.character_name} gave you {quantity} {db_item.name}',
        'sender': 'System',
        'recipient_character_names': [recipient_character.character_name],
        'recipients': [recipient_user.id],
    }
    emit('message', reception_message, to=recipient_user.sid)

    # Update sender's inventory only if the sender is not a DM
    if sender_character.character_name != 'DM' and sender_character.character_name != 'Admin':
        sender_inventory_item = InventoryItem.query.filter_by(characterID=sender_character.id, itemID=db_item.id).first()
        if sender_inventory_item and sender_inventory_item.quantity > int(quantity):
            sender_inventory_item.quantity -= int(quantity)
        elif sender_inventory_item.quantity == int(quantity):
            db.session.delete(sender_inventory_item)
        else:
            return jsonify({'message': 'Not enough quantity in inventory'}), 400

        db.session.commit()

        # Emit an inventory_update event to the sender
        emit('inventory_update', {'character_name': sender_character.character_name, 'item': item}, to=sender_user.sid)

        # Notify the DMs and owners, by getting their user IDs from the campaign
        campaign = Campaign.query.filter_by(id=campaignID).first()
        
        if campaign:
            dm_id = campaign.dm_id
            owner_id = campaign.owner_id
        
            # Get the DM and owner users
            dm_user = User.query.filter_by(id=dm_id).first()
            owner_user = User.query.filter_by(id=owner_id).first()
        
            # If any DM or owner users are found, send them a message
            if dm_user or owner_user:
                notification_message = {
                    'type': 'text_message',
                    'text': f"{sender_character.character_name} gave {recipient_character.character_name} {quantity} {db_item.name}",
                    'sender': 'System',
                    'recipients': []
                }
        
                if dm_user:
                    notification_message['recipients'].append(dm_user.id)
                if owner_user and owner_user.id != dm_user.id:
                    notification_message['recipients'].append(owner_user.id)
        
                emit('message', notification_message)

    else:
        app.logger.info("MESSAGE- ITEM TRANSFER- Sender is DM or Admin")

    # Send a confirmation message to the sender.
    confirmation_message = {
        'type': 'text_message',
        'text': f"You gave {recipient_character.character_name} {quantity} {db_item.name}",
        'sender': 'System',
        'recipient_character_names': [sender_character.character_name],
        'recipients': [sender_user.id],
    }
    emit('message', confirmation_message, to=sender_user.sid)

    # Save the transaction message to the database
    new_reception_message = Message(
        sender_id=sender_user.id,
        campaign_id=campaignID,
        recipient_ids=str(recipient_user.id),
        message_type='item_transfer',
        message_text=f'{quantity} {db_item.name}',
        group_id=f"0-{sender_user.id}-{recipient_user.id}",
        item_id=None
    )
    db.session.add(new_reception_message)
    db.session.commit()

def handle_spell_transfer(messageObj, recipient_users, sender):
    # Assuming recipient_users contains only one recipient for a spell_transfer
    recipient = recipient_users[0]
    recipient_user = User.query.filter_by(username=recipient['username']).first()
    sender_user = User.query.filter_by(id=sender.userID).first()
    spell = messageObj['spell']

    # Update recipient's spellbook
    recipient_spellbook_item = Spellbook.query.filter_by(userID=recipient['id'], spell_id=spell['id']).first()

    if not recipient_spellbook_item:
        new_spellbook_item = Spellbook(userID=recipient['id'], spell_id=spell['id'], quantity=1)
        db.session.add(new_spellbook_item)
    else:
        # Assuming that spell details like name, etc. are not modified during transfer
        pass

    db.session.commit()

    # Emit a spellbook_update event to the recipient
    emit('spellbook_update', {'character_name': recipient['character_name'], 'spell': spell}, to=recipient_user.sid)

    # Notify the recipient about the new spell
    reception_message = {
        'type': 'text_message',
        'text': f'Now you the know spell {spell["name"]}',
        'sender': 'System',
        'recipients': [f"{recipient['character_name']}"],
    }
    emit('message', reception_message, to=recipient_user.sid)

    # Send a confirmation message to the sender.
    confirmation_message = {
        'type': 'text_message',
        'text': f"{recipient['character_name']} knows the spell {spell['name']}",
        'sender': 'System',
        'recipients': [f'{sender.character_name}'],
    }
    emit('message', confirmation_message, to=sender_user.sid)


## Initiative Tracking
def initiative_campaign_room():
    """Return the campaign room for the authenticated socket connection."""
    campaign_id = request.args.get('campaignID')
    return f"campaign:{campaign_id}" if campaign_id else None


@socketio.on('Roll for initiative!')
@socket_db_session
def roll_initiative():
    room = initiative_campaign_room()
    emit('Roll for initiative!', to=room) if room else emit('Roll for initiative!')

@socketio.on('initiative roll')
@socket_db_session
def handle_initiative_roll(data):
    if not isinstance(data, dict) or not data.get('characterName'):
        return
    room = initiative_campaign_room()
    emit('initiative roll', data, to=room) if room else emit('initiative roll', data)

@socketio.on('update turn')
@socket_db_session
def handle_update_turn(data):
    # The data object might include information like:
    # {
    #     'current': 'Current Character Name',
    #     'next': 'Next Character Name'
    # }

    room = initiative_campaign_room()
    emit('turn update', data, to=room) if room else emit('turn update', data)

@socketio.on('combatants')
@socket_db_session
def handle_combatants(data):
    room = initiative_campaign_room()
    emit('combatants', data, to=room) if room else emit('combatants', data)

@socketio.on('end of combat')
@socket_db_session
def end_combat():
    room = initiative_campaign_room()
    emit('end of combat', to=room) if room else emit('end of combat')


@socketio.on('heartbeat')
@socket_db_session
def handle_heartbeat():
    username = request.args.get('username')
    with active_connections_lock:
        if username in active_connections:
            app.logger.info(f"Heartbeat received from: {username}")

@socketio.on('user_disconnected')
@socket_db_session
def handle_user_disconnected(data):
    campaign_id = data.get('campaign_id')
    user_id = data.get('user_id')

    app.logger.info(f"User {user_id} is disconnecting from campaign {campaign_id}")
    # Update the list of active users
    user = User.query.filter_by(id=user_id).first()
    if user:
        user.is_online = False
        user.sid = None
        db.session.commit()
        # Remove the mapping thread-safely
        with active_connections_lock:
            sid = active_connections.pop(user.username, None)  # Remove the mapping
        emit_active_users(campaign_id, to_sid=False)

@socketio.on('disconnect')
@socket_db_session
def handle_disconnect():
    """event listener when client disconnects to the server"""
    app.logger.debug("DISCONNECT- request.sid: %s", request.sid)
    safe_args = request.args.to_dict()
    if safe_args.get('token'):
        safe_args['token'] = '[redacted]'
    app.logger.debug("DISCONNECT- request.args: %s", safe_args)

    user = User.query.filter_by(sid=request.sid).first()
    if user:
        app.logger.info("DISCONNECT- %s is logging off!", user.username)

        with active_connections_lock:
            if user.username in active_connections:
                del active_connections[user.username]
                app.logger.info(f"Active connections: {active_connections}")
        user.is_online = False
        db.session.commit()

        campaign_id = request.args.get('campaignID')  # Retrieve the campaignID from the request arguments

        if campaign_id != 'null':
            emit_active_users(campaign_id, to_sid=False)
            emit("disconnect",f"user {user.username} disconnected", room='/')
            app.logger.info("DISCONNECT- %s disconnected", user.username)


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001)
