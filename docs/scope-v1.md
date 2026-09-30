# Périmètre du premier prototype — version de travail

## Objectif du premier incrément

Obtenir un parcours de démonstration supervisé, reproductible avec des données fictives, où le kinésithérapeute sélectionne un dossier local fictif, choisit un protocole, contrôle la capture, obtient un résultat avec son statut de qualité, revoit la preuve et prépare un brouillon. Un parcours sans LLM doit produire le même ensemble de faits via un gabarit déterministe. La validation du rapport est une action explicite du professionnel distincte de l'approbation d'exercices.

Ce périmètre est une cible de développement, pas une fonctionnalité déjà livrée. Les premières versions ne devront annoncer que les parties effectivement vérifiées.

## Inclus dans le parcours initial

1. Une seule personne, une seule caméra d'ordinateur, une séance active et un protocole à la fois. Contrôle du cadrage, arrêt permanent, gestion du refus ou de la perte de caméra, et isolation entre séances.
2. Un premier protocole complet choisi avec un kinésithérapeute référent parmi les candidats du cahier : flexion active du coude en vue de profil, flexion active du genou dans une position définie, élévation du bras sous une convention explicite, ou lever de chaise pour temps et répétitions. Les autres protocoles suivent seulement après vérification du premier.
3. Repères de pose produits par un moteur interchangeable, contrôle de qualité séparé, géométrie déterministe et rejet des données insuffisantes. Aucun score clinique n'est déduit d'un simple score de confiance du modèle.
4. Données et rapport versionnés : provenance, source (`algorithm`, `manual`, `patient_reported`), unités, côté, statut, motifs de qualité, références de preuve et historique des corrections.
5. Revue du professionnel avec actions distinctes d'acceptation, correction et refus. Export du brouillon clairement marqué et export validé seulement après décision professionnelle.
6. Fonctionnement local sans service externe pendant une séance ; démo synthétique sans dossier patient réel ; voie de repli lorsque le LLM est absent ou en panne.

## Étapes ultérieures

La capture par smartphone via HTTPS et appairage local, le catalogue approuvé d'exercices et ses règles d'admissibilité, l'orchestration et le LLM local, les comparaisons longitudinales, la distribution hors ligne et un pilote encadré ont chacun des critères de validation propres. La 3D, le multicaméra, l'entraînement de modèles et un programme autonome à domicile sont des extensions conditionnelles. Leur présence dans le cahier n'autorise pas à les annoncer comme disponibles.

## Contraintes de départ

- Aucune donnée patient, vidéo réelle, clé privée ou poids de modèle dans le dépôt GitHub ; les captures autorisées seront conservées hors du code selon une politique définie avant collecte.
- La vidéo 2D n'est exploitée que dans un plan de mouvement défini ; un changement de vue, une occlusion critique, un côté ambigu ou une personne différente peuvent entraîner l'abstention.
- Les sorties de l'IA restent des propositions. Les chiffres et statuts affichés sont rendus depuis les objets structurés ; le modèle ne peut ni valider ni inventer une mesure ou un dosage.
- L'architecture React/TypeScript, FastAPI/Pydantic, SQLite, moteur de pose interchangeable et `llama.cpp` constitue une hypothèse de départ à confirmer par prototypes, licences et mesures sur la machine cible.

## Ordre du travail

Le cadrage des exigences, des protocoles, des risques et de la mesure précède l'implémentation de la capture. Puis viennent un seul protocole bout en bout, la qualité et les calculs, la validation de ces indicateurs, la revue sans LLM, les exercices approuvés et enfin la génération locale. Les travaux de sécurité et les tests accompagnent chaque étape.
