# KACHHAPA- The World Turtle
I would highly recommend using [Docker Desktop](https://www.docker.com/products/docker-desktop/) for this project. It will make accessing the terminal window for each container much easier.

## A Quick Note First
Clone the repo, then run this command in the parent direcvtory: `docker-compose up --build -d`. It will take awhile the first time because Docker will have to download several images and then build the web app. Once the build is successful and all the containers are running, you'll be able to access the web app at `localhost` in your web browser. Sometimes, when building the Docker containers for the first time, the Flask container will fail to start. Here is where having Docker Desktop installed makes things easier because it is very straight forward to check the status of the container and to restart it if necessary. It's usually some "Table already exists error". Doesn't matter. Just restart the container and everything will be fine. I'll fix this problem if I feel the need to track down the cause. Presumably it's an issue with the Docker configuration or setup.

## Getting Started
The first thing you should do is register for an account. After you do that, you'll need to select the "Create A New Campaign" option from the Account Profile page. Once those two steps are complete, you can begin to explore the various capabilities of web app. A good first step would be to click the "Add Items" button on the Inventory page and upload the included CSV called "Items" which will provide a variety of starter items to work with. You'll need to have other users registered to join your campaign in order to issue items to them. If you need to have separate tabs open for the DM and the Player users, use a priavte session or Incognito Mode so the tokens don't clash.

## Alternatively
A script has been provided which creates a `user` and an `admin` account. The password for `user` is just `password` and the login for `admin` is just `admin`. The script also creates a campaign with `admin` as the DM and creates a character for `user`, then adds it to the campaign. This works for nicely for testing purposes, if you've got a fresh database with nothing in it. Once the `docker-compose` command has finished running, you can use `docker exec webapp-flask-1 python populate_users.py` or `docker exec kachhapa--the-world-turtle-flask-1 python populate_users.py` to execute the Python script within the Docker container for the Flask app, which will create the aforementioned user accounts, campaign, and character.

## Going Forward
Whether you choose to create your own account and campaign or use the script-provided ones, the next step should probably be to populate the database with items which can then be issued to players in a campaign. To make this faster, two CSV files have been included in the GameElements directory. One of the files contains an extensive list of armor, basic weapon options, and some options for mounts or vehicles. The second file, called `Items- full.csv` contains the same items, plus an extensive list of adventuring gear as well which might be useful.

## Current Features
Here is a list of the currently implmented features in Kachhapa. The code to provide these features has been written, but there is no guarentees at the moment that they'll work without error. Some effort has been made to provide better feedback to the end user in the event of errors, but checking the console of the Flask container (very easy to do if using Docker Desktop, or in a terminal using the `docker logs -f webapp-flask-1` to watch in real-time) or in the web console (accessed via the Developer Tool options of most web browsers) is often the best place to identify where problems may be occuring. There is still a lot of debugging statements left in for this purpose.

Features:
- User Profile Page
    - Shows each user a list of the campaigns they are in, characters they've created, and provides quick access to campaign wikis
- Campaign Creation
    - Choose a name and provide a brief description of the campaign. TODO: incorporate pre-packaged "module" content.
- Character Creation (WiP)
    - Walks the user through creating their character, providing options for race, class, et ceterea to choose from.
- Inventory Management
    - Players can manage their characters’ inventory.
    - Items can be added via CSV upload or manually through the interface.
    - Players can mark items as “equipped” or “attuned,” which keeps them at the top of their inventory list.
    - Inventory updates in real-time using WebSockets, and players can trade or give items to each other.
- Journal
    - Players have access to a journal where they can log important information about their campaign or character.
    - Journal entries persist across refreshes and can be saved, edited, or deleted.
- DM Tools
    - Initiative Tracker: Allows the DM to roll initiative for players and NPCs and manage combat order. (WiP)
    - NPC Generator: Automatically generates NPC names, stats, and backgrounds based on predefined rules. (WiP)
    - Loot Management: DMs can create and manage loot crates for players, which include random items that players can receive. (The "random" part is WiP)
    - DM can track and update players’ inventories in real-time.
- Character Sheet
    - Dynamic tiles for displaying and editing character stats, inventory, and other character features.
    - Ability to rearrange tiles ~~and save custom layouts~~.
    - Support for tracking XP, wealth, proficiencies, spells, and class features.
    - Support for different character systems, such as D&D 5e, with fields for ability scores, race, and class. (In theory.)
- Chat Widget
	- Real-time messaging for players and DMs, with the ability to group messages by recipient or group.
	- Chat messages persist in the database and can be retrieved on reconnect.
	- Integration with inventory updates (e.g., notifying DMs of item trades).
- Campaign Wiki:
    - Each campaign has a wiki where (approved) users can create and edit pages.
    - A lightweight, user-friendly wiki editor is provided, with Markdown support.
    - Wiki access can be restricted based on user roles (DM, players, etc.). (Not yet tested)
    - Version control for wiki pages is in progress. (WiP- the page to view past versions of a page doesn't exist yet, but the database does track the information)
- WebSocket Support
    - Real-time updates for combat, chat, and inventory management are supported via WebSockets, ensuring changes made by one player are reflected across the session instantly. (WebSockets haven't been tested in the Docker environment yet)

## Upcoming Features
- Admin Console & Dashboard for Monitoring the Flask Server
    - Flask-Admin console and FlaskMonitoringDashboard integration is in progress, allowing you to monitor API calls, view errors, and oversee system performance. The libraries are implemented, but some work needs to be done on making the pages these tools provide actually accessible in the web browser.
- Map Generation
    - A tool for generating procedural maps for towns, villages, and continents.
    - Users can zoom in and out of settlements, view buildings, and interact with points of interest (POIs).
    - A travel system is being developed to calculate time and distance between points, including options for walking, riding, or flying. In-world Time of Day will adjust accordingly.
    - Integration with OpenLayers and GeoJSON for handling map layers and data.

## TODOs
- switch to a system-agnostic way of storing character (both player and non-player) attributes.
- Move "Atmospheric Settings" to the Atlas-level, rather than individual settlements.
- Implement "Add buidling" workflow:
    - [Developing Build a House from Plans](https://doc.babylonjs.com/guidedLearning/workshop/House/)
    - [Using Build a House from Plans](https://doc.babylonjs.com/guidedLearning/workshop/House_Use/)
    - [Adding a Roof to a House Built from Plans](https://doc.babylonjs.com/guidedLearning/workshop/roof/)

- Need an Asset Importer for importing character models
    - Imported models can be selected from a library panel
- Animation library
    - Walking
    - Running
    - sitting
    - eating (raising utensil from table to mouth)
    - drinking (raising cup/mug/tankard to mouth)
    - Ready to Fight stance
    - Falling down
    - Casting magic
    - Riding a wagon
    - mounting/dismounting wagon
    - Riding a horse
    - mounting/dismounting horse
    - swimming animation (underwater and surface swimming. slow & fast?)

## Database Updates
If, in the course of development, the tables change in Flask, it will be necessary to upgrade the database to match the new Flask configuration. To do this, navigate either to the Docker container running Flask or the command line, and type `flask db migrate -m "explain what changed"`, then `flask db upgrade` to commit those changes.