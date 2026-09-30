# Registre initial des risques logiciels — version de travail

Ce registre sert à guider les exigences et les tests. Il n'est ni une validation clinique, ni une analyse exhaustive de sécurité. La gravité, la probabilité, l'acceptabilité et les responsabilités devront être établies avec les personnes compétentes avant un usage réel.

| ID | Scénario et conséquence possible | Contrôle prévu | Preuve à produire |
| --- | --- | --- | --- |
| `RISK-LAT-001` | Inversion droite/gauche par miroir vidéo : résultat attribué au mauvais côté. | Confirmation du côté au protocole ; coordonnées anatomiques séparées de l'affichage. | Test miroir sur coordonnées de calcul et export. |
| `RISK-CASE-001` | Réponse tardive ou changement de dossier : mesure rangée dans la mauvaise séance. | Identifiants opaques liés à la séance, rejet des flux périmés, une séance active. | Test de changement de dossier avec capture en cours. |
| `RISK-ANGLE-001` | Plan ou convention d'angle inadapté : valeur plausible mais trompeuse. | Fiche de protocole versionnée, vue vérifiée et libellé d'angle apparent. | Cas géométriques synthétiques et capture hors plan rejetée. |
| `RISK-OCCL-001` | Repère inventé sous occlusion : angle faux publié. | Masques de visibilité et abstention avec motif ; valeur `null` si rejet. | Clips avec poignet ou cheville masqué. |
| `RISK-NOISE-001` | Bruit ou image retardée : valeur extrême ou retour trompeur. | Horodatages réels, file bornée, filtrage versionné, preuve du sommet retenu. | Tests de jitter, pertes d'images et retard. |
| `RISK-COUNT-001` | Oscillation autour d'un seuil : répétition comptée deux fois. | Segmentation avec états, hystérésis et durée minimale. | Séquence synthétique avec pause et oscillation. |
| `RISK-STOP-001` | Arrêt pour douleur traité comme essai complet : résultat ou relance inadaptés. | Arrêt immédiat, statut interrompu, calcul complet interdit. | Essai interrompu avec déclaration de douleur. |
| `RISK-EX-001` | Exercice incompatible ou retiré proposé au patient. | Catalogue approuvé, exclusions déterministes, validation distincte du programme. | Cas avec restriction et demande LLM d'un identifiant interdit. |
| `RISK-LLM-001` | Texte généré inventant diagnostic, valeur ou dosage. | Chiffres rendus depuis objets structurés, contrôle sémantique, repli déterministe. | Réponses simulées contradictoires rejetées. |
| `RISK-DRAFT-001` | Brouillon confondu avec rapport validé. | Statut visible sur écran et export ; validation réservée à un professionnel identifié. | Export brouillon imprimé et correction après validation. |
| `RISK-DATA-001` | Capture, dossier ou secret publié sur GitHub ou dans un log. | Données hors dépôt, contrôle prépublication et journalisation minimale. | Inspection de release, scan des secrets et journaux synthétiques. |

## Priorités avant la capture réelle

La définition du premier protocole doit fixer côté, vue, repères, formule, motifs d'arrêt et conditions de rejet. Les contrôles `RISK-LAT-001`, `RISK-CASE-001`, `RISK-ANGLE-001` et `RISK-OCCL-001` doivent être conçus dès les contrats de données. Une mesure qui ne passe pas ces contrôles ne doit pas être présentée comme exploitable.
