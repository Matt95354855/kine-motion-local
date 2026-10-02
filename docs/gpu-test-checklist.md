# Premier test : Windows GPU + poste webcam

Vérification technique volontaire, **pas une validation clinique**. Garder GPT‑OSS/Qwen 3.6 FP4 tels que configurés ; ne pas changer leurs poids pour ce test.

## Préparer

- Récupérer `camera-guidance-local`, installer le profil Windows/Linux du README.
- Sur le Windows **sans webcam**, installer seulement le calcul et la pose ; lancer avec `--remote-client`. Les serveurs GPT‑OSS/Qwen restent sur sa boucle locale.
- Sur le poste webcam, suivre `two-machine-setup.md` : client OpenSSH + Python, contrôle de l'empreinte du Windows et pare-feu privé, lanceur `scripts.start_client`. Pas de pose/LLM à installer sur ce poste.
- Exécuter `scripts.check_install --pose-smoke` avec le Python de `.venv`. Noter commit, OS, Python, pose/hash, RAM, GPU/pilote et VRAM disponible. Aucun LLM chargé.
- En cas d'échec, conserver le diagnostic : pas de repli silencieux. `scripts.start_local --demo` teste séparément l'interface avec pose fictive.
- Commencer par une scène/fixture vide, puis un mouvement volontaire non clinique. Aucun patient ni dossier nominatif.
- Qualifier le réseau avec les moyens administrés du poste ; la boucle locale de l'API ne prouve pas l'absence de trafic des dépendances.

## Vérifier le parcours

- Ouvrir `http://127.0.0.1:8765` **sur le client**, choisir le mouvement, côté/direction et caméra. Vérifier voyant du client, absence d'audio et résolution réelle. Le Windows ne doit pas demander sa caméra.
- L'aperçu ne crée pas de séance ; personnage **permanent**, animation propre à chaque geste. Animations réduites : personnage statique toujours visible. Cadre pointillé indicatif, pas une validation automatique.
- Confirmer face/profil selon le mouvement et stabilité puis démarrer ; comparer les repères à la personne. Contrôler gauche/droite en miroir ; l'image analysée reste non inversée.
- Tester séparément coude, genou, épaule, hanche, tronc et inclinaison du cou ; nouveaux résultats toujours limités. La rotation du cou doit rester **sans angle ni courbe mesurée**. Ne pas interpréter le proxy tête/épaules comme une amplitude cervicale.
- Masquer un repère requis, sortir du cadre, tester une seconde personne : abstention/rejet. Masquer un poignet pendant un test du genou ne doit pas invalider ses repères visibles. Aucun suivi de personne silencieux après occlusion.
- Terminer : pistes arrêtées, résultat expérimental, courbe et timestamp du pic. Sans confirmation de qualité, aucune valeur de mesure.
- Arrêter : coupure rapide même pendant la réponse réseau, essai rejeté. Tester aussi débranchement, veille/arrière-plan, permission refusée et caméra occupée.
- Importer un H.264/WebM court : début, temps source, fin et pic. Essayer vidéo trop longue/volumineuse et codec illisible.
- Exporter : brouillon non validé, mode simulation/expérimental, pas de token/JPEG dans le JSON.
- Nouvel essai : ancienne preuve/courbe/note révoquées. Faire 10 essais et comparer la mémoire.
- Expiration 15 min : accès image/séance refusé même sans requête préalable. Les exports déjà téléchargés restent conservés par l'utilisateur.

## Liaison entre les postes

- Vérifier que 8765/ports LLM ne sont pas ouverts au réseau, que SSH est limité au client/VPN et que l'empreinte a été comparée sur le Windows.
- Tester Wi‑Fi puis Ethernet : nombre d'images traitées, aller-retour en ms et P95/volume JPEG dans l'export. Pas de file d'attente d'images ; débit analysé cible 5 Hz, non garanti.
- Ralentir la liaison : anciens repères effacés après 1 s, pas de superposition faussement synchrone. Observer séparément la valeur finale, dont le pic reste brut.
- Couper le tunnel/réseau pendant un essai : arrêt caméra après erreur/timeout (requête image bornée à 15 s), aucune ancienne réponse dans un nouvel essai. Arrêt manuel immédiat disponible sans attendre le serveur.
- Reconnexion : ouvrir explicitement un nouvel essai ; pas de reprise silencieuse. Essayer port client occupé et serveur absent.
- Fermer le client : essai/séance révoqués si message reçu ; expiration serveur en secours. Un export déjà téléchargé n'est pas effacé à distance.
- N'utiliser qu'un navigateur : un nouvel essai sur un autre poste révoque l'ancien. Ce POC n'est pas multi-utilisateur.

## LLM existants — seulement si déjà disponibles

- Sans LLM, le brouillon déterministe reste disponible.
- Les notes LLM restent limitées au coude ; bouton désactivé et refus API pour les nouveaux mouvements. Les brouillons multi-protocoles ne sont pas générés par un LLM.
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
