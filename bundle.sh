#!/bin/bash
set -uo pipefail

# Script to bundle a campaign's tagged NPCs, settlements, and custom items into a
# redistributable module, saved locally so it can be installed on other servers.
#
# --campaignName selects which campaign's data to search. --moduleName is both the
# `source` value to look for (rows whose `source` column equals --moduleName are
# considered part of the module) and the name given to the resulting package, so
# re-running the same --moduleName against a campaign refreshes that module's bundle.
#
# Usage: ./bundle.sh --campaignName <campaign_name> --moduleName <module_name> [--hostname <hostname>] [--outputDir <dir>]

# Default hostname
DEFAULT_HOSTNAME="raspberrypii.local"
# Matches the Flask DATABASE_URL: postgresql://admin:admin@localhost:5432/db
DB_USER="admin"
DB_PASSWORD="admin"
DB_NAME="db"
DB_HOST="localhost"
DB_PORT="5432"

# Function to display usage with available campaigns and modules
show_usage() {
    echo "Usage: $0 --campaignName <campaign_name> --moduleName <module_name> [--hostname <hostname>] [--outputDir <dir>]"
    echo ""
    echo "Finds NPCs, settlements, custom items, loot boxes, calendar events, and wiki"
    echo "pages inside --campaignName whose 'source' column equals --moduleName, and"
    echo "saves them locally as a redistributable module bundle named --moduleName."
    echo "Tag the rows you want to ship with that source value before bundling."
    echo ""
    echo "Available hostnames:"
    echo "  raspberrypi.local (production)"
    echo "  raspberrypii.local (development)"
    echo ""
    echo "For tab completion support, run: source ~/bash_completion.d/bundle_completion.sh"
}

# Function to test connection to hostname
check_connection() {
    local host=$1
    echo "Checking connection to $host..."
    if ! ping -c 1 -W 5 "$host" &>/dev/null; then
        echo "Error: Cannot connect to $host"
        exit 1
    fi
    echo "Connection to $host successful"
}

# Escape single quotes so values can be safely interpolated into SQL string literals.
sql_escape() {
    printf '%s' "$1" | sed "s/'/''/g"
}

# Run a single SQL statement over ssh+psql and print its raw (tuples-only, unaligned) output.
run_sql() {
    local hostname=$1
    local sql=$2
    # -h forces a TCP connection (password auth) instead of the peer-auth unix socket.
    ssh "$hostname" "PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -t -A -c \"$sql\""
}

# Look up a campaign's id by name; prints nothing if not found.
resolve_campaign_id() {
    local hostname=$1
    local campaign_name=$2
    local escaped
    escaped=$(sql_escape "$campaign_name")
    run_sql "$hostname" "SELECT id FROM campaign WHERE name = '$escaped' LIMIT 1;"
}

# Run a SELECT over ssh+psql and save its rows as a JSON array file.
export_table_json() {
    local hostname=$1
    local select_sql=$2
    local out_file=$3
    local label=$4

    echo "Extracting $label..."
    local json
    json=$(run_sql "$hostname" "SELECT COALESCE(json_agg(row_to_json(t)), '[]') FROM ($select_sql) t;")
    if [ -z "$json" ]; then
        json="[]"
    fi
    printf '%s\n' "$json" > "$out_file"

    if command -v jq >/dev/null 2>&1 && jq empty "$out_file" >/dev/null 2>&1; then
        local count
        count=$(jq 'length' "$out_file")
        echo "  -> $count row(s) saved to $out_file"
    else
        echo "  -> saved to $out_file"
    fi
}

# Function to extract module data (NPCs, settlements, items, loot boxes, calendar
# events, wiki pages) from the remote database into the local bundle directory.
extract_module_data() {
    local hostname=$1
    local campaign_id=$2
    local module_name=$3
    local module_escaped
    module_escaped=$(sql_escape "$module_name")

    # URL encode spaces to %20 to prevent curl API parsing errors
    local module_encoded
    module_encoded=$(printf '%s' "$module_name" | sed 's/ /%20/g')

    echo "Extracting module data from $hostname for campaign id $campaign_id and module '$module_name'"

    # Exact column mappings from your Flask NPC model definition
    export_table_json "$hostname" \
        "SELECT source, name, size, creature_type, creature_subtype, alignment, ac, hp, speed, strength, dexterity, constitution, intelligence, wisdom, charisma, saving_throws, skills, immunities, resistance, senses, languages, challenge, traits, actions, description FROM npc WHERE campaign_id = $campaign_id AND source = '$module_escaped'" \
        "$OUTPUT_DIR/npcs.json" "NPCs"

    # WorldAtlasLocation - Portable Babylon.js map structure
    export_table_json "$hostname" \
        "SELECT name, map_key, settlement_type, notes, atlas_x, atlas_y, is_primary, terrain_strokes, roads, water_bodies, buildings, reference_layers, environment, source FROM world_atlas_location WHERE campaign_id = $campaign_id AND source = '$module_escaped'" \
        "$OUTPUT_DIR/settlements.json" "Settlements"

    # Atlas extraction
    echo "Extracting Overworld Atlas configurations..."
    export_table_json "$hostname" \
        "SELECT atlas_image_url, atlas_tile_url_template, atlas_tile_zoom, atlas_environment FROM campaign WHERE id = $campaign_id" \
        "$OUTPUT_DIR/atlas_config.json" "Atlas Layout Canvas"


    # Custom Items extraction query
    export_table_json "$hostname" \
        "SELECT source, name, type, cost, currency, weight, description FROM item WHERE source = '$module_escaped'" \
        "$OUTPUT_DIR/items.json" "Custom Items"

    # Exact structural metadata properties from your Flask LootBox model definition
    export_table_json "$hostname" \
        "SELECT source, name, system, module_key, is_preset FROM loot_box WHERE campaign_id = $campaign_id AND source = '$module_escaped'" \
        "$OUTPUT_DIR/loot_boxes.json" "Loot Boxes"

    # Wildcard fallback selection to dynamically extract the full structure of calendar events safely
    export_table_json "$hostname" \
        "SELECT ce.* FROM calendar_event ce JOIN calendar c ON c.id = ce.calendar_id WHERE c.campaign_id = $campaign_id AND ce.source = '$module_escaped'" \
        "$OUTPUT_DIR/calendar_events.json" "Calendar Events"

    # Extract base wiki pages from API with %20 encoded formatting
    extract_base_module_wiki_pages "$hostname" "$module_encoded" "$OUTPUT_DIR/wiki_pages"

    echo "Data extraction complete for module '$module_name'"
}


