import os
import json
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from app import app, db, User, Character, Campaign, campaign_members

# Push the application context
app.app_context().push()

# Define the user data
users = [
    {"username": "user", "password": "password"},
    {"username": "admin", "password": "admin"}
]

# Register each user and store the admin user
admin_user = None
user_user = None
for user_data in users:
    hashed_password = generate_password_hash(user_data['password'], method='sha256')
    new_user = User(username=user_data['username'], password=hashed_password)
    try:
        db.session.add(new_user)
        db.session.commit()
        print(f"Successfully registered {user_data['username']}")
        if user_data['username'] == 'admin':
            admin_user = new_user
        elif user_data['username'] == 'user':
            user_user = new_user
    except IntegrityError:
        db.session.rollback()
        print(f"User {user_data['username']} already exists")
        existing_user = User.query.filter_by(username=user_data['username']).first()
        if user_data['username'] == 'admin':
            admin_user = existing_user
        elif user_data['username'] == 'user':
            user_user = existing_user

# Register the campaign using the admin user
new_campaign = None
if admin_user:
    campaign_data = {
        "name": "Admin's Campaign",
        "system": "D&D",
        "ruleset": "5e",
        # "icon": "icon_url",
        "description": "A default campaign for testing",
        "scribes": []
    }

    new_campaign = Campaign(
        name=campaign_data['name'],
        system=campaign_data['system'],
        ruleset=campaign_data['ruleset'],
        # icon=campaign_data['icon'],
        description=campaign_data['description'],
        owner_id=admin_user.id,
        dm_id=admin_user.id,
        scribes=campaign_data['scribes']
    )

    db.session.add(new_campaign)
    db.session.commit()
    print(f"Successfully registered campaign with id {new_campaign.to_dict()}")
else:
    print("Admin user registration failed, cannot register campaign")


if admin_user and new_campaign:
    character_data = {
        # "icon": "icon_url",
        "system": "D&D 5e",
        "character_name": "Admin"
    }

    new_character = Character(
        # icon=character_data['icon'],
        system=character_data['system'],
        userID=admin_user.id,
        campaignID=new_campaign.id,
        character_name=character_data['character_name'],
    )

    db.session.add(new_character)
    db.session.commit()
    print("Successfully created character for User and registered it for the campaign:")
    print(new_character.to_dict())

    # Add the admin and character named "Admin" to the campaign_members table
    db.session.execute(
        campaign_members.insert().values(
            userID=admin_user.id,
            campaignID=new_campaign.id,
            characterID=new_character.id
        )
    )
    db.session.commit()
    print("Successfully added user and character to the campaign_members table")

else:
    print("User 'admin' or campaign creation failed, cannot create character")

# Create a character for the user user and register it for the campaign
if user_user and new_campaign:
    character_data = {
        # "icon": "icon_url",
        "system": "D&D 5e",
        "character_name": "Test Character",
        "Class": "Sorcerer",
        "Background": "Sage",
        "Race": "Tiefling",
        "Alignment": "Neutral Good",
        "ExperiencePoints": 0,
        "strength": 10,
        "dexterity": 14,
        "constitution": 12,
        "intelligence": 11,
        "wisdom": 13,
        "charisma": 18,
        "PersonalityTraits": "Curious and inquisitive",
        "Ideals": "Knowledge is power",
        "Bonds": "My mentor",
        "Flaws": "Overly curious",
        "Feats": json.dumps([]),
        "Proficiencies": json.dumps(["Arcana", "History"]),
        "CurrentHitPoints": 10,
        "cp": 0,
        "sp": 0,
        "ep": 0,
        "gp": 15,
        "pp": 0
    }

    new_character = Character(
        # icon=character_data['icon'],
        system=character_data['system'],
        userID=user_user.id,
        campaignID=new_campaign.id,
        character_name=character_data['character_name'],
        Class=character_data['Class'],
        Background=character_data['Background'],
        Race=character_data['Race'],
        Alignment=character_data['Alignment'],
        ExperiencePoints=character_data['ExperiencePoints'],
        strength=character_data['strength'],
        dexterity=character_data['dexterity'],
        constitution=character_data['constitution'],
        intelligence=character_data['intelligence'],
        wisdom=character_data['wisdom'],
        charisma=character_data['charisma'],
        PersonalityTraits=character_data['PersonalityTraits'],
        Ideals=character_data['Ideals'],
        Bonds=character_data['Bonds'],
        Flaws=character_data['Flaws'],
        Feats=character_data['Feats'],
        Proficiencies=character_data['Proficiencies'],
        CurrentHitPoints=character_data['CurrentHitPoints'],
        cp=character_data['cp'],
        sp=character_data['sp'],
        ep=character_data['ep'],
        gp=character_data['gp'],
        pp=character_data['pp']
    )

    db.session.add(new_character)
    db.session.commit()
    print("Successfully created character for User and registered it for the campaign:")
    print(new_character.to_dict())

    # Add the user and character to the campaign_members table
    db.session.execute(
        campaign_members.insert().values(
            userID=user_user.id,
            campaignID=new_campaign.id,
            characterID=new_character.id
        )
    )
    db.session.commit()
    print("Successfully added user and character to the campaign_members table")
else:
    print("User 'user' or campaign creation failed, cannot create character")
