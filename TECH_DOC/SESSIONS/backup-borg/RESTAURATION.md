# Sauvegarde borg de Fedow — exploitation et restauration

Scripts : `backup/` (`save.sh`, `check_backup.sh`, `commun.sh`,
`verifier_sqlite.py`). Commandes : `Makefile` à la racine. Tout tourne **dans**
le conteneur `fedow_django`, avec les variables du `.env` de la stack
(`PREFIX_SAVE_DB`, `BORG_REPO`, `BORG_PASSPHRASE`) et la clé SSH de `./ssh`.

```
make backup    sauvegarde maintenant
make check     la dernière archive est-elle restaurable ? (code non nul sinon)
make list      archives
make info      taille du dépôt
make compact   compactage seul (long la première fois : dans tmux/byobu)
```

## Ce que fait une sauvegarde

1. Snapshot de `database/db.sqlite3` par l'API backup de SQLite, en une étape.
   Il est cohérent (WAL compris) et ne bloque pas les écritures de Fedow.
2. `PRAGMA quick_check` sur le snapshot. S'il est KO, la base vivante est
   sans doute corrompue : le snapshot est archivé sous `KO-<préfixe>-…`, sans
   prune, et le script sort en code 3. Le dernier snapshot sain reste dans
   `backup/snapshot/db.sqlite3`.
3. `borg create` (blocs fixes de 4 Kio, la taille d'une page SQLite), `prune`
   (`--glob-archives "<préfixe>-*"`), `compact`.

`make check` extrait la dernière archive et passe un `integrity_check`
complet.

## Restaurer

Depuis le dossier de la stack, sur l'hôte Fedow. La base vit dans le volume
`fedow_database`, monté en `/home/fedow/Fedow/database`.

1. Choisir l'archive : `make list`.
2. Fedow tourne encore. Extraire la base **dans le volume, sous un autre nom**,
   et la vérifier (remplacer `<archive>`) :
   ```bash
   docker exec fedow_django bash -c '. /home/fedow/Fedow/backup/commun.sh
     cd /home/fedow/Fedow/database && rm -rf restau && mkdir restau && cd restau
     borg extract "$BORG_REPO::<archive>"
     python3 -I /home/fedow/Fedow/backup/verifier_sqlite.py \
       home/fedow/Fedow/backup/snapshot/db.sqlite3 integrity \
     && mv home/fedow/Fedow/backup/snapshot/db.sqlite3 ../db.sqlite3.restaure
     cd .. && rm -rf restau && ls -la'
   ```
   Pour une archive de secours `KO-*`, le fichier extrait est
   `snapshot/db.sqlite3.KO` (et il ne passera pas la vérification).
   Sans borg : `backup/snapshot/db.sqlite3` est la dernière copie vérifiée,
   à copier en `database/db.sqlite3.restaure`.
3. **Arrêter Fedow** : `docker compose stop fedow_django`. Ne jamais remplacer
   la base sous un Fedow qui tourne.
4. Écarter l'ancienne base **avec son `-wal` et son `-shm`**, puis poser la
   base restaurée. Un ancien `-wal` laissé à côté de la base restaurée serait
   rejoué dessus et la corromprait. L'ancienne base est gardée, entière, dans
   `avant-restauration-<date>/` :
   ```bash
   docker compose run --rm --no-deps fedow_django bash -c '
     cd /home/fedow/Fedow/database
     AVANT="avant-restauration-$(date +%Y-%m-%d-%H-%M)"
     mkdir "$AVANT" && mv db.sqlite3 "$AVANT"/
     for f in db.sqlite3-wal db.sqlite3-shm; do [ ! -e "$f" ] || mv "$f" "$AVANT"/; done
     mv db.sqlite3.restaure db.sqlite3 && ls -la . "$AVANT"'
   ```
5. Redémarrer : `docker compose start fedow_django`. La base repart en WAL
   toute seule (l'en-tête le garde, et `start.sh` le reforce).

Le nom d'archive donne la dernière migration de `fedow_core` (`-M0027-`) :
restaurer avec un code au même niveau de migration, ou laisser `migrate`
avancer.

## Verrou orphelin (« Failed to create/acquire the lock »)

Cause connue : BorgWarehouse redémarre pendant une sauvegarde. Borg identifie
l'hôte par `hostname@MAC`, et Docker change la MAC du conteneur au
redémarrage. Borg ne reconnaît plus son verrou et ne le libère jamais.

1. Vérifier qu'aucun borg ne tourne :
   `docker exec fedow_django ps aux | grep -E 'borg|save.sh'` sur l'hôte Fedow,
   `docker exec borgwarehouse ps aux | grep 'borg serve'` sur l'hôte BWH.
2. Seulement alors :
   `docker exec fedow_django bash -c '. /home/fedow/Fedow/backup/commun.sh; borg break-lock "$BORG_REPO"'`

(Toujours `bash -c '. commun.sh; …'`, jamais `. commun.sh` dans un shell
interactif : ses fonctions font `exit` en cas d'erreur et fermeraient la
session.)

Ne jamais automatiser `break-lock` : casser le verrou d'une écriture en cours
corrompt le dépôt. Correctif durable : fixer `mac_address` du conteneur dans
le compose de BorgWarehouse.

## Bon à savoir

- Le snapshot réécrit la base entière à chaque passage (668 Mo toutes les
  15 min, ~64 Go d'écritures disque par jour sur l'hôte Fedow).
- Un `VACUUM` de la base déplace toutes les pages : la sauvegarde suivante
  renvoie la base entière, une fois.
- `~/.cache/borg` n'est pas un volume : après recréation du conteneur, le
  premier passage resynchronise le cache (plus lent, une fois).
- `make backup` sans TTY : Ctrl-C coupe l'affichage, pas la sauvegarde. Elle
  finit seule et garde le `flock` jusque-là. `make compact` (avec TTY, sans
  timeout) s'arrête bien au Ctrl-C ; sinon `docker exec fedow_django pkill -TERM borg`.
- Base vivante corrompue : `save.sh` sort en code 3 après l'archive `KO-*`,
  ou avec le code de borg si cette archive de secours échoue elle-même.
- Les archives `KO-*` ne sont jamais prunées : les supprimer à la main
  (`borg delete`) une fois l'incident traité. `make check` les signale.

## Mesures (tests locaux, 2026-11-11)

Base de test de 224 Mo en WAL, clés UUID :

- un écrivain en boucle pendant la sauvegarde : 0 erreur, latence max 16–31 ms ;
- ~8 600 insertions entre deux archives : 18 Mo neufs (contre 100 % avec
  l'ancien gzip) ;
- sauvegarde complète en ~4 s après la première (12 s) ;
- restauration de la base de dev : 28 tables, comptes identiques.
