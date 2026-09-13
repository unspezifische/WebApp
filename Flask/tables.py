from datetime import datetime, timedelta, timezone

## For database stuff
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select, Numeric, text, func, UniqueConstraint
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, TSVECTOR

import json ## For sending JSON data

db = SQLAlchemy()

DND_RULESET_SYSTEMS = {
    '3.5e': 'D&D 3.5e',
    '4e': 'D&D 4e',
    '5e': 'D&D 5e',
    '5e (2024)': 'D&D 5e (2024)',
}

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

def character_avatar_preset(key):
    return next((preset for preset in CHARACTER_AVATAR_PRESETS if preset['key'] == key), None)


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
    system = db.Column(db.String(50), nullable=False)    
    ruleset = db.Column(db.String(30))                   
    icon = db.Column(db.String(120))  
    description = db.Column(db.Text)
    module = db.Column(db.String(160))
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    dm_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scribes = db.Column(ARRAY(db.Integer), default=[])  
    
    # Overworld Atlas Config Columns
    atlas_image_url = db.Column(db.String(255), nullable=True)
    atlas_tile_url_template = db.Column(db.String(255), nullable=True)
    atlas_tile_zoom = db.Column(db.Integer, nullable=False, default=2, server_default='2')
    
    # Future-proof block for non-static environmental data matrices
    atlas_environment = db.Column(JSONB, nullable=False, default=dict, server_default='{}')

    calendars = db.relationship('Calendar', backref='campaign', lazy=True)
    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_campaigns')
    dm = db.relationship('User', foreign_keys=[dm_id], backref='dm_campaigns')

    @property
    def rules_system(self):
        if self.system == 'D&D 5e':  
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
            # 🚀 NEW: Expose to the React frontend AtlasViewport container
            'atlas': {
                'image_url': self.atlas_image_url,
                'tile_url_template': self.atlas_tile_url_template,
                'tile_zoom': self.atlas_tile_zoom,
                'environment': self.atlas_environment
            }
        }

class Page(db.Model):
    __table_args__ = (
        UniqueConstraint('wiki_id', 'title', name='uq_page_wiki_id_title'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source = db.Column(db.String(80), nullable=False, default='Homebrew')  # Denotes the source of the page, e.g., a module or homebrew
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
    source = db.Column(db.String(80), nullable=False, default='Homebrew')  # Denotes the source of the item, e.g., a module or homebrew

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
            'itemID': self.itemID,
            'charges': self.charges,
            'spell_id': self.spell_id,
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
    source = db.Column(db.String(80), nullable=False, default='Homebrew')  # Denotes the source of the NPC, e.g., a module or homebrew

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


class LootBox(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(80), nullable=False, default='Homebrew')  # Denotes the source of the loot box, e.g., a module or homebrew

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
    source = db.Column(db.String(80), nullable=False, default='System')  # Denotes the source of the calendar, e.g., a module or homebrew
    
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
    source = db.Column(db.String(80), nullable=False, default='System')  # Denotes the source of the event, e.g., a module or homebrew

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
        return {
            'campaign_id': self.campaign_id,
            'map_key': self.map_key,
            'x': self.x,
            'y': self.y,
            'elevation': self.elevation,
            'water_access': self.water_access,
            'road_access': self.road_access
        }


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
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'map_key': self.map_key,
            'name': self.name,
            'point_type': self.point_type,
            'x': self.x,
            'y': self.y,
            'elevation': self.elevation,
            'water_access': self.water_access,
            'road_access': self.road_access
        }


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
    source = db.Column(db.String(80), nullable=False, default='System')

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

    environment = db.Column(db.JSON, nullable=False, default=dict)
    
    # 🌧️ Add persistent weather tracking footprint
    weather = db.Column(db.JSON, nullable=False, default=lambda: {
        "activeWeather": "clear",
        "cloudCover": 0.0,
        "fogDensity": 0.005,
        "fogColor": "#a9c9dc"
    }, server_default='{"activeWeather": "clear", "cloudCover": 0.0, "fogDensity": 0.005, "fogColor": "#a9c9dc"}')

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
            **self.atlas_dict(), 
            'settlement_id': self.id, 
            'coordinate_unit': 'feet',
            'terrain_strokes': self.terrain_strokes or [], 
            'roads': self.roads or [],
            'water_bodies': self.water_bodies or [], 
            'buildings': self.buildings or [],
            'reference_layers': self.reference_layers or [],
            'weather': self.weather # Expose to frontend
        }



