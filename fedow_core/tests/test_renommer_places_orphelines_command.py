"""
Commande de renommage des places orphelines (lieux supprimés dans Lespass).
/ Renaming command for orphan places (venues deleted in Lespass).

LOCALISATION : fedow_core/tests/test_renommer_places_orphelines_command.py

POURQUOI CE FICHIER :
Une place Fedow ne se supprime pas, et son nom est unique. Quand Lespass supprime un lieu
jamais utilisé (commande `supprimer_lieux_inactifs`), sa place reste ici avec son nom :
quelqu'un qui recrée un espace du même nom échoue à l'onboarding. La commande
`renommer_places_orphelines` lit le CSV des traces externes de Lespass (colonne
`place_fedow` = uuid de la place) et ajoute un suffixe au nom de chaque place.
/ A Fedow place cannot be deleted and its name is unique: the command suffixes the name
of each place listed in Lespass's external traces CSV.

CONTRAT TESTÉ (brief Lespass TECH_DOC/SESSIONS/COMPTABILITE/CHANTIER-05-briefs/05-R-N-bis.md)
- `--traces <chemin.csv>` : le CSV de Lespass ; `--suffixe` (défaut « (fermé 2026-10) ») ;
  `--executer` (sinon à blanc : rien n'est écrit).
- Nouveau nom = nom + « » + suffixe, tronqué pour tenir dans `max_length` en gardant le
  suffixe entier, et unique (un numéro est ajouté AVANT le suffixe si le nom est pris :
  le nom finit toujours par le suffixe, donc la commande reste rejouable).
- Place introuvable : signalée (son uuid sur la sortie), rien ne casse. Nom déjà
  suffixé : sautée. Une cellule `place_fedow` vide (lieu sans place) est ignorée.
- Rien d'autre ne change : portefeuille, description, nombre de places.
/ Contract: options, suffixed and truncated unique name, missing place reported, already
suffixed place skipped, empty cell ignored, nothing else touched.
"""
import csv
import os
import tempfile
from io import StringIO
from uuid import uuid4

from django.core.management import call_command

from fedow_core.models import Place, wallet_creator
from fedow_core.tests.tests import FedowTestCase

SUFFIXE_PAR_DEFAUT = "(fermé 2026-10)"
COLONNES_DES_TRACES = [
    "domaine",
    "stripe_connect",
    "stripe_connect_test",
    "place_fedow",
    "administrateurs",
]


