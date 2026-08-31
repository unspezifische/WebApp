#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="ijohnson"
TARGET_HOST_SHORT="raspberrypi"
TARGET_HOSTNAME="raspberrypi.local"
DESTINATION_OVERRIDE="${DESTINATION:-}"
HOSTNAME_EXPLICITLY_SET=false

readonly KACHHAPA_ROOT="/home/ijohnson/Kachhapa"
readonly MTG_ROOT="/home/ijohnson/MtG-webapp"
readonly KACHHAPA_SERVICE="kachhapa-backend"
readonly MTG_SERVICE="mtg-backend"

DEPLOY_KACHHAPA=false
DEPLOY_MTG=false
DEPLOY_NGINX=false
CHECK_ONLY=false
CURRENT_STEP="initialization"
RENDERED_NGINX_CONFIG=""

usage() {
  cat <<'EOF'
Usage: ./publish.sh [--hostname NAME] [--kachhapa] [--mtg] [--nginx] [--all] [--check]

With no deployment selection, all components are selected.
--check performs every local preflight/build check and never contacts the Pi.
--hostname accepts either a short hostname like raspberrypii or a fully
qualified name like raspberrypii.local or raspberrypii.lan.
Nginx is rendered for NAME plus app.NAME, tools.NAME, mtg.NAME, and maps.NAME.
Publishing is offline-safe when requirements files are unchanged. Existing
installations must run scripts/configure-publish-sudo.sh NAME once before
their first fully noninteractive publish.

Example: ./publish.sh --hostname raspberrypi.local --all
EOF
}

normalize_hostname() {
  local hostname=$1

  case "$hostname" in
    *.local)
      TARGET_HOST_SHORT="${hostname%.local}"
      TARGET_HOSTNAME="$hostname"
      ;;
    *.lan)
      TARGET_HOST_SHORT="${hostname%.lan}"
      TARGET_HOSTNAME="$hostname"
      ;;
    *)
      TARGET_HOST_SHORT="$hostname"
      TARGET_HOSTNAME="${hostname}.local"
      ;;
  esac
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local exit_code=$?
  local failed_command=$BASH_COMMAND
  if [[ "$failed_command" == *$'\n'* || ${#failed_command} -gt 240 ]]; then
    failed_command="${failed_command%%$'\n'*} ..."
  fi
  printf '\nDEPLOYMENT FAILED during: %s\n' "$CURRENT_STEP" >&2
  printf 'Command: %s\nExit code: %s\n' "$failed_command" "$exit_code" >&2
  printf 'No later deployment steps were run.\n' >&2
  exit "$exit_code"
}
trap on_error ERR

cleanup() {
  [[ -z "$RENDERED_NGINX_CONFIG" ]] || rm -f "$RENDERED_NGINX_CONFIG"
}
trap cleanup EXIT

if [[ $# -eq 0 ]]; then
  DEPLOY_KACHHAPA=true
  DEPLOY_MTG=true
  DEPLOY_NGINX=true
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hostname)
      shift
      [[ $# -gt 0 ]] || fail "Missing value for --hostname"
      normalize_hostname "$1"
      HOSTNAME_EXPLICITLY_SET=true
      ;;
    --kachhapa) DEPLOY_KACHHAPA=true ;;
    --mtg) DEPLOY_MTG=true ;;
    --nginx) DEPLOY_NGINX=true ;;
    --all)
      DEPLOY_KACHHAPA=true
      DEPLOY_MTG=true
      DEPLOY_NGINX=true
      ;;
    --check) CHECK_ONLY=true ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "Unknown option: $1"
      ;;
  esac
  shift
done

if $HOSTNAME_EXPLICITLY_SET; then
  readonly DESTINATION="${TARGET_USER}@${TARGET_HOSTNAME}"
elif [[ -n "$DESTINATION_OVERRIDE" ]]; then
  readonly DESTINATION="$DESTINATION_OVERRIDE"
else
  readonly DESTINATION="${TARGET_USER}@${TARGET_HOSTNAME}"
fi

# "--check" alone validates everything, matching the no-argument deployment set.
if $CHECK_ONLY && ! $DEPLOY_KACHHAPA && ! $DEPLOY_MTG && ! $DEPLOY_NGINX; then
  DEPLOY_KACHHAPA=true
  DEPLOY_MTG=true
  DEPLOY_NGINX=true
