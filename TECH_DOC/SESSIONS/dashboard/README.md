# Chantier « dashboard » — Fedow

Enrichir le tableau de bord Fedow (`fedow_dashboard/`) avec des informations utiles
pour un **admin réseau / coopérative**.

## Contrainte transverse — NON NÉGOCIABLE

**LECTURE SEULE sur la base de données. Aucune écriture, aucune migration.**
On ne travaille que sur le dashboard (affichage + calculs d'agrégation).
Reconfirmer « lecture seule » avant chaque modification de code.

## Contexte technique

- Fedow tourne via le compose Lespass (`../Lespass/docker-compose-laboutik-V1.yml`),
  image figée `tibillet/fedow:latest`, **SQLite**, gunicorn 5 workers (`start.sh`),
  routé Traefik sur `fedow.tibillet.localhost`.
- Le code source est bind-monté (`../Fedow:/home/fedow/Fedow`).
- Statics : volume `../Fedow/www:/www` partagé avec nginx.
- Modifs template/CSS/JS → prises à chaud. Modifs Python → reload gunicorn
  (`docker exec fedow_django pkill -HUP gunicorn`).

## Specs

| Spec | Fichier | Statut |
|------|---------|--------|
| 1 — Corrections & robustesse | `2026-05-24-spec-1-corrections-robustesse.md` | Validé, prêt |
| 2 — Vue réseau globale | `2026-05-24-spec-2-vue-reseau-globale.md` | Validé |
| 3 — Simulateur de fonte | `2026-05-24-spec-3-simulateur-fonte.md` | Validé |

Ordre d'implémentation : 1 → 2 → 3 (la Spec 1 produit la donnée réutilisée par la Spec 3).
