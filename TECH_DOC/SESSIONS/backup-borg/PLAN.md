# Sauvegarde borg de Fedow — refonte de `backup/save.sh`

Date : 2026-11-11
Statut : codé et testé en local. Relu par un agent avant et après le code.
Les écarts par rapport à ce plan (après relecture) sont listés à la fin.

## Constat (prod, 2026-11-11)

- Le backup échoue depuis le 2026-11-08 20:00 :
  `Failed to create/acquire the lock /home/borgwarehouse/repos/c1542186/lock.exclusive (timeout)`.
  Cause : BorgWarehouse (BWH) a redémarré à 20:00:48, pendant un `borg create`
  commencé à 20:00:22. Le verrou est resté. Docker a donné une nouvelle MAC au
  conteneur ; or borg forme son `host_id` avec `hostname@MAC`. Il ne reconnaît
  plus son propre verrou, ne peut donc pas prouver que le PID est mort, et le
  garde indéfiniment. Seul ce dépôt est touché (les autres n'écrivaient pas).
  Correctif côté BWH (dépôt `borgwarehouse`, hors de ce chantier) : fixer
  `mac_address` dans le compose.
- Le dépôt pèse **340 Go** pour une base SQLite de **668 Mo**. Deux défauts de
  `save.sh` :
  1. `gzip -c db.sqlite3` : un flux gzip change entièrement dès qu'un octet
     change en amont. Borg ne déduplique rien : chaque passage stocke
     ~156 Mo neufs. Avec un cron toutes les ~15 min, ~15 Go par jour.
  2. Jamais de `borg compact`. Depuis borg 1.2 (prod : 1.4.0 des deux côtés),
     `prune` ne libère aucun espace disque sans `compact`.
- Troisième défaut, le plus grave pour la restauration : la base est en
  **WAL** (`start.sh`). `gzip -c db.sqlite3` copie le fichier principal sans
  le `-wal`, et sans aucune cohérence transactionnelle. Les transactions
  validées mais pas encore « checkpointées » sont absentes, et la copie peut
  être incohérente. Aucune sauvegarde actuelle n'est garantie restaurable.

## Contraintes

- Fedow est très utilisé : la sauvegarde ne doit **pas bloquer les écritures**.
- Ceinture et bretelles : vérifier la copie **avant** de l'archiver, et pouvoir
  vérifier une archive après coup (`make check`).
- Ne pas casser ce qui tourne en prod :
  - cron hôte : `docker exec fedow_django /home/fedow/Fedow/backup/save.sh` ;
  - variables lues dans l'environnement du conteneur (`.env` de la stack via
    `env_file`) : `PREFIX_SAVE_DB`, `BORG_REPO`, `BORG_PASSPHRASE` ;
  - clé SSH : `./ssh` monté en `/home/fedow/.ssh` (clé et `known_hosts` par
    défaut de l'utilisateur `fedow`) ;
  - noms d'archives : `<PREFIX_SAVE_DB>-M<migration>-<date>` ;
  - rétention actuelle : `--keep-within=1d --keep-daily=7 --keep-weekly=4
    --keep-monthly=-1 --keep-yearly=-1` (conservée telle quelle).
- Conventions du kit `borgwarehouse/scripts` (et Ghost, Nextcloud) :
  `set -euo pipefail`, `flock`, `borg_tolerant` (code 1 toléré), `prune
  --glob-archives`, `compact`, `check_backup.sh` qui teste l'exploitabilité,
  Makefile « table des matières », here-strings au lieu de `| grep -q`
  (piège SIGPIPE du changelog Nextcloud).

## Choix techniques

### 1. Le snapshot : API Online Backup de Python, en UNE seule étape

`sqlite3.Connection.backup(dest, pages=-1)` (Python 3.10, SQLite 3.46 dans
l'image).

- Une seule étape = une seule transaction de lecture : copie cohérente, WAL
  compris.
- En WAL, un lecteur ne bloque pas les écrivains. Fedow continue d'écrire
  pendant la copie. Seul effet : le checkpoint ne peut pas recycler le WAL
  pendant ces quelques secondes, le `-wal` grossit un peu puis se résorbe.
- **Pourquoi pas `sqlite3 .backup` (CLI, utilisé par le kit)** : le CLI copie
  par pas de 100 pages et relâche le verrou entre deux pas. Si une autre
  connexion écrit entre deux pas, l'API **recommence la copie depuis le
  début**. Sur une base de 668 Mo très sollicitée, la copie peut ne jamais
  finir.
- **Pourquoi pas `VACUUM INTO`** : cohérent aussi, mais il reconstruit la base
  page par page dans un ordre nouveau. Le backup, lui, garde les pages à la
  même position que la source : c'est ce qui permet la déduplication fine
  ci-dessous.
- Garde-fou : si la base n'est pas en WAL, avertissement (la lecture
  bloquerait alors les écritures le temps de la copie). On sauvegarde quand
  même.
- Écrit dans `snapshot/db.sqlite3.tmp`, renommé en `snapshot/db.sqlite3`
  seulement après vérification. Le dernier snapshot local est donc toujours un
  snapshot vérifié.

### 2. Vérification AVANT archivage

Sur la copie (jamais sur la base vivante), ouverte en lecture seule
`immutable=1` (aucun fichier `-wal`/`-shm` créé, aucun octet modifié) :

- `PRAGMA integrity_check` doit renvoyer exactement `ok` ;
- la table `django_migrations` doit contenir des lignes.

Échec : on n'archive pas, code de sortie non nul, l'ancien snapshot reste.

### 3. Borg

- `borg create --compression zstd,9` (valeur du kit SQLite). Seuls les blocs
  nouveaux sont compressés.
- `--chunker-params fixed,65536` : SQLite écrit des pages de 4 Kio à position
  fixe, et le snapshot préserve ces positions. Avec le découpage par défaut
  (buzhash, ~2 Mio en moyenne), chaque page modifiée fait réécrire un bloc de
  ~2 Mio. Avec des blocs fixes de 64 Kio (16 pages), elle n'en coûte que 64 Kio.
- `borg prune --glob-archives "$PREFIX_SAVE_DB-*"`, rétention inchangée.
- `borg compact` après chaque prune (rapide en régime normal : il ne réécrit
  que les segments libérés à plus de 10 %).
- `--lock-wait 120` : une lecture concurrente (`make check`, `make list`) ne
  fait plus échouer le cron au bout de 1 s.
- Sur erreur borg, message qui rappelle la procédure du verrou orphelin
  (vérifier qu'aucun borg ne tourne, puis `borg break-lock`). **Jamais de
  `break-lock` automatique.**
- `nice` / `ionice -c2 -n7` sur snapshot, vérification et borg : Fedow garde
  la priorité CPU et disque.

### 4. Une seule sauvegarde à la fois

`flock -n` sur `backup/.backup.lock`. Le premier `compact` (340 Go) peut durer
longtemps : les crons qui tombent pendant ce temps sortent proprement en
erreur « déjà en cours », au lieu de s'empiler.

## Fichiers

| Fichier | Changement |
|---|---|
| `backup/save.sh` | Réécrit. Même chemin, mêmes variables, même format de nom d'archive. |
| `backup/check_backup.sh` | Nouveau. Fraîcheur (`AGE_MAX_HEURES`, défaut 1), présence de `db.sqlite3`, extraction dans un dossier temporaire, `integrity_check` + `django_migrations`. Code non nul si KO. |
| `Makefile` | Nouveau, à la racine : `make backup`, `make check`, `make list`, `make info`, via `docker exec fedow_django`. |
| `.gitignore` | `backup/snapshot/`, `backup/.backup.lock`, `backup/dumps/*.gz`. |
| `CHANGELOG.md` | Entrée. |
| `TECH_DOC/SESSIONS/backup-borg/` | Ce plan + procédure de restauration. |

Hors périmètre : correctif MAC de BWH, changement de rétention, migration du
`.env` vers la convention du kit (risque en prod sans bénéfice ici).

## Mise en prod (mainteneur)

1. Arrêter le `borg check` en cours (Ctrl-C). Vérifier qu'aucun borg ne
   tourne, puis `borg break-lock` (voir RESTAURATION.md).
2. Contrôles, avant de déployer :
   - le préfixe ne contient que `[a-zA-Z0-9_-]` (sinon `commun.sh` refuse de
     démarrer) : `docker exec fedow_django printenv PREFIX_SAVE_DB` ;
   - toutes les archives portent ce préfixe, sinon le prune ne les verra plus
     (ne doit rien afficher) :
     `docker exec fedow_django bash -c 'borg list --short "$BORG_REPO" | grep -v "^$PREFIX_SAVE_DB-"'`
3. Déployer : `git pull`. Si `./` est monté dans le conteneur (compose du
   dépôt), pas de rebuild. Vérifier que les scripts sont visibles et que
   `backup/` est inscriptible par `fedow` :
   `docker exec fedow_django bash -c 'ls /home/fedow/Fedow/backup/ && touch /home/fedow/Fedow/backup/.backup.lock && echo ok'`
4. En heure creuse, dans tmux/byobu : **`make compact` d'abord** (sans
   timeout, peut durer des heures). Les crons qui tombent pendant ce temps
   sautent (« déjà en cours »). Lancé après un `make backup`, ce gros compact
   serait coupé au bout de 30 min, et chaque cron recommencerait.
5. Puis `make backup` (première archive au nouveau format), `make check`,
   `make info` : 20 à 30 Go attendus, puis une baisse au fil des prunes.
6. Supprimer les anciens `backup/dumps/*.gz` (622 Mo).
7. Côté BorgWarehouse : fixer `mac_address` dans le compose (verrou orphelin).

## Tests (local, conteneur de dev, dépôt borg jetable)

- Dépôt borg local dans le conteneur, variables passées explicitement (le
  conteneur local n'a ni `BORG_REPO` ni clé SSH).
- Écritures en boucle sur une copie de base pendant le snapshot : aucune
  erreur `database is locked`, snapshot cohérent.
- Deux lancements simultanés : le second sort sur le `flock`.
- Base corrompue : le snapshot est refusé, rien n'est archivé.
- Mesure de la déduplication : deux archives successives après quelques
  écritures, `--stats` doit montrer quelques Mo neufs seulement.
- `check_backup.sh` : OK sur une bonne archive, KO sur une archive sans base.

## Écarts après relecture (2026-11-11)

- Chunker : `fixed,4096` (taille de page) au lieu de `fixed,65536`. Les clés
  UUID4 dispersent les écritures : en blocs de 64 Kio, presque toute la base
  changerait à chaque passage.
- `save.sh` fait un `quick_check` ; l'`integrity_check` complet est dans
  `check_backup.sh`.
- Base vivante corrompue : archivée quand même sous `KO-*` (hors prune), code 3.
- `timeout` autour de borg et du snapshot ; `BORG_RSH` avec `BatchMode` et
  `ServerAlive*`.
- Premier compact : `make compact` (`save.sh --compact`, même `flock`), à part.
- `ionice` retiré, avertissement « pas en WAL » retiré.
- Nom d'archive avec les secondes (un `make backup` dans la minute du cron
  échouait sur « archive already exists »).
- Taille attendue après le premier compact : **20 à 30 Go**, pas « quelques
  Go ». Les archives gzip restent tant que la rétention les garde (toutes les
  mensuelles), puis la taille baisse au fil des prunes.
