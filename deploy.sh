#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh  —  Script unique de déploiement ENSForm
#
# MODES LOCAUX (sur cette machine) :
#   ./deploy.sh                 Installation complète (Gunicorn+Nginx+Tunnel)
#   ./deploy.sh --restart       Redémarrer le service
#   ./deploy.sh --update        Mettre à jour les dépendances + redémarrer
#   ./deploy.sh --tunnel        (Re)configurer le tunnel Cloudflare
#   ./deploy.sh --dev           Lancer le serveur de développement Flask
#
# MODES REMOTE (déploiement via SSH vers RPi ou autre serveur) :
#   ./deploy.sh --remote                 Déploiement complet sur la cible
#   ./deploy.sh --remote --update        Sync fichiers + redémarrer
#   ./deploy.sh --remote --restart       Redémarrer le service distant
#   ./deploy.sh --remote --tunnel        Reconfigurer tunnel distant
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="$(whoami)"
SERVICE_NAME="ensform"
GUNICORN_PORT=8000
ENV_FILE="$APP_DIR/.env"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()     { echo -e "${RED}[ERR]${NC}  $*" >&2; exit 1; }
step()    { echo ""; echo -e "${BOLD}── $* ──────────────────────────────────────${NC}"; }

[[ $EUID -eq 0 ]] && err "Ne pas lancer en root. sudo sera utilisé si besoin."

# ── Parse des arguments ──────────────────────────────────────────────────────
REMOTE=false
MODE="full"
for arg in "$@"; do
  case "$arg" in
    --remote)   REMOTE=true ;;
    --restart)  MODE="restart" ;;
    --update)   MODE="update" ;;
    --tunnel)   MODE="tunnel" ;;
    --dev)      MODE="dev" ;;
    --help|-h)
      head -17 "$0" | tail -16
      exit 0
      ;;
    *) err "Option inconnue : $arg. Utilisez --help." ;;
  esac
done

# ═════════════════════════════════════════════════════════════════════════════
# REMOTE : délégation via SSH
# ═════════════════════════════════════════════════════════════════════════════
if $REMOTE; then
  REMOTE_CONF="$APP_DIR/.remote_config"

  if [[ -f "$REMOTE_CONF" ]]; then
    source "$REMOTE_CONF"
  else
    REMOTE_HOST=""
    REMOTE_USER="pi"
    REMOTE_DIR="/home/pi/form"
  fi

  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo -e "   ${BOLD}Déploiement ENSForm → distant${NC}  [mode: $MODE]"
  echo "═══════════════════════════════════════════════════════"
  echo ""

  read -rp "  Hôte (IP ou hostname) [${REMOTE_HOST:-?}] : " INPUT_HOST
  REMOTE_HOST="${INPUT_HOST:-$REMOTE_HOST}"
  [[ -z "$REMOTE_HOST" ]] && err "Adresse obligatoire."

  read -rp "  Utilisateur SSH [${REMOTE_USER}] : " INPUT_USER
  REMOTE_USER="${INPUT_USER:-$REMOTE_USER}"

  read -rp "  Dossier distant [${REMOTE_DIR}] : " INPUT_DIR
  REMOTE_DIR="${INPUT_DIR:-$REMOTE_DIR}"

  cat > "$REMOTE_CONF" <<EOF
REMOTE_HOST="$REMOTE_HOST"
REMOTE_USER="$REMOTE_USER"
REMOTE_DIR="$REMOTE_DIR"
EOF

  SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
  info "Cible : $SSH_TARGET:$REMOTE_DIR"

  info "Vérification SSH…"
  ssh -o ConnectTimeout=10 "$SSH_TARGET" exit || err "Impossible de joindre $SSH_TARGET"
  success "SSH OK."

  RSYNC_EXCLUDES=(
    --exclude='venv/' --exclude='instance/' --exclude='__pycache__/'
    --exclude='*.pyc' --exclude='.env' --exclude='.remote_config'
    --exclude='*.db' --exclude='*.sqlite'
  )

  do_sync() {
    info "Synchronisation des fichiers…"
    ssh "$SSH_TARGET" "mkdir -p $REMOTE_DIR"
    rsync -az --progress "${RSYNC_EXCLUDES[@]}" "$APP_DIR/" "${SSH_TARGET}:${REMOTE_DIR}/"
    success "Fichiers synchronisés."
  }

  case "$MODE" in
    restart)
      ssh "$SSH_TARGET" "sudo systemctl restart $SERVICE_NAME"
      success "Service distant redémarré."
      ;;
    update)
      do_sync
      ssh "$SSH_TARGET" "cd $REMOTE_DIR && bash deploy.sh --update"
      ;;
    tunnel)
      do_sync
      ssh -t "$SSH_TARGET" "cd $REMOTE_DIR && bash deploy.sh --tunnel"
      ;;
    full)
      do_sync
      info "Lancement de l'installation sur la cible (session interactive)…"
      ssh -t "$SSH_TARGET" "cd $REMOTE_DIR && bash deploy.sh"
      ;;
  esac

  echo ""
  success "Opération distante terminée."
  exit 0