fi

if ! $DEPLOY_KACHHAPA && ! $DEPLOY_MTG && ! $DEPLOY_NGINX; then
  fail "Nothing selected. Choose --kachhapa, --mtg, --nginx, or --all."
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command is unavailable: $1"
}

require_path() {
  [[ -e "$1" ]] || fail "Required deployment path is missing: $1"
}

validate_service_file() {
  local service_file=$1
  grep -q '^\[Unit\]$' "$service_file" || fail "$service_file has no [Unit] section."
  grep -q '^\[Service\]$' "$service_file" || fail "$service_file has no [Service] section."
  grep -q '^ExecStart=' "$service_file" || fail "$service_file has no ExecStart."
}

validate_python_syntax() {
  python3 - "$@" <<'PY'
import sys
from pathlib import Path

for filename in sys.argv[1:]:
    source = Path(filename).read_bytes()
    compile(source, filename, "exec")
PY
}

validate_alembic_graph() {
  local migrations_versions_path="${1:-Flask/migrations/versions}"
  python3 - "$migrations_versions_path" <<'PY'
import ast
import sys
from pathlib import Path

migrations_path = Path(sys.argv[1])
revisions = {}
dependencies = set()

for migration_path in sorted(migrations_path.glob("*.py")):
    tree = ast.parse(migration_path.read_text(), filename=str(migration_path))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
            values[target.id] = ast.literal_eval(node.value)
    revision = values.get("revision")
    if not revision:
        raise SystemExit(f"{migration_path}: missing revision identifier")
    if revision in revisions:
        raise SystemExit(f"Duplicate Alembic revision {revision}: {revisions[revision]} and {migration_path}")
    revisions[revision] = migration_path
    down_revision = values.get("down_revision")
    if isinstance(down_revision, str):
        dependencies.add(down_revision)
    elif down_revision:
        dependencies.update(down_revision)

missing = sorted(dependencies.difference(revisions))
if missing:
    raise SystemExit(f"Alembic migration graph references missing revision(s): {', '.join(missing)}")

heads = sorted(set(revisions).difference(dependencies))
if not heads:
    raise SystemExit("Alembic migration graph has no head revision")
print(f"Alembic migration head{'s' if len(heads) != 1 else ''}: {', '.join(heads)}")
if len(heads) > 1:
    print("Multiple migration branches detected; deployment will apply all heads.")
PY
}

validate_nginx_structure() {
  local config_path=$1
  local expected_hostname=$2
  python3 - "$config_path" "$expected_hostname" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
hostname = sys.argv[2]
text = path.read_text()
depth = 0
for line_number, raw_line in enumerate(text.splitlines(), 1):
    line = raw_line.split("#", 1)[0]
    depth += line.count("{") - line.count("}")
    if depth < 0:
        raise SystemExit(f"{path}:{line_number}: unexpected closing brace")
if depth:
    raise SystemExit(f"{path}: unbalanced braces ({depth} block(s) left open)")
for required in ("upstream backend", "upstream mtg_backend", "upstream foundry_vtt", f"server_name {hostname}", f"server_name app.{hostname}", f"server_name mtg.{hostname}", f"server_name maps.{hostname}"):
    if required not in text:
        raise SystemExit(f"{path}: missing required directive: {required}")
PY
}

prepare_rendered_nginx() {
  [[ -n "$RENDERED_NGINX_CONFIG" ]] && return
  RENDERED_NGINX_CONFIG=$(mktemp "${TMPDIR:-/tmp}/kachhapa-nginx.XXXXXX")
  scripts/render-nginx-config.sh "$TARGET_HOSTNAME" "$RENDERED_NGINX_CONFIG" nginx.conf
}

