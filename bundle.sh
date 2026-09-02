#!/bin/bash

# Script to bundle changes from a test campaign back into a shareable module
# Usage: ./bundle.sh --campaignName <campaign_name> --moduleName <module_name> [--hostname <hostname>]

# Default hostname
DEFAULT_HOSTNAME="raspberrypii.local"

# Function to display usage with available campaigns and modules
show_usage() {
    echo "Usage: $0 --campaignName <campaign_name> --moduleName <module_name> [--hostname <hostname>]"
    echo ""
    echo "Available campaigns (example):"
    echo "  Campaign1"
    echo "  Campaign2" 
    echo "  Waterdeep Campaign"
    echo "  Test Campaign"
    echo ""
    echo "Available modules (example):"
    echo "  Waterdeep Dragon Heist"
    echo "  Curse of Strahd"
    echo "  Tomb of Annihilation"
    echo "  Elemental Evil"
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

# Function to extract data from remote database
extract_module_data() {
    local hostname=$1
    local campaign_name=$2
    local module_name=$3
    
    echo "Extracting module data from $hostname for campaign '$campaign_name' and module '$module_name'"
    
    # Create temporary directory for extraction
    local temp_dir="./temp_extraction_$$"
    mkdir -p "$temp_dir"
    
    # Extract Items (assuming we have database access)
    echo "Extracting Items..."
    ssh "$hostname" "psql -U admin -d kachhapa_sandbox -c \"SELECT * FROM item WHERE source LIKE '%$module_name%';\"" > "$temp_dir/items.csv" 2>/dev/null || true
    
    # Extract NPCs
    echo "Extracting NPCs..."
    ssh "$hostname" "psql -U admin -d kachhapa_sandbox -c \"SELECT * FROM npc WHERE source LIKE '%$module_name%';\"" > "$temp_dir/npcs.csv" 2>/dev/null || true
    
    # Extract Settlements (WorldAtlasLocation)
    echo "Extracting Settlements..."
    ssh "$hostname" "psql -U admin -d kachhapa_sandbox -c \"SELECT * FROM world_atlas_location WHERE source LIKE '%$module_name%';\"" > "$temp_dir/settlements.csv" 2>/dev/null || true
    
    # Extract Calendar Events
    echo "Extracting Calendar Events..."
    ssh "$hostname" "psql -U admin -d kachhapa_sandbox -c \"SELECT * FROM calendar_event WHERE source LIKE '%$module_name%';\"" > "$temp_dir/calendar_events.csv" 2>/dev/null || true
    
    # Extract Loot Boxes
    echo "Extracting Loot Boxes..."
    ssh "$hostname" "psql -U admin -d kachhapa_sandbox -c \"SELECT * FROM loot_box WHERE source LIKE '%$module_name%';\"" > "$temp_dir/loot_boxes.csv" 2>/dev/null || true
    
    # Extract base wiki pages from API
    echo "Extracting Base Wiki Pages..."
    extract_base_module_wiki_pages "$hostname" "$module_name" "$temp_dir"
    
    # Copy extracted data to bundle output
    echo "Copying extracted data to bundle directory..."
    if [ -d "$temp_dir" ]; then
        # Move CSV files to the bundle structure
        if [ -f "$temp_dir/items.csv" ]; then
            cp "$temp_dir/items.csv" "$OUTPUT_DIR/"
        fi
        if [ -f "$temp_dir/npcs.csv" ]; then
            cp "$temp_dir/npcs.csv" "$OUTPUT_DIR/"
        fi
        if [ -f "$temp_dir/settlements.csv" ]; then
            cp "$temp_dir/settlements.csv" "$OUTPUT_DIR/"
        fi
        if [ -f "$temp_dir/calendar_events.csv" ]; then
            cp "$temp_dir/calendar_events.csv" "$OUTPUT_DIR/"
        fi
        if [ -f "$temp_dir/loot_boxes.csv" ]; then
            cp "$temp_dir/loot_boxes.csv" "$OUTPUT_DIR/"
        fi
        
        # Copy wiki pages if they exist
        if [ -d "$temp_dir/wiki_pages" ]; then
            cp -r "$temp_dir/wiki_pages"/* "$OUTPUT_DIR/wiki_pages/" 2>/dev/null || true
        fi
        
        # Clean up temporary directory
        rm -rf "$temp_dir"
    fi
    
    echo "Data extraction complete for module '$module_name'"
}

# Parse command line arguments
HOSTNAME="$DEFAULT_HOSTNAME"
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
if [ -z "$CAMPAIGN_NAME" ] || [ -z "$MODULE_NAME" ]; then
    echo "Error: Both --campaignName and --moduleName must be provided"
    show_usage
    exit 1
fi

echo "Bundling changes for campaign '$CAMPAIGN_NAME' into module '$MODULE_NAME'"
echo "Using hostname: $HOSTNAME"

# Check connection to hostname
check_connection "$HOSTNAME"

# Create output directory structure
OUTPUT_DIR="./Flask/modules/${MODULE_NAME}"
mkdir -p "$OUTPUT_DIR"

echo "Bundle directory created: $OUTPUT_DIR"

# Extract module data from the remote database
rm -f "$temp_dir/base_pages.json"

# Function to extract base wiki pages from API endpoint
extract_base_module_wiki_pages() {
    local hostname=$1
    local module_name=$2
    local temp_dir=$3
    
    echo "Extracting base wiki pages for module '$module_name' from $hostname"
    
    # Create wiki pages directory in temp folder
    mkdir -p "$temp_dir/wiki_pages"
    
    # Check if jq is available
    if command -v jq >/dev/null 2>&1; then
        # Use jq to parse JSON response
        local api_url="http://$hostname/api/modules/$module_name/wiki/base-pages"
        echo "Fetching from API: $api_url"
        
        # Fetch the JSON data and save it to a temporary file first
        curl -s "$api_url" > "$temp_dir/base_pages.json" || {
            echo "Failed to fetch base pages from API"
            return 1
        }
        
        # Extract pages using jq
        local page_count=$(jq -r '.pages | length' "$temp_dir/base_pages.json")
        if [ "$page_count" -gt 0 ]; then
            for i in $(seq 0 $((page_count-1))); do
                local title=$(jq -r ".pages[$i].title" "$temp_dir/base_pages.json" | sed 's/[[:space:]]*$//')
                local content=$(jq -r ".pages[$i].content" "$temp_dir/base_pages.json")
                
                # Skip if title is empty
                if [ -n "$title" ] && [ "$title" != "null" ]; then
                    # Sanitize filename (remove invalid characters)
                    local filename=$(echo "$title" | sed 's/[^a-zA-Z0-9._-]/_/g' | cut -c1-100).md
                    
                    # Write markdown file
                    echo "# $title" > "$temp_dir/wiki_pages/$filename"
                    echo "" >> "$temp_dir/wiki_pages/$filename"
                    echo "$content" >> "$temp_dir/wiki_pages/$filename"
                fi
            done
        else
            echo "No base wiki pages found for module '$module_name'"
        fi
    else
        # Fallback: try to use basic curl and sed/awk parsing (without jq)
        echo "jq not available, attempting fallback method..."
        local api_url="http://$hostname/api/modules/$module_name/wiki/base-pages"
        echo "Fetching from API: $api_url"
        
        # Fetch the JSON data
        curl -s "$api_url" > "$temp_dir/base_pages.json" || {
            echo "Failed to fetch base pages from API"
            return 1
        }
        
        # Simple approach using grep/sed (basic parsing)
        local content=$(grep -o '"content":"[^"]*"' "$temp_dir/base_pages.json" | sed 's/"content":"//' | sed 's/"$//')
        if [ -n "$content" ]; then
            echo "Base pages found but parsing without jq is limited. Using basic approach."
            # This is a simplified version - would need more robust handling for multiple pages
            local title="Base_Wiki_Page"
            local filename="$title.md"
            
            echo "# $title" > "$temp_dir/wiki_pages/$filename"
            echo "" >> "$temp_dir/wiki_pages/$filename"
            echo "$content" >> "$temp_dir/wiki_pages/$filename"
        else
            echo "No base wiki pages found or unable to parse with fallback method"
        fi
    fi
    
    # Clean up temporary JSON file
    rm -f "$temp_dir/base_pages.json"
}
extract_module_data "$HOSTNAME" "$CAMPAIGN_NAME" "$MODULE_NAME"

echo "Structure created successfully in: $OUTPUT_DIR"
