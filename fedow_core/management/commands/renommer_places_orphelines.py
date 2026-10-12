"""
Renommer les places des lieux supprimés dans Lespass (places orphelines).
/ Rename the places of the venues deleted in Lespass (orphan places).

LOCALISATION : fedow_core/management/commands/renommer_places_orphelines.py

But : une place ne se supprime pas (fedow_core/admin.py) et son nom est unique
(fedow_core/models.py, Place.name). Quand Lespass supprime un lieu jamais utilisé
(commande Lespass `supprimer_lieux_inactifs`), sa place reste ici avec son nom :
quelqu'un qui recrée un espace du même nom échoue à l'onboarding. Cette commande
libère le nom en y ajoutant un suffixe.
/ A place cannot be deleted and its name is unique: this command frees the name of the
places of deleted venues by adding a suffix.

Méthode (en clair) :
 1. On lit le CSV des traces externes de Lespass (`--traces-externes`), colonne
    `place_fedow` = uuid de la place. Une cellule vide (lieu sans place) est ignorée.
 2. Pour chaque uuid :
      - place introuvable -> signalée (uuid sur la sortie) ;
      - nom qui finit déjà par le suffixe -> sautée (la commande est rejouable) ;
      - sinon nouveau nom = nom + " " + suffixe, tronqué pour tenir dans la longueur
        maximum du nom en gardant le suffixe entier. Si ce nom est déjà pris, un numéro
        est ajouté AVANT le suffixe (le nom finit toujours par le suffixe).
 3. Une seule transaction pour tout. Seul le nom change : ni le portefeuille, ni les
    assets, ni les admins, ni rien d'autre.

À BLANC PAR DÉFAUT : aucune écriture sans --executer.
/ DRY-RUN by default: no write without --executer.

Les anciens et nouveaux noms sont affichés pour l'opérateur.
/ Old and new names are printed for the operator.
"""
import csv
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from fedow_core.models import Place

SUFFIXE_PAR_DEFAUT = "(fermé 2026-10)"
COLONNE_DE_LA_PLACE = "place_fedow"


