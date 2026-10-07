# Robustesse de l'analyse — 7 octobre 2026

Incrément intégré à la livraison du **7 octobre**. Il renforce la traçabilité
et la lecture du suivi ; il ne démontre pas une amélioration de précision en degrés.
Le geste de l'utilisateur n'est pas déclaré mauvais à partir d'une perte de pose.

## Ce qui change

- Diagnostics par repère requis : visibilité, présence, seuil appliqué et cause
  technique de non-conservation. Les entrées non finies deviennent `null`, avec
  les champs concernés signalés. Les scores ne sont pas une précision angulaire.
- Libellés factuels : `no_pose` signifie que le détecteur n'a pas retourné de pose ;
  `occlusion`, conservé pour compatibilité, peut également désigner un repère sous
  le seuil de confiance. Il ne prouve pas à lui seul un masquage physique.
- Comptes par motif et groupes d'images non exploitables, sans interpolation.
  Les 32 premiers groupes sont détaillés ; les comptes couvrent tous les groupes.
  La durée d'un groupe est l'écart entre sa première et sa dernière image reçue
  (une image isolée : 0 ms), pas une durée de panne ou d'absence de personne.
- Contexte du maximum brut : les voisins immédiatement précédent/suivant sont
  décrits seulement si leurs angles sont calculables, leurs séquences contiguës
  et leurs horodatages croissants, avec un écart au pic de 1 000 ms au maximum.
  Cette limite est **technique**, pas un seuil de plausibilité biomécanique.
  Les différences d'angle sont brutes ; aucun voisin ne valide le pic.
- Plus grande variation entre deux images immédiatement adjacentes exploitables,
  avec intervalle et écart temporel. Aucun seuil arbitraire ne la classe comme
  mouvement impossible ou erreur certaine du détecteur.
- Interface courte : « suivi à vérifier », pic brut 2D, détails repliés et rappel
  des confirmations manuelles. Le personnage reste visible. Les confirmations
  ne sont jamais cochées automatiquement et ne jugent pas le geste.
- Export JSON versionné : distinction entre aperçu et JPEG encodé,
  dimensions confirmées par le serveur, cadence cible et qualité JPEG. La source
  1 280 × 720 peut être analysée en 640 × 360 ; la résolution n'a pas été augmentée.
- Instantané de provenance au démarrage du serveur : commit/état Git, hash du
  périmètre d'implémentation déclaré, version Python/MediaPipe, hash réel du modèle
  de pose configuré et options effectives. Les informations indisponibles restent
  `null`. Aucun chemin privé, jeton ou identité de personne n'est ajouté. La
  livraison complète ajoute les paramètres navigateur/caméra et la configuration
  LLM filtrée, ainsi que des compteurs de tentatives ; voir [le manifeste](progress-2026-10-07.md).

Les seuils de conservation des repères restent à **0,5**. Les trois seuils natifs
MediaPipe sont maintenant explicites à leur valeur par défaut existante, 0,5.
Deux poses maximum, CPU et mode VIDEO inchangés. Les dimensions, cadence cible,
compression et choix du maximum sont inchangés. La livraison complète refuse
désormais une capture temporellement interrompue, même si trois bonnes images
avaient déjà été reçues ; ce rejet est une protection technique, pas un jugement du geste.
GPT‑OSS, Qwen 3.6 FP4, leurs poids, alias et paramètres restent inchangés.

## Contrats et limites

`motion.samples` conserve ses quatre clés historiques. Les compléments sont dans
`motion.robustness` et `motion.pose_diagnostics`. Ces derniers ne sont ni de
nouveaux faits cliniques ni des instructions libres envoyées au LLM. Le contrat
de vocabulaire fermé des observations live reste inchangé. Le motif fermé
`capture_interrupted` complète les motifs de mesure/rapport et les faits de la
note finale ; aucune instruction libre n'est ajoutée.

Le maximum brut, sa séquence et son JPEG de preuve restent associés comme avant.
Aucun filtre ne remplace cette valeur. Une mesure rejetée garde `value_deg: null` :
le rapport et le résultat principal ne republient pas un angle via les diagnostics.
La courbe et le maximum brut peuvent rester dans les données techniques de test,
explicitement non validées. La rotation guidée du cou reste sans angle ; cette
absence attendue n'est pas comptée comme perte de suivi.

La provenance est un **instantané de démarrage** : redémarrer après modification
du code, du modèle ou de l'environnement. `implementation_sha256` couvre les
fichiers listés dans `services/api/provenance.py`, y compris le contrôle capture
et le harness, pas tous les logiciels de la machine ni les poids/runtime LLM.
Le hash du modèle de pose n'est fourni que si son chemin a été
transmis au serveur et le fichier est lisible et dans la limite de 32 Mo.
`hash_verified: false` constate une différence, sans remplacer le fichier ; un
hash vérifié établit l'intégrité du fichier, pas sa précision.

Les diagnostics restent en mémoire, puis dans les exports explicitement demandés.
Ils sont effacés avec la séance : nouvel essai, annulation ou expiration. Aucun
enregistrement continu de vidéo et aucune image personnelle ajoutée au dépôt.

## Vérification et suite

Les tests automatisés couvrent les seuils, scores non finis, compatibilité des
contrats, pertes/horodatages, limites de voisinage, absence de quantification,
provenance, refus d'angles sur mesure rejetée et nettoyage des données. Les médias,
poses et serveurs utilisés par ces tests sont simulés ; ils ne prouvent pas la
précision sur le Windows GPU ou une personne réelle.

Le premier incrément a passé **188 tests Python et 70 tests JavaScript (258 total)**
avant l'ajout du watchdog capture et du manifeste LLM. Vérifications complètes de
la livraison dans [le suivi du 7 octobre](progress-2026-10-07.md), sans prétendre
à une validation webcam/GPU ou à la précision clinique.

Contrôle navigateur : démarrage de l'interface de démonstration observé, sans
webcam. Le clip géométrique existant utilise `mp4v` et a été refusé comme illisible
par ce navigateur ; aucune validation vidéo de bout en bout n'est revendiquée.
Le serveur de contrôle a été arrêté ; aucun fichier de capture n'a été ajouté.

Pour le prochain essai volontaire non clinique, exporter JSON et TXT de cette
version, vérifier la provenance et comparer les motifs/intervalles aux images.
Ne pas transmettre de vidéo personnelle sans accord explicite, et ne pas déposer
ces captures sur GitHub. Les anciens exports sans diagnostics restent lisibles,
mais ne permettent pas de reconstruire les scores ou la résolution réelle.

Avant de modifier seuils, résolution ou estimation finale : constituer un jeu de
clips autorisés avec repères annotés et référence 2D, comparer les configurations
dans les mêmes conditions et mesurer erreurs, variabilité et délais. Un pic
filtré aurait besoin d'une preuve distincte correspondant au nouvel estimateur.
Le watchdog des images manquantes est maintenant intégré, mais reste à qualifier
sur le matériel. Détecter des pixels figés malgré des horodatages croissants, le
suivi d'identité, la calibration et l'évaluation automatique du geste restent à
réaliser/qualifier séparément.

Références primaires : [scores de repères MediaPipe](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/components/containers/Landmark),
[options du moteur](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarkerOptions).