# Function to extract base wiki pages from API endpoint
extract_base_module_wiki_pages() {
    local hostname=$1
    local module_name=$2
    local out_dir=$3

    echo "Extracting base wiki pages for module '$module_name' from $hostname"
    mkdir -p "$out_dir"

    if ! command -v jq >/dev/null 2>&1; then
        echo "jq not available; skipping wiki page export"
        return 0
    fi

    local api_url="http://$hostname/api/modules/$module_name/wiki/base-pages"
    echo "Fetching from API: $api_url"

    local tmp_json
    tmp_json=$(mktemp)
    if ! curl -sf "$api_url" > "$tmp_json"; then
        echo "Failed to fetch base pages from API"
        rm -f "$tmp_json"
        return 1
    fi

    local page_count
    page_count=$(jq -r '.pages | length' "$tmp_json" 2>/dev/null || echo 0)
    if [ "$page_count" -gt 0 ] 2>/dev/null; then
        for i in $(seq 0 $((page_count - 1))); do
            local title content filename
            title=$(jq -r ".pages[$i].title" "$tmp_json" | sed 's/[[:space:]]*$//')
            content=$(jq -r ".pages[$i].content" "$tmp_json")

            if [ -n "$title" ] && [ "$title" != "null" ]; then
                filename=$(echo "$title" | sed 's/[^a-zA-Z0-9._-]/_/g' | cut -c1-100).md
                {
                    echo "# $title"
                    echo ""
                    echo "$content"
                } > "$out_dir/$filename"
            fi
        done
        echo "  -> $page_count wiki page(s) saved to $out_dir"
    else
        echo "No base wiki pages found for module '$module_name'"
    fi
    rm -f "$tmp_json"
}

# Parse command line arguments
HOSTNAME="$DEFAULT_HOSTNAME"
OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --campaignName)
            CAMPAIGN_NAME="$2"
            shift 2
            ;;
        --moduleName)
            MODULE_NAME="$2"
            shift 2
            ;;
        --hostname)
            HOSTNAME="$2"
            shift 2
            ;;
        --outputDir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate arguments
if [ -z "${CAMPAIGN_NAME:-}" ] || [ -z "${MODULE_NAME:-}" ]; then
    echo "Error: Both --campaignName and --moduleName must be provided"
    show_usage
    exit 1
fi

echo "Bundling changes for campaign '$CAMPAIGN_NAME' into module '$MODULE_NAME'"
echo "Using hostname: $HOSTNAME"

# Check connection to hostname
check_connection "$HOSTNAME"

# Resolve the campaign to a database id so npc/settlement/loot box/calendar exports
# can be scoped to it (item exports are global, matched by source alone).
CAMPAIGN_ID=$(resolve_campaign_id "$HOSTNAME" "$CAMPAIGN_NAME" | tr -d '[:space:]')
if [ -z "$CAMPAIGN_ID" ]; then
    echo "Error: No campaign named '$CAMPAIGN_NAME' was found on $HOSTNAME"
    exit 1
fi
echo "Resolved campaign '$CAMPAIGN_NAME' to id $CAMPAIGN_ID"

# Create output directory structure (local machine, so it can be redistributed from here)
if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="./Flask/modules/${MODULE_NAME}"
fi
mkdir -p "$OUTPUT_DIR"

echo "Bundle directory created: $OUTPUT_DIR"

# Extract module data from the remote database
extract_module_data "$HOSTNAME" "$CAMPAIGN_ID" "$MODULE_NAME"

# Manifest describing where this bundle came from, so it can be traced back later.
cat > "$OUTPUT_DIR/manifest.json" <<EOF
{
  "module_name": "$MODULE_NAME",
  "source_campaign": "$CAMPAIGN_NAME",
  "exported_from_host": "$HOSTNAME",
  "exported_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo ""
echo "Structure created successfully in: $(cd "$OUTPUT_DIR" && pwd)"
echo "Copy that directory to another server to redistribute this module."
