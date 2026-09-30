# Matrice d'acceptation initiale

État actuel : certains calculs passent sur des repères synthétiques ; le parcours de séance et la validation clinique restent à développer. `À définir` signifie qu'un protocole, un seuil ou une procédure doit encore être fixé avant de pouvoir conclure. Une démonstration sur données synthétiques ne prouve pas l'aptitude à l'usage clinique.

| Exigence | Résultat observable à obtenir | Vérification / preuve à conserver | État |
| --- | --- | --- | --- |
| `REQ-PURPOSE-001` | Brouillon descriptif associé à un protocole identifié. | Scénario synthétique de bout en bout et export du brouillon. | À faire |
| `REQ-REVIEW-001` | Accepter, corriger et refuser sont des actions distinctes. | Test de revue de résultats erronés et historique des décisions. | À faire |
| `REQ-LOCAL-001` | Séance complète sans dépendance Internet. | Test à froid avec trafic externe bloqué et journal de réseau. | Partiel : démo synthétique locale ; trafic du moteur réel non vérifié. |
| `REQ-TRACE-001` | Chaque résultat montre ses preuves et versions. | Inspection d'un export après changement de version. | Partiel : repère synthétique et versions dans l'objet de mesure. |
| `REQ-SCOPE-001` | Aucune donnée de l'ancienne séance dans le nouveau dossier. | Test de changement de dossier avec réponse tardive. | Partiel : jeton de séance unique et rejet des anciennes images testés. |
| `REQ-CAPTURE-001` | Caméra contrôlable, arrêt effectif, aucun audio. | Tests permission, déconnexion, arrêt et inspection des pistes. | Partiel : interface et API ; caméra physique non testée. |
| `REQ-PROTOCOL-001` | Protocole complet et versionné requis avant mesure. | Validation du schéma de protocole et exemples invalides. | À définir |
| `REQ-MEASURE-001` | Angle, excursion, durée et répétitions correctement nommés. | Squelettes synthétiques et revue des libellés. | Partiel : angle apparent du coude sur données synthétiques. |
| `REQ-QUALITY-001` | Quatre statuts distincts et motifs lisibles. | Clips de rejet, limitation, arrêt et non-réalisation. | Partiel : statuts et motifs testés sur repères synthétiques. |
| `REQ-ABSTAIN-001` | Une capture hors plan ne produit pas de mesure fiable. | Cas d'occlusion, changement de vue et valeurs `null`. | Partiel : abstention selon drapeaux de qualité fournis en entrée. |
| `REQ-SOURCE-001` | Déclaration et saisie manuelle identifiées. | Export avec valeur inconnue, douleur et mesure instrumentée. | À faire |
| `REQ-REPORT-001` | Aucun chiffre généré ne remplace une mesure structurée. | Injection d'un chiffre contradictoire dans une réponse simulée. | Partiel : brouillon déterministe, sans LLM. |
| `REQ-FALLBACK-001` | Brouillon disponible avec LLM arrêté. | Parcours synthétique sans serveur de génération. | Partiel : démo indépendante du LLM, sans parcours de séance. |
| `REQ-VALIDATE-001` | Réviseur identifié ; modification invalide la nouvelle version. | Test de correction après validation et historique conservé. | À faire |
| `REQ-EXERCISE-001` | Fiche retirée ou incompatible jamais proposée. | Jeux de contraintes et tentative du LLM de citer une fiche interdite. | À définir |
| `REQ-EXERCISE-002` | Aucun dosage implicite ; programme approuvé séparément. | Cas sans dosage et test des permissions de validation. | À faire |
| `REQ-DATA-001` | Dépôt et release sans données réelles ni secrets. | Scan de fichiers, secrets et artefacts avant publication. | À faire |
| `REQ-VALIDATION-001` | Toute précision annoncée porte son domaine de validité. | Rapport par protocole et contrôle d'impact après changement. | À définir |

## Hors du premier incrément

Le smartphone local sécurisé, le LLM réel, le suivi longitudinal, la 3D, l'adaptation de modèles et le programme autonome à domicile ne constituent pas des critères de fin du cadrage initial. Leur activation nécessitera des exigences, risques et preuves propres. Le logiciel ne se présentera pas comme diagnostic ou comme garantie de récupération.