fi

# ═════════════════════════════════════════════════════════════════════════════
# LOCAL : exécution sur cette machine
# ═════════════════════════════════════════════════════════════════════════════

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "   ${BOLD}ENSForm${NC}  [mode: $MODE]"
echo "   Dossier : $APP_DIR"
echo "═══════════════════════════════════════════════════════════════"

# ── --dev : serveur de développement ─────────────────────────────────────────
if [[ "$MODE" == "dev" ]]; then
  step "Serveur de développement"
  if [[ ! -d "$APP_DIR/venv" ]]; then
    python3 -m venv "$APP_DIR/venv"
  fi
  source "$APP_DIR/venv/bin/activate"
  pip install -r "$APP_DIR/requirements.txt" -q

  if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
    info "Variables chargées depuis .env"
  else
    export SECRET_KEY="dev-$(python3 -c 'import secrets;print(secrets.token_hex(16))')"
    export AUTH_ENABLED="false"
    warn "Pas de .env → authentification désactivée, SECRET_KEY temporaire."
  fi

  info "http://localhost:5000"
  python3 "$APP_DIR/app.py"
  exit 0
fi

# ── --restart ────────────────────────────────────────────────────────────────
if [[ "$MODE" == "restart" ]]; then
  sudo systemctl restart "$SERVICE_NAME"
  success "Service $SERVICE_NAME redémarré."
  exit 0
fi

# ── --update : dépendances + restart ─────────────────────────────────────────
if [[ "$MODE" == "update" ]]; then
  step "Mise à jour"
  if [[ ! -d "$APP_DIR/venv" ]]; then
    python3 -m venv "$APP_DIR/venv"
  fi
  "$APP_DIR/venv/bin/pip" install --upgrade pip -q
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
  "$APP_DIR/venv/bin/pip" install gunicorn -q
  success "Dépendances à jour."
  sudo systemctl restart "$SERVICE_NAME"
  sleep 1
  if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    success "Service $SERVICE_NAME redémarré."
  else
    err "Le service n'a pas démarré. Vérifiez : journalctl -u $SERVICE_NAME -n 30"
  fi
  exit 0
fi

# ── Fonction tunnel (réutilisée par --tunnel et full) ────────────────────────
setup_tunnel() {
  step "Cloudflare Tunnel (accès public HTTPS)"

  if ! command -v cloudflared &>/dev/null; then
    info "Installation de cloudflared…"
    ARCH="$(uname -m)"
    case "$ARCH" in
      x86_64)  CF_ARCH="amd64" ;;
      aarch64) CF_ARCH="arm64" ;;
      armv7l)  CF_ARCH="arm"   ;;
      *)       err "Architecture non supportée : $ARCH" ;;
    esac
    curl -L --silent --output /tmp/cloudflared.deb \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}.deb"
    sudo dpkg -i /tmp/cloudflared.deb && rm -f /tmp/cloudflared.deb
    success "cloudflared installé."
  else
    info "cloudflared : $(cloudflared --version 2>&1 | head -1)"
  fi

  if [[ -f "$HOME/.cloudflared/cert.pem" ]]; then
    warn "Certificat Cloudflare déjà présent : login ignoré."
  else
    echo ""
    echo -e "${YELLOW}  ÉTAPE MANUELLE — Authentification Cloudflare${NC}"
    echo "  Un lien s'ouvrira dans votre navigateur."
    read -rp "  Appuyez sur Entrée pour continuer…" _
    cloudflared tunnel login
  fi

  TUNNEL_NAME="ensform"
  if cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    warn "Tunnel '$TUNNEL_NAME' existant — réutilisé."
  else
    cloudflared tunnel create "$TUNNEL_NAME"
    success "Tunnel '$TUNNEL_NAME' créé."
  fi

  TUNNEL_UUID="$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')"
  info "UUID : $TUNNEL_UUID"

  CF_CONFIG_DIR="$HOME/.cloudflared"
  mkdir -p "$CF_CONFIG_DIR"
  cat > "$CF_CONFIG_DIR/config.yml" <<EOF