class Command(BaseCommand):
    help = (
        "Ajoute un suffixe au nom des places des lieux supprimés dans Lespass, lues dans "
        "le CSV des traces externes. À blanc par défaut ; --executer pour écrire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--traces", required=True,
            help="CSV des traces externes de Lespass (colonne place_fedow).",
        )
        parser.add_argument(
            "--suffixe", default=SUFFIXE_PAR_DEFAUT,
            help=f"Suffixe ajouté au nom (défaut : « {SUFFIXE_PAR_DEFAUT} »).",
        )
        parser.add_argument(
            "--executer", action="store_true",
            help="Renomme vraiment. Sans ce flag : à blanc (aucune écriture).",
        )

    def handle(self, *args, **options):
        executer = options["executer"]
        suffixe = options["suffixe"].strip()
        longueur_maximum_du_nom = Place._meta.get_field("name").max_length

        if not suffixe:
            raise CommandError("Le suffixe ne peut pas être vide.")
        if len(suffixe) + 1 >= longueur_maximum_du_nom:
            raise CommandError("Le suffixe est trop long pour le nom d'une place.")

        uuids_des_places = self.lire_les_places_du_csv(options["traces"])

        if not executer:
            self.stdout.write("À BLANC : rien n'est écrit (--executer pour écrire).")

        places_renommees = []
        nombre_de_places_sautees = 0
        uuids_introuvables = []
        noms_donnes_dans_ce_passage = set()

        with db_transaction.atomic():
            for uuid_de_la_place in uuids_des_places:
                place = Place.objects.filter(pk=uuid_de_la_place).first()
                if place is None:
                    uuids_introuvables.append(uuid_de_la_place)
                    continue

                if place.name.endswith(suffixe):
                    nombre_de_places_sautees += 1
                    continue

                nouveau_nom = nom_libre_avec_le_suffixe(
                    place, suffixe, longueur_maximum_du_nom, noms_donnes_dans_ce_passage
                )
                noms_donnes_dans_ce_passage.add(nouveau_nom)
                places_renommees.append((place.name, nouveau_nom))

                # update() : seul le nom change, sans passer par save().
                # / update(): only the name changes, without save().
                if executer:
                    Place.objects.filter(pk=place.pk).update(name=nouveau_nom)

        for ancien_nom, nouveau_nom in places_renommees:
            self.stdout.write(f"  {ancien_nom}  ->  {nouveau_nom}")
        for uuid_introuvable in uuids_introuvables:
            self.stdout.write(f"  place introuvable : {uuid_introuvable}")

        verbe = "renommées" if executer else "à renommer"
        self.stdout.write(f"{len(places_renommees)} places {verbe}")
        self.stdout.write(f"{nombre_de_places_sautees} places sautées (déjà suffixées)")
        self.stdout.write(f"{len(uuids_introuvables)} places introuvables")

    def lire_les_places_du_csv(self, chemin_des_traces):
        """
        Les uuid de la colonne `place_fedow`, sans doublon, dans l'ordre du fichier. Une
        cellule vide est ignorée ; une valeur qui n'est pas un uuid est signalée, puis
        sautée.
        / The place_fedow uuids, deduplicated; empty cells ignored, non-uuid values reported.
        """
        try:
            with open(chemin_des_traces, encoding="utf-8-sig", newline="") as fichier:
                lecteur = csv.DictReader(fichier)
                if COLONNE_DE_LA_PLACE not in (lecteur.fieldnames or []):
                    raise CommandError(
                        f"Colonne « {COLONNE_DE_LA_PLACE} » absente du fichier."
                    )
                valeurs_lues = []
                for ligne in lecteur:
                    valeurs_lues.append((ligne.get(COLONNE_DE_LA_PLACE) or "").strip())
        except OSError as erreur:
            raise CommandError(f"Fichier illisible : {erreur}")

        uuids_des_places = []
        for valeur in valeurs_lues:
            if not valeur:
                continue
            if not est_un_uuid(valeur):
                # Filtrer une place sur un texte qui n'est pas un uuid lèverait une erreur :
                # la valeur est signalée, puis sautée.
                # / A non-uuid text would make the query fail: reported, then skipped.
                self.stdout.write(f"  valeur qui n'est pas un uuid : {valeur}")
                continue
            if valeur not in uuids_des_places:
                uuids_des_places.append(valeur)
        return uuids_des_places


def est_un_uuid(texte):
    """Vrai si le texte est un uuid. / True if the text is a uuid."""
    try:
        uuid.UUID(texte)
    except ValueError:
        return False
    return True


def construire_le_nom(nom_d_origine, suffixe, numero, longueur_maximum_du_nom):
    """
    Nom + (numéro) + suffixe, le nom d'origine tronqué pour que le tout tienne dans la
    longueur maximum. Le suffixe est toujours entier, à la fin.
    / Name + (number) + suffix, the original name truncated to fit; suffix always whole.
    """
    if numero is None:
        fin_du_nom = f" {suffixe}"
    else:
        fin_du_nom = f" {numero} {suffixe}"
    place_pour_le_nom_d_origine = longueur_maximum_du_nom - len(fin_du_nom)
    debut_du_nom = nom_d_origine[:place_pour_le_nom_d_origine].rstrip()
    return debut_du_nom + fin_du_nom


def nom_libre_avec_le_suffixe(place, suffixe, longueur_maximum_du_nom, noms_deja_donnes):
    """
    Le premier nom suffixé libre : ni porté par une autre place, ni déjà donné pendant ce
    passage. Sans numéro d'abord, puis 2, 3…
    / The first free suffixed name: no number first, then 2, 3…
    """
    numero = None
    while True:
        nom_candidat = construire_le_nom(place.name, suffixe, numero, longueur_maximum_du_nom)
        nom_deja_pris = (
            Place.objects.filter(name=nom_candidat).exclude(pk=place.pk).exists()
            or nom_candidat in noms_deja_donnes
        )
        if not nom_deja_pris:
            return nom_candidat
        if numero is None:
            numero = 2
        else:
            numero += 1
