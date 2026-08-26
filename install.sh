#!/bin/bash
# Note: don't run this script while connected to the Pi's Wi-Fi AP, because the
# connection will drop when we reconfigure the AP settings.
set -euo pipefail

TARGET_USER="ijohnson"
TARGET_HOST_SHORT="raspberrypi"
TARGET_HOSTNAME="raspberrypi.local"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--hostname NAME]

--hostname accepts either a short hostname like raspberrypii or a fully
qualified name like raspberrypii.local or raspberrypii.lan.
The generated Nginx config serves NAME plus app.NAME, tools.NAME, mtg.NAME,
and maps.NAME, allowing multiple Pi installations to share one network.

Example: ./install.sh --hostname kachhapa-two
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hostname)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for --hostname" >&2; usage >&2; exit 1; }
      normalize_hostname "$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
  shift
done

DESTINATION="${TARGET_USER}@${TARGET_HOSTNAME}"

RENDERED_NGINX_CONFIG=""
cleanup() {
  [[ -z "$RENDERED_NGINX_CONFIG" ]] || rm -f "$RENDERED_NGINX_CONFIG"
}
trap cleanup EXIT

REMOTE_BASE="/home/ijohnson/Kachhapa"
REMOTE_FLASK="$REMOTE_BASE/Flask"
REMOTE_WEB="$REMOTE_BASE/webapp"
REMOTE_VENV="$REMOTE_BASE/venv"
REMOTE_MTG="/home/ijohnson/MtG-webapp"
REMOTE_MTG_BACKEND="$REMOTE_MTG/backend"
REMOTE_MTG_FRONTEND="$REMOTE_MTG/frontend"
REMOTE_MTG_VENV="$REMOTE_MTG/venv"

# ---- Wi-Fi AP settings ----
AP_SSID="PiNetwork"
AP_PASS="password"          # >= 8 chars
AP_IP="10.42.0.1"
AP_CIDR="10.42.0.1/24"
AP_DHCP_START="10.42.0.50"
AP_DHCP_END="10.42.0.150"
LAN_IF="wlan0"
WAN_IF="eth0"
COUNTRY_CODE="US"
CHANNEL="6"

echo "==> Environment summary"
printf 'Local host: %s\n' "$(hostname)"
printf 'Local shell: %s\n' "${SHELL:-unknown}"
printf 'Local python3: %s\n' "$(python3 --version 2>/dev/null || echo unavailable)"
printf 'Target host: %s\n' "$DESTINATION"

echo "==> 0) Sanity check local files"
for f in \
  "Flask/requirements.txt" "Flask/app.py" "Flask/Harptos.json" "Flask/Gregorian.json" "nginx.conf" \
  "Flask/module_templates.py" \
  "Flask/media/modules/waterdeep_dragon_heist/waterdeep_texture.jpg" \
  "Flask/media/modules/waterdeep_dragon_heist/waterdeep_heightmap.png" \
  "Flask/media/modules/waterdeep_dragon_heist/waterdeep_dm_reference.jpg" \
  "Flask/media/modules/waterdeep_dragon_heist/waterdeep_location_key.jpg" \
  "scripts/render-nginx-config.sh" "scripts/check-deployment-routes.sh" \
  "scripts/configure-publish-sudo.sh" "scripts/kachhapa-deploy-root" \
  "scripts/kachhapa-publish.sudoers" \
  "kachhapa-backend.service" "5etools-src/index.html" \
  "MtG-webapp/backend/requirements.txt" "MtG-webapp/backend/run.py" \
  "MtG-webapp/backend/mtg-backend.service" "MtG-webapp/frontend/package.json"; do
  [[ -f "$f" ]] || { echo "Missing required file: $f"; exit 1; }
done
for d in "Flask/media/modules" "MtG-webapp/backend/app" "MtG-webapp/backend/scripts" "MtG-webapp/data"; do
  [[ -d "$d" ]] || { echo "Missing required directory: $d"; exit 1; }
done
command -v npm >/dev/null 2>&1 || { echo "Missing required local command: npm"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "Missing required local command: curl"; exit 1; }

echo "==> Building MTG frontend locally"
npm --prefix MtG-webapp/frontend run build
[[ -f MtG-webapp/frontend/build/index.html ]] || { echo "MTG frontend build did not create index.html"; exit 1; }

