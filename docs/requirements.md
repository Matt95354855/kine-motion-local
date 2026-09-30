# Exigences initiales — version de travail

Chaque ligne définit une obligation à vérifier, non une capacité déjà réalisée. Les identifiants relient le code, les tests et les preuves. Les seuils numériques, protocoles activés et décisions cliniques restent à fixer avec le référent concerné avant validation.

| ID | Exigence et justification | Responsable pressenti | Scénario de vérification | Preuve attendue |
| --- | --- | --- | --- | --- |
| `REQ-PURPOSE-001` | Décrire uniquement des indicateurs définis par protocole et préparer un brouillon ; éviter une interprétation libre de la vidéo. | Protocoles, mesure, rapport | Exécuter un cas synthétique du protocole actif. | Résultats étiquetés avec protocole et statut brouillon. |
| `REQ-REVIEW-001` | Le kiné peut accepter, corriger ou refuser chaque résultat et proposition ; sa décision reste nécessaire. | Revue | Présenter une valeur et une suggestion volontairement erronées. | Historique des décisions et version finale liée au réviseur. |
| `REQ-LOCAL-001` | Capture, mesure, catalogue et rédaction fonctionnent sans service externe pendant une séance. | Application, installation | Parcours complet avec Internet bloqué et ressources installées. | Rapport de test réseau et parcours réussi ou échec explicite. |
| `REQ-TRACE-001` | Relier chaque mesure et proposition à la capture, au protocole, aux règles et versions utilisées. | Contrats, persistance | Ouvrir une mesure ancienne après mise à jour du logiciel. | Provenance et versions historiques conservées. |
| `REQ-SCOPE-001` | Le premier parcours suit une personne, une caméra et un protocole actif à la fois ; prévenir les mélanges de séances. | Séance, capture | Changer de dossier pendant ou juste après une capture. | Flux et résultats de l'ancienne séance refusés pour le nouveau dossier. |
| `REQ-CAPTURE-001` | Permettre cadrage, démarrage, arrêt immédiat et gestion des erreurs caméra sans activer le microphone. | Capture | Refus de permission, perte de caméra et arrêt manuel. | États affichés, pistes arrêtées et audio absent. |
| `REQ-PROTOCOL-001` | Chaque indicateur possède vue, posture, côté, repères, formule, unités et version explicites. | Protocoles | Charger une fiche incomplète puis une fiche valide. | Fiche invalide rejetée ; fiche valide affichable et versionnée. |
| `REQ-MEASURE-001` | Séparer angle apparent, excursion observée, durée et répétitions de toute interprétation anatomique ou clinique. | Géométrie, rapport | Comparer deux indicateurs d'un même essai. | Conventions et libellés propres à chaque indicateur. |
| `REQ-QUALITY-001` | Marquer les résultats `valid`, `limited`, `rejected` ou `not_performed` et expliquer les limites. | Qualité | Masquer un repère critique, déplacer la caméra et interrompre un essai. | Motifs structurés ; valeur `null` si rejetée. |
| `REQ-ABSTAIN-001` | Aucun défaut de capture ne devient silencieusement une valeur exploitable ou une suggestion. | Qualité, règles | Rejouer un clip hors plan ou insuffisant. | Abstention visible et absence de candidat déclenché par cette mesure. |
| `REQ-SOURCE-001` | Distinguer résultat algorithmique, saisie professionnelle et déclaration du patient ; ne pas assimiler inconnu à zéro. | Contrats, revue | Saisir douleur non renseignée et amplitude passive manuelle. | Sources et états distincts à l'écran et à l'export. |
| `REQ-REPORT-001` | Les chiffres, unités, côtés et statuts du rapport proviennent des objets structurés ; le LLM ne les fixe pas. | Rendu, validateur | Fournir un texte généré contenant un chiffre contradictoire. | Sortie rejetée ou chiffre rendu depuis la mesure vérifiée. |
| `REQ-FALLBACK-001` | Le parcours de mesures et de compte rendu reste disponible quand le LLM est arrêté. | Rapport, orchestration | Arrêter le service LLM avant la génération. | Brouillon déterministe fidèle aux mesures, sans perte de séance. |
| `REQ-VALIDATE-001` | Seul un professionnel identifié valide un rapport ; toute modification déterminante crée une nouvelle version à revoir. | Revue, persistance | Modifier une mesure après validation. | Rapport antérieur préservé, nouveau statut `review_required`. |
| `REQ-EXERCISE-001` | Une suggestion ne vient que d'une fiche active approuvée et passe les exclusions et prérequis avant classement. | Catalogue, règles | Demander un exercice retiré ou incompatible. | Proposition refusée avec raison, y compris si demandée par le LLM. |
| `REQ-EXERCISE-002` | Un programme et son dosage nécessitent une approbation distincte du rapport ; les champs absents restent inconnus. | Catalogue, revue | Générer une suggestion sans fréquence autorisée. | Aucun dosage inventé ni consigne patient non approuvée. |
| `REQ-DATA-001` | Captures, dossiers, secrets et poids restent hors du dépôt ; les exemples de CI sont synthétiques. | Dépôt, sécurité | Examiner un paquet de release et une PR de test. | Inventaire sans donnée réelle, secret ou ressource interdite. |
| `REQ-VALIDATION-001` | Publier la performance seulement pour les protocoles, captures et populations effectivement évalués. | Validation | Changer moteur de pose ou convention d'angle. | Domaine de validation et évaluation d'impact mis à jour. |

## Décisions à prendre avant le premier protocole actif

- Choisir avec le kinésithérapeute référent le premier mouvement, sa consigne, sa posture, sa vue et ses motifs d'arrêt.
- Fixer pour cet indicateur la convention géométrique, la référence de comparaison, les seuils de qualité et les critères d'acceptation.
- Préciser le système cible, les conditions de collecte de captures autorisées et la durée de conservation, puis tester l'exécution hors ligne.
