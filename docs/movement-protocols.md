# Catalogue de mouvements POC — conventions et limites

Version des nouveaux protocoles : `0.1.0-dev`, pipeline `0.3.0-dev`. Le coude conserve son ancien pipeline/contrat. Le catalogue exécutable est `packages/biomechanics/protocols.py` et l'interface le récupère auprès de l'API : pas de liste concurrente de mouvements dans le navigateur.

Il s'agit de parcours expérimentaux d'observation, **pas d'examens cliniques validés**. Les silhouettes sont animées indépendamment de la personne filmée. Elles restent visibles en aperçu, en capture et après l'essai ; la préférence d'accessibilité « réduire les animations » les fige. Aucune cadence, série, charge, amplitude à atteindre ou prescription n'est donnée.

## Repères et conventions

- **Coude** : épaule–coude–poignet du côté sélectionné ; flexion projetée = 180° − angle interne. Ne quantifie pas l'hyperextension signée.
- **Genou** : hanche–genou–cheville, même convention. Hanche, genou et cheville doivent être visibles dans le même plan de profil.
- **Épaule** : coude–épaule–hanche ; angle interne entre bras et axe apparent du tronc. Le coude sert à orienter le bras, pas le poignet. Une caméra de face ne permet pas de corriger les rotations/projections ni d'isoler les contributions scapulaires.
- **Hanche** : épaule–hanche–genou ; 180° − angle interne. L'épaule fournit un axe de tronc, pas un repère osseux du bassin ; mouvements du tronc/bassin et vêtements peuvent biaiser le résultat.
- **Tronc** : axe entre milieu du bassin et milieu des épaules ; inclinaison absolue par rapport au haut de l'image. Une caméra inclinée biaise la valeur. Pas de mesure segmentaire rachidienne.
- **Inclinaison du cou** : angle absolu entre la ligne oreille gauche→droite et épaule gauche→droite. Les quatre repères doivent être visibles. C'est un proxy d'orientation tête/épaules, **pas une amplitude cervicale**. Détection des oreilles, perspective, rotation hors plan, asymétrie et épaules mobiles sont des limites majeures. Aucune calibration neutre automatique.
- **Rotation du cou** : guide animé, lignes d'oreilles/épaules quand visibles, **aucun angle**. La projection 2D actuelle ne fournit pas de mesure de rotation cervicale. Résultat `rejected`, raison `rotation_not_measurable_2d` ; cela décrit la limite de calcul, pas un échec du mouvement de la personne.

Les coordonnées normalisées sont converties en pixels avec la largeur **et** la hauteur de la capture. Le miroir est réservé à l'affichage ; les repères anatomiques ne sont pas permutés. Les angles sont non signés et le résultat numérique est le pic brut de l'essai, pas une différence neutre→pic ni une amplitude passive.

Pour les articulations, `side` est le côté anatomique **demandé**. Pour le tronc/cou, il indique la direction de l'illustration ; cette direction n'est pas vérifiée dans la vidéo et n'est pas une classification automatique du mouvement. Le rapport le précise. Une comparaison gauche/droite n'est pas encore réalisée.

## Contrôles et abstention

- La pose recherche au plus deux personnes pour pouvoir refuser un cadre multipersonne ; aucun suivi d'identité persistante.
- La visibilité/présence des repères est filtrée à 0,5 (seuil technique provisoire). L'absence d'un point requis refuse l'image ; les points non utilisés par le mouvement ne bloquent pas l'essai.
- Vue de face/profil et caméra stable restent confirmées **manuellement**. Le cadre en pointillés est indicatif, sans validation automatique du cadrage.
- Au moins trois images utilisables et 80 % de couverture pour une valeur. Ces minima techniques ne sont pas une garantie de précision, ni une durée clinique suffisante.
- Arrêt, vue non confirmée, caméra instable ou plusieurs personnes : aucune valeur publiée.
- Pour tous les nouveaux protocoles quantifiés, une valeur éventuellement calculée reste `limited`, avec `experimental_protocol` et les réserves spécifiques tête/tronc. Le statut `valid` du coude est uniquement un statut technique hérité, jamais une validation clinique.
- Repères âgés de plus de 1 s masqués, pas déplacés artificiellement pour suivre la vidéo. Le résultat serveur peut encore être exploitable, mais l'affichage n'affirme pas une superposition synchrone si le traitement est lent.

## Rapports et LLM

Le brouillon déterministe nomme le bon mouvement, la convention, les réserves et la preuve. L'image du pic est conservée seulement lorsqu'une valeur a une référence de preuve concordante ; aucune image de pic pour la rotation guidée. Le résumé conserve les trous sans interpolation. Export JSON `schema_version=1.1` : métadonnées du protocole et statistiques descriptives de transport ; aucun jeton ni JPEG.

GPT‑OSS/Qwen 3.6 FP4 et le harness existant ne sont pas modifiés. Le harness reste réservé au coude : bouton désactivé pour les nouveaux mouvements et refus serveur `409 protocol_not_supported_by_harness`, même en cas d'appel direct. Étendre son contrat de façon explicitement autorisée et testée sera un travail séparé.

## Qualification à faire

Faire approuver chaque consigne et motif d'arrêt par un professionnel. Utiliser des clips consentis/non cliniques et annotés indépendamment. Définir une référence et une tolérance **pour chaque convention**, puis relever erreurs, abstentions, répétabilité, morphologie, angles de caméra, vêtements et éclairage. Les tests géométriques/synthétiques actuels prouvent le calcul et le transport, pas la validité de la perception sur une personne.

Ne pas ajouter de tests de force, de manœuvres provocatives ou d'interprétation diagnostique sous couvert de multiplier les mouvements. Arrêter l'observation en cas de douleur ou de gêne ; ce prototype ne détermine pas si une personne peut réaliser un geste en sécurité.
