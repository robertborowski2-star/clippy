#!/usr/bin/env bash
# Clippy bootstrap script for Debian (Pi OS Bookworm) / Ubuntu 22.04+.
# Idempotent where feasible. Fails loudly on any step.
#
# Run as your normal user from a checkout of the repo:
#     bash setup_clippy.sh
#
# Provisions a `clippy` system user, deploys the repo to /home/clippy/clippy-src,
# builds a venv, installs deps, installs the systemd unit, and enables it
# (without --now). Operator finishes by editing .env and starting the service.
#
# State migration (clippy.db + research walnuts + project walnuts) is NOT
# handled here — see the printed next-steps for the rsync commands you'll
# want to run manually from the previous host.

set -euo pipefail

log()  { printf '\033[1;36m[clippy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[clippy]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[clippy]\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || die "setup_clippy.sh is Linux-only."
[[ $EUID -ne 0 ]] || die "Run as your normal user; sudo will be invoked as needed."

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_USER="clippy"
SERVICE_HOME="/home/${SERVICE_USER}"
DEPLOY_DIR="${SERVICE_HOME}/clippy-src"
VENV_DIR="${DEPLOY_DIR}/venv"
ENV_FILE="${DEPLOY_DIR}/.env"
SYSTEMD_DIR="/etc/systemd/system"
UNIT_FILE="${SYSTEMD_DIR}/clippy.service"

# --- baseline packages ------------------------------------------------------

log "Updating apt and installing baseline packages"
sudo apt-get update
sudo apt-get install -y \
    build-essential git curl rsync ufw \
    ca-certificates \
    python3 python3-venv python3-dev

# --- service user + deploy dir ----------------------------------------------

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    log "Creating system user ${SERVICE_USER}"
    sudo useradd --system --create-home --home-dir "${SERVICE_HOME}" \
        --shell /bin/bash "${SERVICE_USER}"
fi

log "Deploying repo to ${DEPLOY_DIR}"
sudo mkdir -p "${DEPLOY_DIR}"
# --delete is intentional so files removed in source disappear on redeploy.
# .env and venv are preserved so secrets and the installed venv survive.
sudo rsync -a --delete \
    --exclude 'venv/' \
    --exclude '.env' \
    --exclude '__pycache__/' \
    --exclude '.git/' \
    --exclude '.DS_Store' \
    --exclude '.claude/' \
    "${REPO_DIR}/" "${DEPLOY_DIR}/"
sudo chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DEPLOY_DIR}"

# --- Python venv as the service user ----------------------------------------

log "Creating Python venv at ${VENV_DIR} (as ${SERVICE_USER})"
sudo -u "${SERVICE_USER}" bash <<EOF
set -euo pipefail
[[ -d '${VENV_DIR}' ]] || python3 -m venv '${VENV_DIR}'
'${VENV_DIR}/bin/pip' install --upgrade pip
'${VENV_DIR}/bin/pip' install -r '${DEPLOY_DIR}/requirements.txt'
EOF

# --- .env -------------------------------------------------------------------

if ! sudo test -f "${ENV_FILE}"; then
    log "Generating .env from template (operator must fill in secrets)"
    sudo -u "${SERVICE_USER}" cp "${DEPLOY_DIR}/.env.template" "${ENV_FILE}"
    sudo chmod 600 "${ENV_FILE}"
fi

# --- systemd unit -----------------------------------------------------------

log "Writing systemd unit ${UNIT_FILE}"
sudo tee "${UNIT_FILE}" >/dev/null <<EOF
[Unit]
Description=Clippy Research Agent
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${DEPLOY_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${DEPLOY_DIR}/main.py --no-bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
log "Enabling clippy.service (not started yet — fill in .env first)"
sudo systemctl enable clippy.service >/dev/null

# --- firewall ---------------------------------------------------------------

log "Configuring UFW"
sudo ufw allow OpenSSH || true
sudo ufw --force enable || true

# --- summary ----------------------------------------------------------------

cat <<EOF

[clippy] Install complete.

  Service user:   ${SERVICE_USER}
  Repo deployed:  ${DEPLOY_DIR}
  Env file:       ${ENV_FILE}
  Venv:           ${VENV_DIR}

Next steps:

  1. Fill in ${ENV_FILE} with secrets:
       sudo -u ${SERVICE_USER} \$EDITOR ${ENV_FILE}
     Required: ANTHROPIC_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, AGENT_API_KEY
     For Darwin integration: DARWIN_INGEST_URL, DARWIN_API_KEY

  2. Migrate state from the previous host (if any). On THIS host, run:

       # Research data (DB + research walnuts)
       sudo rsync -avz --rsync-path='sudo rsync' \\
           pi@<old-host>.local:/home/pi/clippy/ \\
           ${SERVICE_HOME}/clippy/
       sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${SERVICE_HOME}/clippy

       # Project walnuts (read by Clippy as memory.read_project_context)
       sudo rsync -avz --rsync-path='sudo rsync' \\
           pi@<old-host>.local:/home/pi/walnuts/ \\
           ${SERVICE_HOME}/walnuts/
       sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${SERVICE_HOME}/walnuts

  3. Start the service:
       sudo systemctl start clippy.service

  4. Watch the journal for the next scheduled job:
       sudo journalctl -u clippy.service -f

EOF
