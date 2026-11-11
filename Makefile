# Table des matieres de la sauvegarde. La logique vit dans backup/.
# Les scripts tournent DANS le conteneur (utilisateur fedow) : variables du
# .env de la stack, cle SSH de ~/.ssh.
.PHONY: help backup check list info compact

CONTENEUR ?= fedow_django
SCRIPTS := /home/fedow/Fedow/backup

help:
	@echo "Sauvegarde borg de Fedow — cibles disponibles :"
	@echo ""
	@echo "  make backup    lance une sauvegarde maintenant"
	@echo "  make check     verifie que la derniere sauvegarde est restaurable"
	@echo "  make list      liste les archives (y compris les archives de secours KO-*)"
	@echo "  make info      taille du depot (dont la taille reelle, dedupliquee)"
	@echo "  make compact   compacte le depot (le premier peut durer des heures :"
	@echo "                 a lancer dans tmux/byobu ; les sauvegardes sautent pendant ce temps)"
	@echo ""
	@echo "Ctrl-C sur make backup coupe l'affichage, pas la sauvegarde (elle finit seule)."
	@echo "Restaurer : TECH_DOC/SESSIONS/backup-borg/RESTAURATION.md"

backup:
	docker exec $(CONTENEUR) bash $(SCRIPTS)/save.sh

check:
	docker exec $(CONTENEUR) bash $(SCRIPTS)/check_backup.sh

# list et info sourcent commun.sh : memes variables, meme SSH, meme attente
# du verrou que les scripts.
list:
	@docker exec $(CONTENEUR) bash -c '. $(SCRIPTS)/commun.sh; borg_ list "$$BORG_REPO"'

info:
	@docker exec $(CONTENEUR) bash -c '. $(SCRIPTS)/commun.sh; borg_ info "$$BORG_REPO"'

compact:
	docker exec -it $(CONTENEUR) bash $(SCRIPTS)/save.sh --compact
