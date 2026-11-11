# shellcheck shell=bash
##### INSTRUCTION
#
# Bibliotheque commune aux scripts de sauvegarde (a sourcer, pas a lancer) :
#   . "$(dirname "$0")/commun.sh"
#
# Tout tourne DANS le conteneur fedow_django (utilisateur fedow). Les
# variables viennent du .env de la stack, injecte par `env_file` :
#   PREFIX_SAVE_DB    prefixe des archives (ex. fed_coop)
#   BORG_REPO         adresse ssh:// du depot sur BorgWarehouse
#   BORG_PASSPHRASE   passphrase du depot — AU COFFRE, avec `borg key export`
# La cle SSH est celle de l'utilisateur fedow (./ssh monte en ~/.ssh).
#
# Fournit :
#   dire / erreur   journal horodate
#   borg_           borg avec timeout, attente du verrou, priorite basse
#
# / Shared helpers for the backup scripts (sourced). Runs inside the
# fedow_django container; config comes from the stack's .env.
#####

FEDOW_DIR="${FEDOW_DIR:-/home/fedow/Fedow}"
BACKUP_DIR="$FEDOW_DIR/backup"

dire()   { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
erreur() { echo "$(date '+%Y-%m-%d %H:%M:%S') [backup] ERREUR : $*" >&2; exit 2; }

: "${PREFIX_SAVE_DB:?PREFIX_SAVE_DB absent de l environnement (.env de la stack)}"
: "${BORG_REPO:?BORG_REPO absent de l environnement (.env de la stack)}"
: "${BORG_PASSPHRASE:?BORG_PASSPHRASE absent de l environnement (.env de la stack)}"
# Le prefixe sert de motif au prune (--glob-archives "$PREFIX_SAVE_DB-*") :
# un caractere special le transformerait en joker.
case "$PREFIX_SAVE_DB" in
  *[!a-zA-Z0-9_-]*) erreur "PREFIX_SAVE_DB invalide : lettres, chiffres, - et _ uniquement." ;;
esac

export BORG_REPO BORG_PASSPHRASE
export BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes
export BORG_RELOCATED_REPO_ACCESS_IS_OK=yes

# SSH : la cle par defaut de ~/.ssh (pas de -i, comme avant).
#   BatchMode       echoue tout de suite au lieu d'attendre une saisie
#   ServerAlive*    detecte une connexion morte : sans lui, un SSH fige garde
#                   le verrou pour toujours et tous les crons suivants sautent.
export BORG_RSH="${BORG_RSH:-ssh -oBatchMode=yes -oServerAliveInterval=30 -oServerAliveCountMax=6}"

for outil in borg python3 flock timeout nice; do
  command -v "$outil" >/dev/null || erreur "$outil introuvable dans le PATH."
done

# Duree max d'un appel borg, en secondes (0 = sans limite).
BORG_TIMEOUT="${BORG_TIMEOUT:-1800}"

# borg_ <commande> <args...>
# Codes borg : 0 ok, 1 avertissement (tolere, sauf pour create), >= 2 erreur (on sort).
#   --lock-wait 120 : un `make list` ou `make check` qui tient le verrou ne fait
#                     plus echouer le cron au bout d'une seconde (defaut borg).
#   timeout         : SIGTERM, que borg traite proprement (il rend le verrou).
#                     BORG_TIMEOUT=0 : pas de timeout du tout, pour que Ctrl-C
#                     atteigne borg (timeout le place dans un autre groupe).
#   nice            : Fedow garde la priorite CPU.
#   9>&-            : borg et ssh n'heritent pas du descripteur du flock (un ssh
#                     maitre ControlPersist le garderait apres la fin du script).
borg_() {
  local rc=0
  if [ "$BORG_TIMEOUT" = 0 ]; then
    nice -n 10 borg --lock-wait 120 "$@" 9>&- || rc=$?
  else
    nice -n 10 timeout --kill-after=60 "$BORG_TIMEOUT" borg --lock-wait 120 "$@" 9>&- || rc=$?
  fi
  if [ "$rc" -eq 124 ]; then
    erreur "borg $1 depasse ${BORG_TIMEOUT}s : arrete. Connexion SSH figee ? BorgWarehouse surcharge ?"
  fi
  if [ "$rc" -ge 2 ]; then
    echo "[backup] ERREUR : 'borg $1' a echoue (code $rc)." >&2
    echo "[backup] Si le message dit 'Failed to create/acquire the lock' :" >&2
    echo "         verrou orphelin possible (BorgWarehouse redemarre pendant une sauvegarde)." >&2
    echo "         1. verifier qu'AUCUN borg ne tourne, ici ET dans le conteneur borgwarehouse ;" >&2
    echo "         2. puis seulement : borg break-lock \"\$BORG_REPO\"" >&2
    echo "         Voir TECH_DOC/SESSIONS/backup-borg/RESTAURATION.md" >&2
    exit "$rc"
  fi
  # Pour create, un avertissement peut vouloir dire « fichier source illisible » :
  # une archive SANS la base. Jamais tolere.
  if [ "$rc" -eq 1 ] && [ "$1" = create ]; then
    erreur "borg create : avertissement (code 1), l'archive est peut-etre incomplete. Pas de prune."
  fi
  [ "$rc" -eq 1 ] && echo "[backup] (avertissement borg ignore, code 1 — voir ci-dessus)" >&2
  return 0
}
