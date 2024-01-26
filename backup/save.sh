#!/bin/bash
set -e
# a lancer sur l'hote qui heberge les conteneurs. Verifier que borgbackup soit bien installé !

DATE_NOW=$(date +%Y-%m-%d-%H-%M)
MIGRATION=$(ls /home/fedow/Fedow/fedow_core/migrations | grep -E '^[0]' | tail -1 | head -c 4)

PREFIX=$PREFIX_SAVE_DB-M$MIGRATION

DUMPS_DIRECTORY="/home/fedow/Fedow/backup"

echo $DATE_NOW" on gzip la db en sqlite"
gzip -c /home/fedow/Fedow/database/db.sqlite3 > $DUMPS_DIRECTORY/$PREFIX-$DATE_NOW.db.sqlite3.gz

echo $DATE_NOW" on supprime les vieux dumps sql de plus de 30min"
/usr/bin/find $DUMPS_DIRECTORY -mmin +30 -type f -delete

#### BORG SEND TO SSH ####

export BORG_REPO=$BORG_REPO
export BORG_PASSPHRASE=$BORG_PASSPHRASE
export BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=yes
export BORG_RELOCATED_REPO_ACCESS_IS_OK=yes

echo $DATE_NOW" on cree l'archive borg "
/usr/bin/borg create -vs --compression lz4 \
  $BORG_REPO::$PREFIX-$DATE_NOW \
  $DUMPS_DIRECTORY

/usr/bin/borg prune -v --list --keep-within=3d --keep-daily=7 --keep-weekly=4 --keep-monthly=-1 --keep-yearly=-1 $BORG_REPO