RENDERED_NGINX_CONFIG=$(mktemp "${TMPDIR:-/tmp}/kachhapa-nginx.XXXXXX")
scripts/render-nginx-config.sh "$TARGET_HOSTNAME" "$RENDERED_NGINX_CONFIG" nginx.conf
printf 'Nginx names: %s, app.%s, tools.%s, mtg.%s, maps.%s\n' \
  "$TARGET_HOSTNAME" "$TARGET_HOSTNAME" "$TARGET_HOSTNAME" "$TARGET_HOSTNAME" "$TARGET_HOSTNAME"

echo "==> 1) Install base packages"
ssh -tt "$DESTINATION" "sudo apt update && sudo apt install -y \
  nginx curl rsync ffmpeg python3-venv python3-pip python3-dev build-essential pkg-config \
  libpq-dev libssl-dev libffi-dev python3-setuptools \
  cargo rustc \
  postgresql postgresql-contrib \
  rabbitmq-server \
  avahi-daemon avahi-utils \
  hostapd dnsmasq dhcpcd5 \
  iptables iptables-persistent"

echo "==> 2) Hostname + mDNS"
ssh -tt "$DESTINATION" "sudo hostnamectl set-hostname $TARGET_HOST_SHORT && sudo systemctl enable --now avahi-daemon"

echo "==> 2.5) Configure narrowly scoped passwordless publishing"
scripts/configure-publish-sudo.sh "$TARGET_HOSTNAME"

echo "==> Configure Avahi hostname aliases for LAN access"
ssh -tt "$DESTINATION" "sudo bash -lc '
set -e

ETH_IP=\$(ip -4 -o addr show eth0 | awk '\''{print \$4}'\'' | cut -d/ -f1 | head -n1)