local_preflight() {
  CURRENT_STEP="local preflight"
  echo "==> Running local preflight checks"

  require_command bash
  require_command curl
  require_command grep
  require_command python3
  require_path scripts/check-deployment-routes.sh
  require_path scripts/configure-publish-sudo.sh
  require_path scripts/kachhapa-deploy-root
  require_path scripts/kachhapa-publish.sudoers
  bash -n "$0"

  if $DEPLOY_KACHHAPA; then
    require_command npm
    for path in \
      Flask/requirements.txt Flask/import_5etools.py Flask/app.py \
      Flask/Harptos.json Flask/Gregorian.json \
      Flask/templates Flask/static Flask/migrations Flask/media/modules kachhapa-backend.service \
      Flask/media/modules/waterdeep_dragon_heist/waterdeep_texture.jpg \
      Flask/media/modules/waterdeep_dragon_heist/waterdeep_heightmap.png \
      Flask/media/modules/waterdeep_dragon_heist/waterdeep_dm_reference.jpg \
      Flask/media/modules/waterdeep_dragon_heist/waterdeep_location_key.jpg \
      webapp/package.json webapp/package-lock.json webapp/src webapp/public; do
      require_path "$path"
    done
    grep -qi '^gunicorn==' Flask/requirements.txt ||
      fail "Flask/requirements.txt must pin gunicorn."
    grep -qi '^gevent==' Flask/requirements.txt ||
      fail "Flask/requirements.txt must pin gevent."
    grep -qi '^gevent-websocket==' Flask/requirements.txt ||
      fail "Flask/requirements.txt must pin gevent-websocket."
    validate_python_syntax Flask/app.py
    validate_python_syntax Flask/module_templates.py
    [[ ! -f Flask/extract_dnd_pdf.py ]] || validate_python_syntax Flask/extract_dnd_pdf.py
    validate_alembic_graph
    validate_service_file kachhapa-backend.service
    grep -q '/venv/bin/gunicorn' kachhapa-backend.service ||
      fail "kachhapa-backend.service does not launch Gunicorn from the Kachhapa virtualenv."
  fi

  if $DEPLOY_MTG; then
    require_command npm
    for path in \
      MtG-webapp/backend/requirements.txt MtG-webapp/backend/run.py \
      MtG-webapp/backend/app MtG-webapp/backend/scripts MtG-webapp/data \
      MtG-webapp/backend/mtg-backend.service MtG-webapp/frontend/package.json \
      MtG-webapp/frontend/package-lock.json MtG-webapp/frontend/src \
      MtG-webapp/frontend/public; do
      require_path "$path"
    done
    validate_python_syntax MtG-webapp/backend/run.py
    validate_service_file MtG-webapp/backend/mtg-backend.service
    grep -qi '^gunicorn==' MtG-webapp/backend/requirements.txt ||
      fail "MtG-webapp/backend/requirements.txt must pin gunicorn."
    grep -q '/venv/bin/gunicorn' MtG-webapp/backend/mtg-backend.service ||
      fail "mtg-backend.service does not launch Gunicorn from the MTG virtualenv."
  fi

  if $DEPLOY_NGINX; then
    require_path nginx.conf
    require_path scripts/render-nginx-config.sh
    require_path 5etools-src/index.html
    prepare_rendered_nginx
    validate_nginx_structure "$RENDERED_NGINX_CONFIG" "$TARGET_HOSTNAME"
    echo "==> Rendered Nginx names for $TARGET_HOSTNAME"
  fi
}

build_frontends() {
  if $DEPLOY_KACHHAPA; then
    CURRENT_STEP="Kachhapa frontend build"
    echo "==> Building Kachhapa frontend locally"
    npm --prefix webapp run build
    require_path webapp/build/index.html
  fi

  if $DEPLOY_MTG; then
    CURRENT_STEP="MTG frontend build"
    echo "==> Building MTG frontend locally"
    npm --prefix MtG-webapp/frontend run build
    require_path MtG-webapp/frontend/build/index.html
  fi
}

