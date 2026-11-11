#!/bin/bash
set -euo pipefail

##### INSTRUCTION
#
# Sauvegarde de la base SQLite de Fedow vers un depot BorgWarehouse.
# Tourne DANS le conteneur. Lance par le cron de l'hote :
#   docker exec fedow_django /home/fedow/Fedow/backup/save.sh
# ou a la main :  make backup
#
# Principe :
#   1. Snapshot coherent de la base, SANS bloquer Fedow (API backup de SQLite,
#      en une seule etape, voir plus bas).
#   2. Verification du snapshot (PRAGMA quick_check) AVANT de l'archiver.
#   3. borg create -> prune -> compact.
#
# Le snapshot verifie reste dans backup/snapshot/db.sqlite3 : c'est toujours
# la derniere copie saine, utilisable meme sans borg.
#
# Variables (.env de la stack) : voir commun.sh.
# Verifier une archive : make check. Restaurer : TECH_DOC/SESSIONS/backup-borg/
#
# Mode particulier :
#   save.sh --compact   compacte le depot, sans sauvegarder (premier
#                       compactage, qui peut durer des heures : make compact)
#
# / Consistent, non-blocking snapshot of Fedow's SQLite database, checked,
# then archived with borg. See TECH_DOC/SESSIONS/backup-borg/.
#####

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=commun.sh
. "$SCRIPT_DIR/commun.sh"

DB_PATH="${DB_PATH:-$FEDOW_DIR/database/db.sqlite3}"
SNAPSHOT_DIR="$BACKUP_DIR/snapshot"
SNAPSHOT="$SNAPSHOT_DIR/db.sqlite3"
SNAPSHOT_TMP="$SNAPSHOT.tmp"
SNAPSHOT_KO="$SNAPSHOT.KO"

# Le snapshot est une copie complete des portefeuilles, dans un dossier monte
# sur l'hote : lisible par fedow seulement.
umask 077

# Une seule sauvegarde a la fois. Le cron tombe toutes les 15 min : un passage
# lent (ou le premier compact) ne doit pas en empiler d'autres.
exec 9>"$BACKUP_DIR/.backup.lock"
if ! flock -n 9; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') [backup] une sauvegarde (ou un compact) est deja en cours — passage saute." >&2
  exit 1
fi


case "${1:-}" in
  ''|--compact) : ;;
  *) erreur "argument inconnu : $1 (seul --compact est accepte)." ;;
esac


#### MODE COMPACT SEUL ####
if [ "${1:-}" = "--compact" ]; then
  dire "compactage du depot $BORG_REPO (sans limite de duree)"
  BORG_TIMEOUT=0 borg_ compact --progress "$BORG_REPO"
  dire "compactage termine"
  exit 0
fi


#### NOM DE L'ARCHIVE ####
# Numero de la derniere migration de fedow_core (0027_xxx.py -> 0027) : on sait
# a quel code correspond la base de chaque archive.
# Un glob plutot que `ls | grep | tail | head` : pas de tuyau, pas de SIGPIPE
# sous pipefail.
MIGRATIONS=("$FEDOW_DIR"/fedow_core/migrations/0[0-9][0-9][0-9]_*.py)
[ -e "${MIGRATIONS[0]}" ] || erreur "aucune migration trouvee dans $FEDOW_DIR/fedow_core/migrations"
DERNIERE_MIGRATION="${MIGRATIONS[-1]##*/}"
MIGRATION="${DERNIERE_MIGRATION:0:4}"

# Secondes comprises : un `make backup` lance dans la minute du cron ne doit
# pas echouer sur "archive already exists".
DATE_NOW="$(date +%Y-%m-%d-%H-%M-%S)"
ARCHIVE="$PREFIX_SAVE_DB-M$MIGRATION-$DATE_NOW"


#### PREPARATION ####
[ -f "$DB_PATH" ] || erreur "base introuvable : $DB_PATH"
mkdir -p "$SNAPSHOT_DIR"

# Un .tmp laisse par un passage interrompu : on repart de zero.
trap 'rm -f "$SNAPSHOT_TMP" "$SNAPSHOT_TMP-journal" "$SNAPSHOT_KO"' EXIT
rm -f "$SNAPSHOT_TMP" "$SNAPSHOT_TMP-journal" "$SNAPSHOT_KO"

# Place : une base entiere (+20 %) a cote du snapshot precedent.
TAILLE_DB="$(stat -c %s "$DB_PATH")"
LIBRE="$(( $(df -Pk "$SNAPSHOT_DIR" | awk 'NR == 2 {print $4}') * 1024 ))"
[ "$LIBRE" -gt $(( TAILLE_DB * 12 / 10 )) ] \
  || erreur "place insuffisante dans $SNAPSHOT_DIR : $((LIBRE / 1048576)) Mo libres, base de $((TAILLE_DB / 1048576)) Mo."


