#!/bin/bash
set -euo pipefail

##### INSTRUCTION
#
# Verifie que la derniere sauvegarde est REELLEMENT restaurable.
# Tourne DANS le conteneur. Lance par :  make check
#
#   1. Une archive recente existe-t-elle ? (sinon : le cron est mort)
#   2. Contient-elle la base ?
#   3. La base est-elle exploitable ? Elle est extraite dans un dossier
#      temporaire, puis passee au PRAGMA integrity_check COMPLET (index
#      compris) : plus strict que le quick_check fait a chaque sauvegarde.
#
# Signale aussi une archive de secours KO-* plus recente que la derniere bonne
# archive : la base vivante etait corrompue au dernier passage.
#
# Sort en code non nul si quoi que ce soit cloche : branchable en monitoring.
# AGE_MAX_HEURES (defaut 1) : age max de la derniere archive.
#####

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
# L'extraction d'une base de plusieurs centaines de Mo peut etre longue.
# Avant commun.sh, qui pose sinon 1800 s.
BORG_TIMEOUT="${BORG_TIMEOUT:-3600}"
# shellcheck source=commun.sh
. "$SCRIPT_DIR/commun.sh"

AGE_MAX_HEURES="${AGE_MAX_HEURES:-1}"

ok() { echo "  [ok]   $*"; }
ko() { echo "  [KO]   $*" >&2; ERREURS=$((ERREURS + 1)); }
ERREURS=0

echo "[check] depot : $BORG_REPO  (archives $PREFIX_SAVE_DB-*)"
echo


#### 1. FRAICHEUR ####
echo "1. Fraicheur"
DERNIERE="$(borg_ list --glob-archives "$PREFIX_SAVE_DB-*" --last 1 \
  --format '{archive}{TAB}{time:%Y-%m-%d %H:%M:%S}{NL}' "$BORG_REPO")"
[ -n "$DERNIERE" ] || erreur "aucune archive '$PREFIX_SAVE_DB-*' dans le depot."

ARCHIVE="${DERNIERE%%	*}"
DATE_ARCHIVE="${DERNIERE#*	}"
EPOCH_ARCHIVE="$(date -d "$DATE_ARCHIVE" +%s)"
AGE_HEURES=$(( ( $(date +%s) - EPOCH_ARCHIVE ) / 3600 ))

if [ "$AGE_HEURES" -lt "$AGE_MAX_HEURES" ]; then
  ok "derniere archive : $ARCHIVE ($DATE_ARCHIVE)"
else
  ko "derniere archive : $ARCHIVE ($DATE_ARCHIVE), il y a ${AGE_HEURES} h : le cron ne passe plus."
fi

DERNIERE_KO="$(borg_ list --glob-archives "KO-$PREFIX_SAVE_DB-*" --last 1 \
  --format '{archive}{TAB}{time:%Y-%m-%d %H:%M:%S}{NL}' "$BORG_REPO")"
if [ -n "$DERNIERE_KO" ]; then
  ARCHIVE_KO="${DERNIERE_KO%%	*}"
  if [ "$(date -d "${DERNIERE_KO#*	}" +%s)" -gt "$EPOCH_ARCHIVE" ]; then
    ko "archive de secours $ARCHIVE_KO plus recente que la derniere bonne : la base vivante est corrompue."
  else
    echo "  [info] archive de secours ancienne : $ARCHIVE_KO (a supprimer une fois l'incident traite)"
  fi
fi


#### 2. CONTENU ####
echo
echo "2. Contenu de l'archive"
CONTENU="$(borg_ list --format '{size}{TAB}{path}{NL}' "$BORG_REPO::$ARCHIVE")"
# awk plutot que `| grep -q` : pas de SIGPIPE sous pipefail.
CHEMIN_BASE="$(awk -F'\t' '$1 > 0 && $2 ~ /\/snapshot\/db\.sqlite3$/ {print $2; exit}' <<< "$CONTENU")"
if [ -n "$CHEMIN_BASE" ]; then
  TAILLE="$(awk -F'\t' -v p="$CHEMIN_BASE" '$2 == p {print $1}' <<< "$CONTENU")"
  ok "base presente : $CHEMIN_BASE ($((TAILLE / 1048576)) Mo)"
else
  ko "aucune base (snapshot/db.sqlite3 non vide) dans l'archive."
fi


#### 3. EXPLOITABLE ? ####
echo
echo "3. La base est-elle exploitable ?"
if [ -n "$CHEMIN_BASE" ]; then
  umask 077
  DOSSIER_EXTRACTION="$(mktemp -d)"
  trap 'rm -rf "$DOSSIER_EXTRACTION"' EXIT

  LIBRE="$(( $(df -Pk "$DOSSIER_EXTRACTION" | awk 'NR == 2 {print $4}') * 1024 ))"
  if [ "$LIBRE" -le $(( TAILLE * 12 / 10 )) ]; then
    ko "place insuffisante dans $DOSSIER_EXTRACTION pour extraire la base ($((LIBRE / 1048576)) Mo libres)."
  else
    (cd "$DOSSIER_EXTRACTION" && borg_ extract "$BORG_REPO::$ARCHIVE" "$CHEMIN_BASE")
    if nice -n 10 python3 -I "$SCRIPT_DIR/verifier_sqlite.py" "$DOSSIER_EXTRACTION/$CHEMIN_BASE" integrity; then
      ok "base extraite et integre (integrity_check complet)"
    else
      ko "base ILLISIBLE ou CORROMPUE : cette sauvegarde n'est pas restaurable."
    fi
  fi
else
  ko "pas de base a verifier."
fi


#### VERDICT ####
echo
if [ "$ERREURS" -eq 0 ]; then
  echo "[check] La derniere sauvegarde est restaurable."
  exit 0
fi
echo "[check] $ERREURS probleme(s). Cette sauvegarde n'est pas fiable." >&2
exit 1