class MapMediaAsset(db.Model):
    """Opaque, database-backed raster used by settlement maps and world atlases."""
    __tablename__ = 'map_media_asset'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, unique=True, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id', ondelete='CASCADE'), nullable=True, index=True)
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
        return {
            'id':self.id,
            'commodity_key':self.commodity_key,
            'name':self.name,
            'base_price_cp':self.base_price_cp,
            'current_price_cp':self.current_price_cp,
            'stock':round(self.stock,2),
            'target_stock':self.target_stock,
            'price_index':round(self.current_price_cp / self.base_price_cp, 2),
            'last_imported':self.last_imported
        }


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
        return {
            column:getattr(self,column) for column in ('id','x','y','foot_traffic','quality','accessibility','cash_reserves_cp',
                'daily_capacity','average_sale_cp','cost_of_goods_rate','daily_overhead_cp','closure_grace_days','slump_days','closed')}

    def to_dict(self):
        return {
            'id':self.id,
            'name':self.name,
            'business_type':self.business_type,
            'x':self.x,
            'y':self.y,
            'foot_traffic':self.foot_traffic,
            'quality':self.quality,
            'accessibility':self.accessibility,
            'cash_reserves_cp':self.cash_reserves_cp,
            'player_owned':self.player_owned,
            'closed':self.closed,
            'slump_days':self.slump_days
        }


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
        return {
            'day_index':self.day_index,
            'customers':self.customers,
            'revenue_cp':self.revenue_cp,
            'costs_cp':self.costs_cp,
            'profit_cp':self.profit_cp,
            'cash_reserves_cp':self.cash_reserves_cp,
            'market_share':self.market_share
        }


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
    def simulation_dict(self):
        return {
            'key':self.occupation_key,
            'ability_weights':self.ability_weights,
            'target_workers':self.target_workers,
            'minimum_suitability':self.minimum_suitability
        }
    
    def to_dict(self):
        return {
            'id':self.id,
            'key':self.occupation_key,
            'name':self.name,
            'ability_weights':self.ability_weights,
            'target_workers':self.target_workers,
            'base_wage_cp':self.base_wage_cp,
            'produces_commodity_key':self.produces_commodity_key
        }


class NobleFamily(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    campaign_id=db.Column(db.Integer,db.ForeignKey('campaign.id'),nullable=False,index=True)
    name=db.Column(db.String(120),nullable=False)
    wealth_cp=db.Column(db.Integer,nullable=False,default=0)
    investment_risk=db.Column(db.Float,nullable=False,default=.5)
    active=db.Column(db.Boolean,nullable=False,default=True)
    def to_dict(self):
        return {
            'id':self.id,
            'name':self.name,
            'wealth_cp':self.wealth_cp,
            'investment_risk':self.investment_risk,
            'active':self.active
        }


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
    def to_dict(self): return {
        'id':self.id,
        'npc_id':self.npc_id,
        'name':self.name,
        'abilities':{
            key:getattr(self,key) for key in ('strength','dexterity','constitution','intelligence','wisdom','charisma')},
            'economic_autonomy':self.economic_autonomy,
            'story_locked':self.story_locked,
            'simulation_generated':self.simulation_generated,
            'social_class':self.social_class,
            'occupation_key':self.occupation_key,
            'employer_business_id':self.employer_business_id,
            'noble_family_id':self.noble_family_id,
            'wealth_cp':self.wealth_cp,
            'career_cooldown_until_day':self.career_cooldown_until_day
        }


class EmploymentHistory(db.Model):
    id=db.Column(db.Integer,primary_key=True);agent_id=db.Column(db.Integer,db.ForeignKey('settlement_economic_agent.id',ondelete='CASCADE'),nullable=False,index=True)
    day_index=db.Column(db.Integer,nullable=False);from_occupation=db.Column(db.String(80));to_occupation=db.Column(db.String(80));reason=db.Column(db.String(120),nullable=False)


class NobleInvestment(db.Model):
    id=db.Column(db.Integer,primary_key=True);family_id=db.Column(db.Integer,db.ForeignKey('noble_family.id',ondelete='CASCADE'),nullable=False,index=True)
    business_id=db.Column(db.Integer,db.ForeignKey('settlement_business.id',ondelete='CASCADE'),nullable=False,index=True)
    principal_cp=db.Column(db.Integer,nullable=False,default=0);total_dividends_cp=db.Column(db.Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint('family_id','business_id',name='uq_noble_family_business_investment'),)
    def to_dict(self): return {
        'id':self.id,
        'family_id':self.family_id,
        'business_id':self.business_id,
        'principal_cp':self.principal_cp,
        'total_dividends_cp':self.total_dividends_cp
    }


class NobleDecisionLedger(db.Model):
    id=db.Column(db.Integer,primary_key=True); family_id=db.Column(db.Integer,db.ForeignKey('noble_family.id',ondelete='CASCADE'),nullable=False,index=True)
    day_index=db.Column(db.Integer,nullable=False); decision_type=db.Column(db.String(50),nullable=False);business_id=db.Column(db.Integer,db.ForeignKey('settlement_business.id'),nullable=True)
    amount_cp=db.Column(db.Integer,nullable=False,default=0); summary=db.Column(db.Text,nullable=False)
  

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
        return {
            'slot': self.slot,
            'sound': self.sound_asset.to_dict() if self.sound_asset else None
        }

class SoundTranscodeError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code