remote_preflight() {
  CURRENT_STEP="remote preflight"
  echo "==> Checking Raspberry Pi prerequisites"
  require_command ssh
  require_command scp
  require_command rsync

  ssh -o BatchMode=yes -o ConnectTimeout=10 "$DESTINATION" "bash -s" -- \
    "$DEPLOY_KACHHAPA" "$DEPLOY_MTG" "$DEPLOY_NGINX" "$KACHHAPA_ROOT" "$MTG_ROOT" "$TARGET_HOSTNAME" <<'REMOTE'
set -Eeuo pipefail
deploy_kachhapa=$1
deploy_mtg=$2
deploy_nginx=$3
kachhapa_root=$4
mtg_root=$5
target_hostname=$6

for command_name in sudo systemctl cmp; do
  command -v "$command_name" >/dev/null || {
    echo "Missing required remote command: $command_name" >&2
    exit 1
  }
done

if ! sudo -n /usr/local/sbin/kachhapa-deploy-root check; then
  echo "Passwordless publish helper is not configured." >&2
  echo "Run once from the project directory: scripts/configure-publish-sudo.sh $target_hostname" >&2
  exit 1
fi

if "$deploy_kachhapa"; then
  for command_name in pg_dump file python3; do
    command -v "$command_name" >/dev/null || {
      echo "Missing required remote command for Kachhapa: $command_name" >&2
      exit 1
    }
  done
  test -d "$kachhapa_root/Flask" ||
    { echo "Missing remote directory: $kachhapa_root/Flask" >&2; exit 1; }
  test -x "$kachhapa_root/venv/bin/python" ||
    { echo "Missing Kachhapa virtualenv: $kachhapa_root/venv" >&2; exit 1; }
fi

if "$deploy_mtg"; then
  command -v python3 >/dev/null ||
    { echo "Missing required remote command for MTG: python3" >&2; exit 1; }
  command -v psql >/dev/null ||
    { echo "Missing required remote command for MTG: psql" >&2; exit 1; }
  test -d "$(dirname "$mtg_root")" ||
    { echo "Missing remote parent directory: $(dirname "$mtg_root")" >&2; exit 1; }
  test -x "$mtg_root/venv/bin/python" ||
    { echo "Missing MTG virtualenv; run install.sh while Internet access is available." >&2; exit 1; }
fi

if "$deploy_nginx"; then
  if ! command -v nginx >/dev/null && [[ ! -x /usr/sbin/nginx ]]; then
    echo "Missing required remote command for Nginx: nginx (checked PATH and /usr/sbin/nginx)" >&2
    exit 1
  fi
  command -v rsync >/dev/null ||
    { echo "Missing required remote command for 5etools: rsync" >&2; exit 1; }
  test -f /etc/nginx/nginx.conf ||
    { echo "Missing remote Nginx config: /etc/nginx/nginx.conf" >&2; exit 1; }
fi
REMOTE
}

deploy_tools() {
  CURRENT_STEP="5etools file transfer"
  echo "==> Deploying 5etools static site"
  ssh "$DESTINATION" "mkdir -p /home/ijohnson/5etools-src"
  rsync -avz --delete --exclude='.git/' 5etools-src/ \
    "$DESTINATION:/home/ijohnson/5etools-src/"
}

backup_kachhapa_database() {
  local backup_name="database_backup_${TARGET_HOST_SHORT}.dump"
  CURRENT_STEP="Raspberry Pi database backup"
  echo "==> Backing up the production Kachhapa database to $backup_name"
  ssh "$DESTINATION" "bash -s" -- "$backup_name" <<'REMOTE'
set -Eeuo pipefail
backup_name=$1
backup_path="/home/ijohnson/$backup_name"
tmp_dump=$(mktemp "/home/ijohnson/${backup_name}.XXXXXX")
trap 'rm -f "$tmp_dump"' EXIT
PGPASSWORD=admin pg_dump -U admin -h localhost -F c db -f "$tmp_dump"
mv "$tmp_dump" "$backup_path"
trap - EXIT
REMOTE

  CURRENT_STEP="database backup download"
  local local_dump
  local_dump=$(mktemp "./${backup_name}.XXXXXX")
  trap 'rm -f "${local_dump:-}"' RETURN
  scp "$DESTINATION:/home/ijohnson/$backup_name" "$local_dump"
  [[ -s "$local_dump" ]] || fail "Downloaded database backup is empty; existing backup was preserved."
  file "$local_dump" | grep -q "PostgreSQL custom database dump" ||
    fail "Downloaded file is not a PostgreSQL custom dump; existing backup was preserved."
  mv "$local_dump" "$backup_name"
  trap - RETURN
}

