#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# reset_db.sh  –  Réinitialisation de la base de données
#
# Options :
#   (aucune)          reset complet  : tout supprimer et recréer
#   --accounts-only   reset partiel  : supprimer uniquement les comptes admin
#   --keep-accounts   reset partiel  : supprimer tout SAUF les comptes admin
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="$SCRIPT_DIR/instance/forms.db"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }

MODE="full"
if [[ "${1:-}" == "--accounts-only" ]]; then MODE="accounts"; fi
if [[ "${1:-}" == "--keep-accounts" ]]; then MODE="keep_accounts"; fi

echo ""
echo "════════════════════════════════════════════════"
echo -e "   ${BOLD}Reset base de données — ENSForm${NC}"
echo "════════════════════════════════════════════════"
echo ""

if [[ ! -f "$DB_PATH" ]]; then
  warn "Base de données introuvable : $DB_PATH"
  warn "Elle sera créée automatiquement au prochain démarrage de l'app."
  exit 0
fi

case "$MODE" in
  full)
    echo -e "  Mode        : ${RED}${BOLD}RESET COMPLET${NC}"
    echo    "  Suppression : tous les formulaires, réponses, participants,"
    echo    "                départements et comptes admin"
    ;;
  accounts)
    echo -e "  Mode        : ${YELLOW}${BOLD}COMPTES UNIQUEMENT${NC}"
    echo    "  Suppression : uniquement les comptes admin"
    echo    "  Conservé    : formulaires, réponses, participants"
    ;;
  keep_accounts)
    echo -e "  Mode        : ${YELLOW}${BOLD}TOUT SAUF COMPTES${NC}"
    echo    "  Suppression : formulaires, réponses, participants, départements"
    echo    "  Conservé    : comptes admin"
    ;;
esac

echo ""
read -rp "Confirmer ? [o/N] " CONFIRM
[[ "$CONFIRM" =~ ^[oOyY]$ ]] || { info "Annulé."; exit 0; }
echo ""

# ── Vérifier que l'app n'est pas en cours d'exécution ─────────────────────────
if pgrep -f "python3 app.py" > /dev/null 2>&1; then
  warn "L'application Flask semble tourner. Arrêtez-la d'abord pour éviter"
  warn "les conflits de verrouillage SQLite, puis relancez ce script."
  read -rp "  Continuer quand même ? [o/N] " FORCE
  [[ "$FORCE" =~ ^[oOyY]$ ]] || { info "Annulé."; exit 0; }
fi

# ── Sauvegarde automatique ─────────────────────────────────────────────────────
BACKUP="$DB_PATH.bak_$(date +%Y%m%d_%H%M%S)"
cp "$DB_PATH" "$BACKUP"
success "Sauvegarde créée : $(basename "$BACKUP")"

# ── Opérations SQL ─────────────────────────────────────────────────────────────
info "Opérations sur la base de données…"

case "$MODE" in
  full)
    rm -f "$DB_PATH"
    success "Base de données supprimée."
    info "Elle sera recréée automatiquement au prochain démarrage de l'app."
    ;;

  accounts)
    sqlite3 "$DB_PATH" "DELETE FROM admin_users;"
    success "Table admin_users vidée."
    ;;

  keep_accounts)
    sqlite3 "$DB_PATH" "
      PRAGMA foreign_keys = OFF;
      DELETE FROM answers;
      DELETE FROM responses;
      DELETE FROM group_participants;
      DELETE FROM group_departments;
      DELETE FROM questions;
      DELETE FROM forms;
      PRAGMA foreign_keys = ON;
    "
    success "Formulaires, réponses, participants et départements supprimés."
    success "Comptes admin conservés."
    ;;
esac

echo ""
echo "════════════════════════════════════════════════"
success "Reset terminé."
echo ""
echo "  Sauvegarde  : $(basename "$BACKUP")"
echo "  Pour l'app  : bash start.sh"
if [[ "$MODE" == "full" || "$MODE" == "accounts" ]]; then
  echo "  Inscription : http://localhost:5000/admin/register"
fi
echo "════════════════════════════════════════════════"
echo ""