class RenommerPlacesOrphelinesTest(FedowTestCase):

    def setUp(self):
        super().setUp()
        self.dossier_temporaire = tempfile.TemporaryDirectory()
        self.longueur_maximum_du_nom = Place._meta.get_field("name").max_length

    def tearDown(self):
        self.dossier_temporaire.cleanup()
        super().tearDown()

    # ------------------------------------------------------------------
    # Outils / Helpers
    # ------------------------------------------------------------------

    def creer_une_place(self, nom):
        """Une place de test, avec son portefeuille. / A test place with its wallet."""
        return Place.objects.create(name=nom, wallet=wallet_creator())

    def ecrire_les_traces(self, valeurs_de_place_fedow):
        """
        Écrit un CSV au format des traces externes de Lespass, une ligne par valeur de la
        colonne `place_fedow` (uuid en texte, ou texte vide).
        / Writes a CSV like Lespass's external traces, one row per place_fedow value.
        """
        chemin_des_traces = os.path.join(
            self.dossier_temporaire.name, f"traces_{uuid4().hex[:8]}.csv"
        )
        with open(chemin_des_traces, "w", encoding="utf-8", newline="") as fichier:
            ecrivain = csv.writer(fichier)
            ecrivain.writerow(COLONNES_DES_TRACES)
            numero_de_ligne = 0
            for valeur_de_place_fedow in valeurs_de_place_fedow:
                numero_de_ligne += 1
                ecrivain.writerow([
                    f"lieu-{numero_de_ligne}.tibillet.localhost",
                    "",
                    "",
                    valeur_de_place_fedow,
                    "",
                ])
        return chemin_des_traces

    def lancer_la_commande(self, *options):
        """Lance la commande, rend sa sortie. / Runs the command, returns its output."""
        sortie = StringIO()
        call_command("renommer_places_orphelines", *options, stdout=sortie, stderr=sortie)
        return sortie.getvalue()

    def nom_relu(self, place):
        return Place.objects.get(pk=place.pk).name

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_a_blanc_ne_renomme_rien(self):
        place = self.creer_une_place("Lieu fermé à blanc")
        chemin_des_traces = self.ecrire_les_traces([str(place.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces)

        self.assertEqual(self.nom_relu(place), "Lieu fermé à blanc")

    def test_executer_ajoute_le_suffixe_par_defaut(self):
        place = self.creer_une_place("Lieu jamais utilisé")
        chemin_des_traces = self.ecrire_les_traces([str(place.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        self.assertEqual(
            self.nom_relu(place), f"Lieu jamais utilisé {SUFFIXE_PAR_DEFAUT}"
        )

    def test_suffixe_choisi(self):
        place = self.creer_une_place("Lieu au suffixe choisi")
        chemin_des_traces = self.ecrire_les_traces([str(place.pk)])

        self.lancer_la_commande(
            "--traces", chemin_des_traces, "--suffixe", "(fermé)", "--executer"
        )

        self.assertEqual(self.nom_relu(place), "Lieu au suffixe choisi (fermé)")

    def test_rejouee_ne_suffixe_pas_deux_fois(self):
        place = self.creer_une_place("Lieu rejoué")
        chemin_des_traces = self.ecrire_les_traces([str(place.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")
        nom_apres_le_premier_passage = self.nom_relu(place)
        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        self.assertEqual(self.nom_relu(place), nom_apres_le_premier_passage)
        self.assertEqual(
            nom_apres_le_premier_passage, f"Lieu rejoué {SUFFIXE_PAR_DEFAUT}"
        )

    def test_place_introuvable_signalee_sans_erreur(self):
        place = self.creer_une_place("Lieu bien là")
        uuid_introuvable = str(uuid4())
        chemin_des_traces = self.ecrire_les_traces([uuid_introuvable, str(place.pk)])

        sortie = self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        self.assertIn(uuid_introuvable, sortie)
        self.assertEqual(self.nom_relu(place), f"Lieu bien là {SUFFIXE_PAR_DEFAUT}")

    def test_cellule_place_fedow_vide_ignoree(self):
        place = self.creer_une_place("Lieu après une ligne vide")
        chemin_des_traces = self.ecrire_les_traces(["", str(place.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        self.assertEqual(
            self.nom_relu(place), f"Lieu après une ligne vide {SUFFIXE_PAR_DEFAUT}"
        )

    def test_nom_long_tronque_en_gardant_le_suffixe_entier(self):
        nom_le_plus_long_possible = "L" * self.longueur_maximum_du_nom
        place = self.creer_une_place(nom_le_plus_long_possible)
        chemin_des_traces = self.ecrire_les_traces([str(place.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        nouveau_nom = self.nom_relu(place)
        self.assertLessEqual(len(nouveau_nom), self.longueur_maximum_du_nom)
        self.assertTrue(nouveau_nom.endswith(SUFFIXE_PAR_DEFAUT))
        self.assertTrue(nouveau_nom.startswith("L"))

    def test_nom_deja_pris_recoit_un_numero_et_garde_le_suffixe(self):
        place_orpheline = self.creer_une_place("Lieu en double")
        autre_place = self.creer_une_place(f"Lieu en double {SUFFIXE_PAR_DEFAUT}")
        chemin_des_traces = self.ecrire_les_traces([str(place_orpheline.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        nouveau_nom = self.nom_relu(place_orpheline)
        self.assertNotEqual(nouveau_nom, self.nom_relu(autre_place))
        self.assertTrue(nouveau_nom.startswith("Lieu en double"))
        self.assertTrue(nouveau_nom.endswith(SUFFIXE_PAR_DEFAUT))
        self.assertLessEqual(len(nouveau_nom), self.longueur_maximum_du_nom)
        self.assertEqual(
            self.nom_relu(autre_place), f"Lieu en double {SUFFIXE_PAR_DEFAUT}"
        )

    def test_ne_touche_a_rien_d_autre(self):
        place = self.creer_une_place("Lieu à ne pas abîmer")
        Place.objects.filter(pk=place.pk).update(description="Description gardée")
        portefeuille_avant = Place.objects.get(pk=place.pk).wallet_id
        nombre_de_places_avant = Place.objects.count()
        chemin_des_traces = self.ecrire_les_traces([str(place.pk)])

        self.lancer_la_commande("--traces", chemin_des_traces, "--executer")

        place_relue = Place.objects.get(pk=place.pk)
        self.assertEqual(place_relue.wallet_id, portefeuille_avant)
        self.assertEqual(place_relue.description, "Description gardée")
        self.assertEqual(Place.objects.count(), nombre_de_places_avant)
