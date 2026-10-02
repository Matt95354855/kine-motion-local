# Premier test sur la machine GPU

Vérification technique volontaire, **pas une validation clinique**. Garder GPT‑OSS/Qwen 3.6 FP4 tels que configurés ; ne pas changer leurs poids pour ce test.

## Préparer

- Récupérer `camera-guidance-local`, installer le profil Windows/Linux du README.
- Exécuter `scripts.check_install --pose-smoke` avec le Python de `.venv`. Noter commit, OS, Python, pose/hash, RAM, GPU/pilote et VRAM disponible. Aucun LLM chargé.
- En cas d'échec, conserver le diagnostic : pas de repli silencieux. `scripts.start_local --demo` teste séparément l'interface avec pose fictive.
- Commencer par une scène/fixture vide, puis un mouvement volontaire non clinique. Aucun patient ni dossier nominatif.
- Qualifier le réseau avec les moyens administrés du poste ; la boucle locale de l'API ne prouve pas l'absence de trafic des dépendances.

## Vérifier le parcours

- Ouvrir `http://127.0.0.1:8765`, choisir le côté anatomique et la caméra. Vérifier voyant, absence d'audio et résolution réelle.
- L'aperçu ne crée pas de séance ; le personnage s'anime sur l'image et peut être masqué. Animations réduites : personnage statique.
- Confirmer profil/stabilité puis démarrer ; comparer les trois repères au bras. Contrôler gauche/droite en miroir ; l'image analysée reste non inversée.
- Masquer le poignet, sortir du cadre, tester une seconde personne : abstention/rejet et aucune association silencieuse.
- Terminer : pistes arrêtées, résultat expérimental, courbe et timestamp du pic. Sans confirmation de qualité, aucune valeur de mesure.
- Arrêter : coupure rapide même pendant la réponse réseau, essai rejeté. Tester aussi débranchement, veille/arrière-plan, permission refusée et caméra occupée.
- Importer un H.264/WebM court : début, temps source, fin et pic. Essayer vidéo trop longue/volumineuse et codec illisible.
- Exporter : brouillon non validé, mode simulation/expérimental, pas de token/JPEG dans le JSON.
- Nouvel essai : ancienne preuve/courbe/note révoquées. Faire 10 essais et comparer la mémoire.
- Expiration 15 min : accès image/séance refusé même sans requête préalable. Les exports déjà téléchargés restent conservés par l'utilisateur.

## LLM existants — seulement si déjà disponibles

- Sans LLM, le brouillon déterministe reste disponible.
- « Vérifier » teste seulement l'alias. Demande de note distincte de la mesure, aucune validation automatique ; réglage FP4 inchangé.
- GPT‑OSS : aucune image. Qwen : seulement le pic et les deux accords existants ; jamais la vidéo complète.
- Note après nouvel essai : ne doit pas réapparaître. Annuler côté navigateur ne garantit pas l'arrêt côté serveur LLM.

## Retour utile et anonyme

- Commit, système, caméra/résolution, mode/versions et diagnostic technique.
- Étapes d'échec, message exact, fréquence, résultat attendu.
- Démarrage/cadence/retards et RAM/VRAM avant/après ; alias des LLM existants sans chemin personnel.
- Mauvais côté, repère faux, pic parasite, faux rejet/acceptation ou caméra non arrêtée : priorité maximale.
- Screenshots fictifs/anonymes seulement. Aucune vidéo patient, visage, note nominative, clé ou poids dans une issue publique.

La précision exige une référence indépendante par protocole. Les seuils techniques du prototype ne sont pas des seuils cliniques.
