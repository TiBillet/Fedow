"""
Verifie qu'une COPIE de base SQLite est exploitable.
/ Checks that a COPY of an SQLite database is usable.

Usage : python3 -I verifier_sqlite.py <fichier> <quick|integrity>

  quick      PRAGMA quick_check      (save.sh, a chaque passage : plus rapide)
  integrity  PRAGMA integrity_check  (check_backup.sh : complet, index compris)

La copie est ouverte en `immutable=1` : SQLite ne cree ni -wal ni -shm et ne
modifie aucun octet du fichier. Un simple `mode=ro` ne suffit pas sur une base
marquee WAL (ce que garde la copie faite par l'API backup).
Ne JAMAIS lancer ce script sur la base vivante.

Codes de sortie : 0 ok, 3 base non exploitable, 2 erreur d'usage.
"""

import pathlib
import sqlite3
import sys


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ("quick", "integrity"):
        print(__doc__, file=sys.stderr)
        return 2

    chemin_fichier = pathlib.Path(sys.argv[1]).resolve()
    if not chemin_fichier.is_file():
        print(f"[verif] fichier introuvable : {chemin_fichier}", file=sys.stderr)
        return 3

    pragma = "quick_check" if sys.argv[2] == "quick" else "integrity_check"
    uri_lecture_seule = chemin_fichier.as_uri() + "?immutable=1"

    try:
        connexion = sqlite3.connect(uri_lecture_seule, uri=True)
        lignes_resultat = [ligne[0] for ligne in connexion.execute(f"PRAGMA {pragma}")]
        if lignes_resultat != ["ok"]:
            # Une ligne de resultat peut contenir des centaines d'erreurs : on
            # n'en montre que le debut, le journal du cron reste lisible.
            print(f"[verif] PRAGMA {pragma} KO :", file=sys.stderr)
            for ligne in "\n".join(lignes_resultat).splitlines()[:20]:
                print(f"         {ligne}", file=sys.stderr)
            return 3

        # Une base vide (ou pas celle de Fedow) passerait integrity_check.
        nombre_migrations = connexion.execute("SELECT count(*) FROM django_migrations").fetchone()[0]
        if nombre_migrations == 0:
            print("[verif] table django_migrations vide : ce n'est pas une base Fedow.", file=sys.stderr)
            return 3
        connexion.close()
    except sqlite3.DatabaseError as exception:
        print(f"[verif] base illisible : {exception}", file=sys.stderr)
        return 3

    print(f"[verif] PRAGMA {pragma} ok, {nombre_migrations} migrations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