if [ -n \"\$ETH_IP\" ]; then
  cat > /etc/avahi/hosts <<EOF
# Extra mDNS hostname aliases for this Pi on the LAN
\$ETH_IP app.$TARGET_HOSTNAME
\$ETH_IP tools.$TARGET_HOSTNAME
\$ETH_IP mtg.$TARGET_HOSTNAME
\$ETH_IP maps.$TARGET_HOSTNAME
EOF

  systemctl restart avahi-daemon
  echo \"Configured Avahi aliases on \$ETH_IP\"
else
  echo \"No eth0 IPv4 address found; skipping /etc/avahi/hosts aliases\"
fi
'"

echo "==> 3) Create directory structure"
ssh "$DESTINATION" "mkdir -p \
  '$REMOTE_FLASK/templates' \
  '$REMOTE_FLASK/static' \
  '$REMOTE_FLASK/media/modules' \
  '$REMOTE_FLASK/GameElements' \
  '$REMOTE_WEB/build' \
  '$REMOTE_WEB/src' \
  '$REMOTE_WEB/public' \
  '$REMOTE_MTG_BACKEND/app' \
  '$REMOTE_MTG_BACKEND/scripts' \
  '$REMOTE_MTG/data' \
  '$REMOTE_MTG_FRONTEND/build' \
  '/home/ijohnson/5etools-src'"

echo "==> 4) Copy app files (Flask + web + database backup)"
rsync -avz Flask/requirements.txt "$DESTINATION:$REMOTE_FLASK/"
rsync -avz Flask/*.py "$DESTINATION:$REMOTE_FLASK/"
rsync -avz Flask/*.json "$DESTINATION:$REMOTE_FLASK/"
rsync -avz Flask/templates/ "$DESTINATION:$REMOTE_FLASK/templates/"
rsync -avz Flask/static/    "$DESTINATION:$REMOTE_FLASK/static/"
rsync -avz Flask/migrations/ "$DESTINATION:$REMOTE_FLASK/migrations/"
rsync -avz Flask/media/modules/ "$DESTINATION:$REMOTE_FLASK/media/modules/"

# assumes you already built locally
rsync -avz webapp/build/  "$DESTINATION:$REMOTE_WEB/build/"
rsync -avz webapp/src/    "$DESTINATION:$REMOTE_WEB/src/"
rsync -avz webapp/public/ "$DESTINATION:$REMOTE_WEB/public/"

rsync -avz MtG-webapp/backend/requirements.txt MtG-webapp/backend/run.py "$DESTINATION:$REMOTE_MTG_BACKEND/"
rsync -avz MtG-webapp/backend/app/ "$DESTINATION:$REMOTE_MTG_BACKEND/app/"
rsync -avz MtG-webapp/backend/scripts/ "$DESTINATION:$REMOTE_MTG_BACKEND/scripts/"
rsync -avz MtG-webapp/data/ "$DESTINATION:$REMOTE_MTG/data/"
rsync -avz --delete MtG-webapp/frontend/build/ "$DESTINATION:$REMOTE_MTG_FRONTEND/build/"
rsync -avz --delete --exclude='.git/' 5etools-src/ "$DESTINATION:/home/ijohnson/5etools-src/"

# copy database backup if it exists
if [ -f "database_backup.dump" ]; then
  rsync -avz database_backup.dump "$DESTINATION:$REMOTE_BASE/"
fi

echo "==> 5) Create venv + install deps (no sudo for pip)"
ssh "$DESTINATION" "python3 --version && hostname -f && uname -a"
ssh "$DESTINATION" "bash -lc '
set -e
if [ ! -d \"$REMOTE_VENV\" ]; then
  python3 -m venv \"$REMOTE_VENV\"
fi
\"$REMOTE_VENV/bin/python\" -m pip install --upgrade pip wheel setuptools
\"$REMOTE_VENV/bin/pip\" install -r \"$REMOTE_FLASK/requirements.txt\"

if [ ! -d \"$REMOTE_MTG_VENV\" ]; then
  python3 -m venv \"$REMOTE_MTG_VENV\"
fi
\"$REMOTE_MTG_VENV/bin/python\" -m pip install --upgrade pip wheel setuptools
\"$REMOTE_MTG_VENV/bin/pip\" install -r \"$REMOTE_MTG_BACKEND/requirements.txt\"
'"

echo "==> 6) Install hostname-specific nginx.conf + test"
scp "$RENDERED_NGINX_CONFIG" "$DESTINATION:/home/ijohnson/nginx.conf.new"
ssh -tt "$DESTINATION" "sudo install -o root -g root -m 0644 /home/ijohnson/nginx.conf.new /etc/nginx/nginx.conf.new && \
  sudo nginx -t -c /etc/nginx/nginx.conf.new && \
  sudo mv /etc/nginx/nginx.conf.new /etc/nginx/nginx.conf && \
  rm /home/ijohnson/nginx.conf.new"

echo "==> 7) Install systemd services (copy then sudo install)"
scp kachhapa-backend.service "$DESTINATION:/home/ijohnson/kachhapa-backend.service"
scp MtG-webapp/backend/mtg-backend.service "$DESTINATION:/home/ijohnson/mtg-backend.service"
ssh -tt "$DESTINATION" "sudo install -o root -g root -m 0644 /home/ijohnson/kachhapa-backend.service /etc/systemd/system/kachhapa-backend.service && \
  sudo install -o root -g root -m 0644 /home/ijohnson/mtg-backend.service /etc/systemd/system/mtg-backend.service && \
  rm /home/ijohnson/kachhapa-backend.service /home/ijohnson/mtg-backend.service && \
  sudo systemctl daemon-reload && sudo systemctl enable kachhapa-backend mtg-backend"

echo "==> 8) Start base services"
ssh -tt "$DESTINATION" "sudo systemctl enable --now nginx postgresql rabbitmq-server && \
  sudo systemctl reload nginx"

echo "==> 8.5) Ensure PostgreSQL cluster is online"
ssh -tt "$DESTINATION" "bash -lc '
set -e

if command -v pg_lsclusters >/dev/null 2>&1; then
  echo \"Current PostgreSQL clusters:\"
  pg_lsclusters || true

  # Start any cluster that is down
  while read -r ver name port status owner data log; do
    if [ \"\$ver\" != \"Ver\" ] && [ \"\$status\" = \"down\" ]; then
      echo \"Starting PostgreSQL cluster \$ver/\$name...\"
      sudo pg_ctlcluster \$ver \$name start
    fi
  done < <(pg_lsclusters)

  echo \"PostgreSQL clusters after start attempt:\"
  pg_lsclusters || true
else
  echo \"pg_lsclusters not found; falling back to systemctl restart postgresql\"
  sudo systemctl restart postgresql
fi
'"

echo "==> 8.6) Verify PostgreSQL is listening"
ssh -t "$DESTINATION" "ss -lntp | grep 5432 || true"

echo "==> 8.7) Create MTG database and initialize its schema"
ssh -tt "$DESTINATION" "sudo -u postgres psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='admin'\" | grep -q 1 || sudo -u postgres psql -c \"CREATE USER admin WITH PASSWORD 'admin';\""
ssh -tt "$DESTINATION" "sudo -u postgres psql -tc \"SELECT 1 FROM pg_database WHERE datname='mtg_sandbox'\" | grep -q 1 || sudo -u postgres createdb -O admin mtg_sandbox"
ssh "$DESTINATION" "cd '$REMOTE_MTG_BACKEND' && DATABASE_URL='postgresql+psycopg2://admin:admin@127.0.0.1:5432/mtg_sandbox' PG_RAW_URL='postgresql://admin:admin@127.0.0.1:5432/mtg_sandbox' '$REMOTE_MTG_VENV/bin/python' -c 'from run import initialize_database; initialize_database()'"

echo "==> 9) Restore database from backup if available"
ssh -tt "$DESTINATION" "bash -lc '
set -e
DB_BACKUP=\"$REMOTE_BASE/database_backup.dump\"

if [ -f \"\$DB_BACKUP\" ]; then
  echo \"Found database backup, restoring...\"

  TMP_BACKUP=\"/tmp/database_backup.dump\"
  cp \"\$DB_BACKUP\" \"\$TMP_BACKUP\"
  chmod 644 \"\$TMP_BACKUP\"

  sudo -u postgres psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='\''admin'\''\" | grep -q 1 || \
    sudo -u postgres psql -c \"CREATE USER admin WITH PASSWORD '\''admin'\'';\"

  sudo -u postgres psql -c \"DROP DATABASE IF EXISTS db;\"
  sudo -u postgres psql -c \"CREATE DATABASE db OWNER admin TEMPLATE template0 ENCODING '\''UTF8'\'';\"

  sudo -u postgres pg_restore -d db --clean --if-exists \"\$TMP_BACKUP\"

  rm -f \"\$TMP_BACKUP\"
  echo \"Database restore completed\"
else
  echo \"No database backup found at \$DB_BACKUP, skipping restore\"
fi
'"

echo "==> 9.5) Stamp restored database to current Alembic head"
ssh -tt "$DESTINATION" "bash -lc '
set -e
cd /home/ijohnson/Kachhapa/Flask
source /home/ijohnson/Kachhapa/venv/bin/activate
sudo -u postgres psql -d db -c \"DROP TABLE IF EXISTS alembic_version;\"
flask db stamp head
'"

echo "==> 10) Start app services"
ssh -tt "$DESTINATION" "sudo systemctl restart kachhapa-backend mtg-backend"

echo "==> 11) Quick checks"
ssh -tt "$DESTINATION" "hostname; \
  ip -brief addr show $LAN_IF || true; \
  systemctl --no-pager --full status kachhapa-backend | head -n 30; \
  systemctl --no-pager --full status mtg-backend | head -n 30; \
  curl --fail --silent --show-error http://127.0.0.1:5050/api/health >/dev/null; \
  sudo nginx -t"

echo "==> 11.5) Verify public routes from the publishing machine"
scripts/check-deployment-routes.sh "$TARGET_HOSTNAME"

echo "==> 12) Final step: switch wlan0 from client mode to AP mode"
echo "==> About to cut over wlan0 into AP mode. SSH may disconnect after this point."
ssh "$DESTINATION" "umask 077 && cat > /home/ijohnson/kachhapa-ap-setup.sh" <<EOS
set -euo pipefail

LAN_IF="$LAN_IF"
WAN_IF="$WAN_IF"
AP_SSID="$AP_SSID"
AP_PASS="$AP_PASS"
AP_CIDR="$AP_CIDR"
AP_IP="$AP_IP"
DHCP_START="$AP_DHCP_START"
DHCP_END="$AP_DHCP_END"
COUNTRY_CODE="$COUNTRY_CODE"
CHANNEL="$CHANNEL"

echo "==> Sanity: check interface exists"
ip link show "\$LAN_IF" >/dev/null 2>&1 || { echo "Interface \$LAN_IF not found"; ip -br link; exit 1; }

echo "==> Stop AP services while reconfiguring"
systemctl stop hostapd 2>/dev/null || true
systemctl stop dnsmasq 2>/dev/null || true

echo "==> Free wlan0 from client mode"
systemctl stop NetworkManager 2>/dev/null || true
systemctl disable NetworkManager 2>/dev/null || true
systemctl stop wpa_supplicant 2>/dev/null || true
systemctl stop wpa_supplicant@wlan0 2>/dev/null || true

echo "==> Configure static IP for AP (dhcpcd)"
grep -q "^interface \$LAN_IF" /etc/dhcpcd.conf 2>/dev/null || cat >> /etc/dhcpcd.conf <<EOF

interface \$LAN_IF
  static ip_address=\$AP_CIDR
  nohook wpa_supplicant
EOF

echo "==> Assign AP IP immediately"
ip addr flush dev "\$LAN_IF" 2>/dev/null || true
ip addr add "\$AP_CIDR" dev "\$LAN_IF"
ip link set "\$LAN_IF" up

echo "==> Configure dnsmasq DHCP + DNS"
mkdir -p /etc/dnsmasq.d
cat > /etc/dnsmasq.d/kachhapa-ap.conf <<EOF
interface=\$LAN_IF
listen-address=127.0.0.1,\$AP_IP
bind-dynamic

dhcp-range=\$DHCP_START,\$DHCP_END,255.255.255.0,12h

domain-needed
bogus-priv

dhcp-option=option:router,\$AP_IP
dhcp-option=option:dns-server,\$AP_IP

address=/$TARGET_HOSTNAME/\$AP_IP
address=/app.$TARGET_HOSTNAME/\$AP_IP
address=/tools.$TARGET_HOSTNAME/\$AP_IP
address=/mtg.$TARGET_HOSTNAME/\$AP_IP
address=/maps.$TARGET_HOSTNAME/\$AP_IP
EOF

echo "==> Configure upstream DNS for dnsmasq"
if grep -q "^no-resolv" /etc/dnsmasq.conf 2>/dev/null; then
  sed -i '/^server=8\.8\.8\.8$/d;/^server=1\.1\.1\.1$/d;/^server=192\.168\./d' /etc/dnsmasq.conf
else
  echo "no-resolv" >> /etc/dnsmasq.conf
fi

WAN_GW=\$(ip route | awk '/default/ {print \$3; exit}')
if [ -n "\$WAN_GW" ]; then
  grep -q "^server=\$WAN_GW\$" /etc/dnsmasq.conf 2>/dev/null || echo "server=\$WAN_GW" >> /etc/dnsmasq.conf
fi
grep -q "^server=8.8.8.8$" /etc/dnsmasq.conf 2>/dev/null || echo "server=8.8.8.8" >> /etc/dnsmasq.conf
grep -q "^server=1.1.1.1$" /etc/dnsmasq.conf 2>/dev/null || echo "server=1.1.1.1" >> /etc/dnsmasq.conf

grep -q "^conf-dir=/etc/dnsmasq.d" /etc/dnsmasq.conf 2>/dev/null || \
  echo "conf-dir=/etc/dnsmasq.d,*.conf" >> /etc/dnsmasq.conf

echo "==> Configure hostapd"
cat > /etc/hostapd/hostapd.conf <<EOF
country_code=\$COUNTRY_CODE
interface=\$LAN_IF
ssid=\$AP_SSID
hw_mode=g
channel=\$CHANNEL
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_passphrase=\$AP_PASS
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

echo "==> Configure dnsmasq startup ordering"
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat > /etc/systemd/system/dnsmasq.service.d/override.conf <<'EOF'
[Unit]
After=hostapd.service network-online.target
Wants=hostapd.service network-online.target

[Service]
Restart=on-failure
RestartSec=2
ExecStartPre=/bin/sh -c 'for i in $(seq 1 15); do ip link show wlan0 >/dev/null 2>&1 && exit 0; sleep 1; done; echo "wlan0 not ready"; exit 1'
EOF

systemctl daemon-reload

echo "==> Enable IP forwarding"
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-kachhapa-ipforward.conf
sysctl --system

echo "==> Configure NAT and forwarding with iptables"
iptables -t nat -F POSTROUTING
iptables -F FORWARD

iptables -t nat -A POSTROUTING -s 10.42.0.0/24 -o "\$WAN_IF" -j MASQUERADE
iptables -A FORWARD -i "\$WAN_IF" -o "\$LAN_IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i "\$LAN_IF" -o "\$WAN_IF" -j ACCEPT

netfilter-persistent save || true

echo "==> Enable services"
systemctl unmask hostapd || true
systemctl enable hostapd
systemctl enable dnsmasq
systemctl enable dhcpcd 2>/dev/null || true

echo "==> Restart networking + AP services"
systemctl restart dhcpcd 2>/dev/null || true
systemctl restart dnsmasq
systemctl restart hostapd

echo "==> Final AP status"
ip -brief addr show "\$LAN_IF" || true
systemctl --no-pager --full status hostapd | head -n 20 || true
systemctl --no-pager --full status dnsmasq | head -n 20 || true
iptables -t nat -L -n -v || true
iptables -L FORWARD -n -v || true
EOS

ssh -tt "$DESTINATION" 'sudo bash /home/ijohnson/kachhapa-ap-setup.sh; result=$?; rm -f /home/ijohnson/kachhapa-ap-setup.sh; exit $result'