tunnel: $TUNNEL_UUID
credentials-file: $CF_CONFIG_DIR/${TUNNEL_UUID}.json

ingress:
  - service: http://localhost:80
EOF
  success "config.yml cloudflared écrit."

  if [[ ! -f /etc/systemd/system/cloudflared.service ]]; then
    sudo cloudflared service install
  fi
  sudo systemctl enable cloudflared

  sudo mkdir -p /etc/systemd/system/cloudflared.service.d
  sudo tee /etc/systemd/system/cloudflared.service.d/no-watchdog.conf > /dev/null <<'WDOG'
[Service]
WatchdogSec=0
WDOG
  sudo systemctl daemon-reload
  sudo systemctl restart cloudflared
  sleep 2

  if sudo systemctl is-active --quiet cloudflared; then
    success "Tunnel Cloudflare actif."
  else
    warn "cloudflared n'a pas démarré. Vérifiez : journalctl -u cloudflared -n 30"
  fi
}

# ── --tunnel : configuration Cloudflare uniquement ───────────────────────────
if [[ "$MODE" == "tunnel" ]]; then
  setup_tunnel
  exit 0
fi

# ═════════════════════════════════════════════════════════════════════════════
# MODE FULL : installation complète
# ═════════════════════════════════════════════════════════════════════════════

# ── 1. Dépendances système ───────────────────────────────────────────────────
step "1. Dépendances système"
sudo apt-get update -q
sudo apt-get install -y nginx graphviz sqlite3 curl python3-venv 2>/dev/null
success "Paquets installés."