#### 1. SNAPSHOT ####
# API Online Backup de SQLite, en UNE seule etape (pages=-1) :
#   - une seule transaction de lecture : copie coherente, WAL compris ;
#   - en WAL, un lecteur ne bloque pas les ecrivains : Fedow continue
#     d'ecrire pendant la copie (le -wal grossit un peu, puis se resorbe).
# Surtout PAS `sqlite3 .backup` (le CLI) : il copie par pas de 100 pages et
# repart de ZERO a chaque ecriture concurrente. Sur une base tres sollicitee,
# sa duree n'est pas bornee.
# Pas de VACUUM INTO non plus : l'API backup garde chaque page a la meme
# position que dans la source, ce qui permet la deduplication fine de borg.
# timeout : Python reessaie sans fin sur SQLITE_BUSY.
dire "snapshot de $DB_PATH ($((TAILLE_DB / 1048576)) Mo)"
RC=0
nice -n 10 timeout 900 python3 -I - "$DB_PATH" "$SNAPSHOT_TMP" <<'PYTHON' || RC=$?
import sqlite3
import sys

chemin_source, chemin_destination = sys.argv[1], sys.argv[2]
connexion_source = sqlite3.connect(chemin_source, timeout=30)
connexion_destination = sqlite3.connect(chemin_destination)
connexion_source.backup(connexion_destination, pages=-1)
connexion_destination.close()
connexion_source.close()
PYTHON
[ "$RC" -ne 124 ] || erreur "snapshot interrompu apres 900 s (base verrouillee ?). Rien n'est archive."
[ "$RC" -eq 0 ] || erreur "snapshot impossible (code $RC). Rien n'est archive."
[ -s "$SNAPSHOT_TMP" ] || erreur "snapshot vide. Rien n'est archive."


#### 2. VERIFICATION AVANT ARCHIVAGE ####
dire "verification du snapshot"
RC=0
nice -n 10 python3 -I "$SCRIPT_DIR/verifier_sqlite.py" "$SNAPSHOT_TMP" quick || RC=$?

# Code 3 = la base est illisible. Tout autre echec (script absent, Python
# plante) n'est PAS une corruption : erreur simple, sans archive KO.
if [ "$RC" -ne 0 ] && [ "$RC" -ne 3 ]; then
  erreur "verification impossible (code $RC). Rien n'est archive."
fi

if [ "$RC" -eq 3 ]; then
  # Le snapshot est une copie fidele : s'il est corrompu, c'est la base
  # VIVANTE qui l'est. On l'archive quand meme, sous un nom que le prune ne
  # touche jamais (KO-*) : refuser d'archiver ferait perdre tout ce qui suit la
  # derniere bonne archive. Le dernier snapshot sain, lui, reste en place.
  mv -f "$SNAPSHOT_TMP" "$SNAPSHOT_KO"
  echo "[backup] ALERTE : snapshot NON EXPLOITABLE (code $RC). La base vivante est sans doute corrompue." >&2
  echo "[backup] Archive de secours : KO-$ARCHIVE. Pas de prune ni de compact." >&2
  borg_ create --stats --compression zstd,9 --chunker-params fixed,4096 \
    "$BORG_REPO::KO-$ARCHIVE" "$SNAPSHOT_KO"
  exit 3
fi

# Renommage atomique : snapshot/db.sqlite3 est toujours un snapshot verifie.
mv -f "$SNAPSHOT_TMP" "$SNAPSHOT"


#### 3. BORG ####
# --chunker-params fixed,4096 : des blocs de la taille d'une page SQLite.
# Le snapshot garde les pages a leur position : une page modifiee ne coute que
# 4 Kio dans l'archive. Avec le decoupage par defaut (~2 Mio) — et les cles
# UUID de Fedow, qui dispersent les ecritures — presque toute la base
# repartirait a chaque passage.
# Un VACUUM de la base deplace toutes les pages : un envoi complet, une fois.
dire "archive borg : $ARCHIVE"
borg_ create --stats --compression zstd,9 --chunker-params fixed,4096 \
  "$BORG_REPO::$ARCHIVE" "$SNAPSHOT"

# --glob-archives : ne touche QUE les archives de Fedow (ni KO-*, ni celles
# d'une autre sauvegarde partageant le depot).
dire "prune"
borg_ prune --list --glob-archives "$PREFIX_SAVE_DB-*" \
  --keep-within=1d --keep-daily=7 --keep-weekly=4 --keep-monthly=-1 --keep-yearly=-1 \
  "$BORG_REPO"

# Depuis borg 1.2, prune ne libere AUCUN espace disque sans compact. Rapide en
# regime normal : seuls les segments liberes a plus de 10 % sont reecrits.
dire "compact"
borg_ compact "$BORG_REPO"

dire "termine"