deploy_kachhapa() {
  CURRENT_STEP="Kachhapa file transfer"
  echo "==> Deploying Kachhapa"
  rsync -avz Flask/*.py \
    "$DESTINATION:$KACHHAPA_ROOT/Flask/"
  rsync -avz Flask/*.json \
    "$DESTINATION:$KACHHAPA_ROOT/Flask/"
  rsync -avz Flask/templates/ "$DESTINATION:$KACHHAPA_ROOT/Flask/templates/"
  rsync -avz Flask/static/ "$DESTINATION:$KACHHAPA_ROOT/Flask/static/"
  rsync -avz Flask/migrations/ "$DESTINATION:$KACHHAPA_ROOT/Flask/migrations/"
  rsync -avz Flask/media/modules/ "$DESTINATION:$KACHHAPA_ROOT/Flask/media/modules/"

  CURRENT_STEP="Kachhapa dependency check"
  scp Flask/requirements.txt "$DESTINATION:$KACHHAPA_ROOT/Flask/requirements.txt.new"
  ssh "$DESTINATION" "bash -s" -- "$KACHHAPA_ROOT" <<'REMOTE'
set -Eeuo pipefail
root=$1
current="$root/Flask/requirements.txt"
candidate="$current.new"
if [[ -f "$current" ]] && cmp -s "$candidate" "$current"; then
  rm -f "$candidate"
  echo "Kachhapa requirements unchanged; skipping pip install."
else
  echo "Kachhapa requirements changed; installing dependencies."
  "$root/venv/bin/python" -m pip install --disable-pip-version-check -r "$candidate"
  mv "$candidate" "$current"
fi
REMOTE

  backup_kachhapa_database

  CURRENT_STEP="Kachhapa database migration"
  echo "==> Applying all Kachhapa database migration heads"
  ssh "$DESTINATION" "cd $KACHHAPA_ROOT/Flask && $KACHHAPA_ROOT/venv/bin/flask db upgrade heads"

  CURRENT_STEP="Kachhapa frontend deployment"
  ssh "$DESTINATION" "mkdir -p '$KACHHAPA_ROOT/webapp/build.next'"
  rsync -avz --delete webapp/build/ "$DESTINATION:$KACHHAPA_ROOT/webapp/build.next/"
  CURRENT_STEP="Kachhapa frontend artifact verification"
  ssh "$DESTINATION" "bash -s" -- "$KACHHAPA_ROOT" <<'REMOTE'
set -Eeuo pipefail
root=$1
next="$root/webapp/build.next"
live="$root/webapp/build"
previous="$root/webapp/build.previous"

test -r "$next/index.html" && test -s "$next/index.html" || {
  echo "The staged Kachhapa frontend is missing a readable, non-empty build/index.html." >&2
  exit 1
}
rm -rf "$previous"
if [[ -d "$live" ]]; then
  mv "$live" "$previous"
fi
if ! mv "$next" "$live"; then
  [[ ! -d "$previous" ]] || mv "$previous" "$live"
  echo "Could not activate the staged Kachhapa frontend; the prior frontend was restored." >&2
  exit 1
fi
REMOTE

  CURRENT_STEP="Kachhapa service restart"
  if ! ssh "$DESTINATION" "sudo -n /usr/local/sbin/kachhapa-deploy-root restart $KACHHAPA_SERVICE"; then
    CURRENT_STEP="Kachhapa frontend rollback"
    ssh "$DESTINATION" "bash -s" -- "$KACHHAPA_ROOT" <<'REMOTE' || true
set -Eeuo pipefail
root=$1
live="$root/webapp/build"
previous="$root/webapp/build.previous"

if [[ -d "$previous" ]]; then
  mv "$live" "$root/webapp/build.failed.$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$previous" "$live"
  echo "Restored the previous Kachhapa frontend after the backend restart failed." >&2
fi
REMOTE
    fail "Kachhapa backend restart failed; the previous frontend was restored."
  fi
}

deploy_mtg() {
  CURRENT_STEP="MTG file transfer"
  echo "==> Deploying MTG Sandbox"
  ssh "$DESTINATION" "mkdir -p '$MTG_ROOT/backend/app' '$MTG_ROOT/backend/scripts' '$MTG_ROOT/data' '$MTG_ROOT/frontend/build'"
  rsync -avz MtG-webapp/backend/run.py \
    "$DESTINATION:$MTG_ROOT/backend/"
  rsync -avz MtG-webapp/backend/app/ "$DESTINATION:$MTG_ROOT/backend/app/"
  rsync -avz MtG-webapp/backend/scripts/ "$DESTINATION:$MTG_ROOT/backend/scripts/"
  rsync -avz MtG-webapp/backend/migrations/ "$DESTINATION:$MTG_ROOT/backend/migrations/"
  rsync -avz MtG-webapp/data/ "$DESTINATION:$MTG_ROOT/data/"
  rsync -avz --delete MtG-webapp/frontend/build/ "$DESTINATION:$MTG_ROOT/frontend/build/"

  CURRENT_STEP="MTG frontend artifact verification"
  ssh "$DESTINATION" "test -r '$MTG_ROOT/frontend/build/index.html' && test -s '$MTG_ROOT/frontend/build/index.html'" ||
    fail "The deployed MTG frontend is missing a readable, non-empty build/index.html."

  CURRENT_STEP="MTG dependency check"
  scp MtG-webapp/backend/requirements.txt "$DESTINATION:$MTG_ROOT/backend/requirements.txt.new"
  ssh "$DESTINATION" "bash -s" -- "$MTG_ROOT" <<'REMOTE'
set -Eeuo pipefail
root=$1
current="$root/backend/requirements.txt"
candidate="$current.new"
if [[ -f "$current" ]] && cmp -s "$candidate" "$current"; then
  rm -f "$candidate"
  echo "MTG requirements unchanged; skipping pip install."
else
  echo "MTG requirements changed; installing dependencies."
  "$root/venv/bin/python" -m pip install --disable-pip-version-check -r "$candidate"
  mv "$candidate" "$current"
fi
REMOTE

  CURRENT_STEP="MTG database setup"
  ssh "$DESTINATION" "sudo -n /usr/local/sbin/kachhapa-deploy-root mtg-db"
  ssh "$DESTINATION" "cd '$MTG_ROOT/backend' && DATABASE_URL='postgresql+psycopg2://admin:admin@127.0.0.1:5432/mtg_sandbox' PG_RAW_URL='postgresql://admin:admin@127.0.0.1:5432/mtg_sandbox' '$MTG_ROOT/venv/bin/python' -c 'from run import initialize_database; initialize_database()'"

  CURRENT_STEP="MTG database migration"
  echo "==> Applying MTG database migration heads"
  ssh "$DESTINATION" "cd '$MTG_ROOT/backend' && FLASK_APP='app:create_app' DATABASE_URL='postgresql+psycopg2://admin:admin@127.0.0.1:5432/mtg_sandbox' PG_RAW_URL='postgresql://admin:admin@127.0.0.1:5432/mtg_sandbox' '$MTG_ROOT/venv/bin/flask' db upgrade heads"

  CURRENT_STEP="MTG service restart"
  ssh "$DESTINATION" "sudo -n /usr/local/sbin/kachhapa-deploy-root restart $MTG_SERVICE"

  CURRENT_STEP="MTG service health check"
  ssh "$DESTINATION" "for attempt in {1..15}; do curl --fail --silent http://127.0.0.1:5050/api/health >/dev/null 2>&1 && exit 0; sleep 2; done; echo 'mtg-backend.service did not answer on port 5050 after 30 seconds' >&2; exit 1"
}

deploy_nginx() {
  CURRENT_STEP="Nginx configuration update"
  prepare_rendered_nginx
  echo "==> Deploying Nginx configuration for $TARGET_HOSTNAME"
  scp "$RENDERED_NGINX_CONFIG" "$DESTINATION:/home/ijohnson/nginx.conf.new"
  ssh "$DESTINATION" "sudo -n /usr/local/sbin/kachhapa-deploy-root nginx"
}

local_preflight
build_frontends

if $CHECK_ONLY; then
  CURRENT_STEP="validation complete"
  echo "Validation complete. No Raspberry Pi connection or deployment was attempted."
  exit 0
fi

remote_preflight
$DEPLOY_KACHHAPA && deploy_kachhapa
$DEPLOY_MTG && deploy_mtg
if $DEPLOY_NGINX; then
  deploy_tools
  deploy_nginx
fi

CURRENT_STEP="publisher-side route verification"
scripts/check-deployment-routes.sh "$TARGET_HOSTNAME"

CURRENT_STEP="deployment complete"
echo "Deployment complete."