# ── 2. Python venv + Gunicorn ────────────────────────────────────────────────
step "2. Python venv + Gunicorn"
if [[ ! -d "$APP_DIR/venv" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
"$APP_DIR/venv/bin/pip" install gunicorn -q
success "Dépendances Python + Gunicorn prêts."

# ── 3. SMTP Brevo ────────────────────────────────────────────────────────────
step "3. Relay SMTP (Brevo)"

BREVO_USER="" ; BREVO_PASS="" ; MAIL_FROM_VAL="noreply@ensform.org"
if [[ -f "$ENV_FILE" ]]; then
  BREVO_USER="$(grep '^MAIL_USERNAME=' "$ENV_FILE" | cut -d= -f2- || true)"
  BREVO_PASS="$(grep '^MAIL_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
  _FROM="$(grep '^MAIL_FROM=' "$ENV_FILE" | cut -d= -f2- || true)"
  [[ -n "$_FROM" ]] && MAIL_FROM_VAL="$_FROM"
fi

if [[ -n "$BREVO_USER" && -n "$BREVO_PASS" ]]; then
  info "Identifiants Brevo lus depuis .env ($BREVO_USER)."
else
  echo "  Brevo : relay SMTP gratuit (300 mails/jour)."
  echo "  Créez un compte sur https://app.brevo.com → SMTP & API."
  echo ""
  read -rp "  Login SMTP Brevo : " BREVO_USER
  read -rsp "  Clé SMTP Brevo  : " BREVO_PASS ; echo ""
  read -rp "  Adresse expéditeur [$MAIL_FROM_VAL] : " _IN
  [[ -n "$_IN" ]] && MAIL_FROM_VAL="$_IN"
  success "Identifiants Brevo enregistrés."
fi

# ── 4. Fichier .env ──────────────────────────────────────────────────────────
step "4. Configuration (.env)"

WRITE_ENV=true
if [[ -f "$ENV_FILE" ]]; then
  warn "Un fichier .env existe déjà."
  read -rp "  Le conserver ? [O/n] : " KEEP
  [[ "${KEEP:-O}" =~ ^[nN]$ ]] || WRITE_ENV=false
fi

if $WRITE_ENV; then
  EXISTING_KEY=""
  [[ -f "$ENV_FILE" ]] && EXISTING_KEY="$(grep '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)"
  SECRET_KEY="${EXISTING_KEY:-$(python3 -c 'import secrets;print(secrets.token_hex(32))')}"

  # Lire ADMIN_ID et ADMIN_PASSWORD existants
  ADMIN_ID_VAL="" ; ADMIN_PW_VAL=""
  if [[ -f "$ENV_FILE" ]]; then
    ADMIN_ID_VAL="$(grep '^ADMIN_ID=' "$ENV_FILE" | cut -d= -f2- || true)"
    ADMIN_PW_VAL="$(grep '^ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
  fi

  cat > "$ENV_FILE" <<EOF
# ── ENSForm production ──────────────────────────────────────
SECRET_KEY=$SECRET_KEY
AUTH_ENABLED=true
FLASK_ENV=production

# SMTP (relay Brevo)
MAIL_SERVER=smtp-relay.brevo.com
MAIL_PORT=587
MAIL_USERNAME=$BREVO_USER
MAIL_PASSWORD=$BREVO_PASS
MAIL_FROM=$MAIL_FROM_VAL
MAIL_USE_TLS=true
EOF

  if [[ -n "$ADMIN_ID_VAL" ]]; then
    cat >> "$ENV_FILE" <<EOF

# Super-admin
ADMIN_ID=$ADMIN_ID_VAL
ADMIN_PASSWORD=$ADMIN_PW_VAL
EOF
  fi

  chmod 600 "$ENV_FILE"
  success ".env créé (chmod 600)."
fi

# ── 5. Service systemd ──────────────────────────────────────────────────────
step "5. Service systemd (Gunicorn)"

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=ENSForm (Gunicorn)
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/gunicorn \\
    --workers 2 \\
    --timeout 120 \\
    --graceful-timeout 30 \\
    --bind 127.0.0.1:${GUNICORN_PORT} \\
    --access-logfile /var/log/${SERVICE_NAME}_access.log \\
    --error-logfile /var/log/${SERVICE_NAME}_error.log \\
    app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo touch /var/log/${SERVICE_NAME}_access.log /var/log/${SERVICE_NAME}_error.log
sudo chown "$APP_USER":"$APP_USER" /var/log/${SERVICE_NAME}_access.log /var/log/${SERVICE_NAME}_error.log

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 2

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
  success "Service $SERVICE_NAME actif."
else
  err "Le service n'a pas démarré. Vérifiez : journalctl -u $SERVICE_NAME -n 30"
fi

# ── 6. Nginx ─────────────────────────────────────────────────────────────────
step "6. Nginx (reverse proxy)"

sudo tee /etc/nginx/sites-available/${SERVICE_NAME} > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    location /static/ {
        alias $APP_DIR/static/;
        expires 7d;
        add_header Cache-Control "public";
    }

    client_max_body_size 10M;

    location /api/ {
        proxy_pass         http://127.0.0.1:${GUNICORN_PORT};
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_send_timeout    130s;
        proxy_read_timeout    130s;
    }

    location / {
        proxy_pass         http://127.0.0.1:${GUNICORN_PORT};
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 90s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/${SERVICE_NAME} /etc/nginx/sites-enabled/${SERVICE_NAME}
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl enable nginx && sudo systemctl reload nginx
success "Nginx configuré."

# ── 7. Tunnel Cloudflare ─────────────────────────────────────────────────────
setup_tunnel

# ── 8. Résumé ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
success "Installation terminée !"
echo ""
echo "  Accès local  : http://localhost/admin"
echo "  Accès public : https://ensform.org"
echo ""
echo "  Commandes utiles :"
echo "    ./deploy.sh --restart         Redémarrer le service"
echo "    ./deploy.sh --update          Mettre à jour + redémarrer"
echo "    ./deploy.sh --dev             Serveur de dev local"
echo "    ./deploy.sh --tunnel          Reconfigurer le tunnel"
echo "    ./deploy.sh --remote          Déployer vers RPi/serveur"
echo "    ./deploy.sh --remote --update Mise à jour distante"
echo ""
echo "  Logs :"
echo "    journalctl -u $SERVICE_NAME -f"
echo "    journalctl -u cloudflared -f"
echo "═══════════════════════════════════════════════════════════════"
