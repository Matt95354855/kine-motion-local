# Premier test : Windows GPU + poste webcam

Vérification technique volontaire, **pas une validation clinique**. Garder GPT‑OSS/Qwen 3.6 FP4 tels que configurés ; ne pas changer leurs poids pour ce test.

## Préparer

- Récupérer explicitement `camera-guidance-local`, pas `main` ; suivre les instructions de mise à jour du README en préservant les modifications locales. Noter le SHA avec `git rev-parse HEAD`, puis installer le profil Windows/Linux. Vérifier la CI du **même commit** ; un ancien résultat vert ne qualifie pas la livraison actuelle.
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
- Rechercher une image figée sans déconnexion explicite. Le watchdog de gel n'est pas encore développé : si la caméra ne produit plus d'images récentes, arrêter volontairement, ne pas retenir la mesure et noter le défaut. Le compteur des seules images traitées ne prouve pas une capture complète.
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
- Contrat final du 6 octobre : réponse avec `measurement_ref`, `fact_codes`, `requires_professional_review:true` seulement, et restitution exacte de `supported_fact_codes`. Aucun texte libre du modèle n'est affiché ; la phrase française vient de l'application. L'ancien JSON `text` doit produire un repli, pas une note. Voir [le contrat](tool-integration.md).
- Comparer une mesure exploitable, limitée et rejetée : la note doit conserver les réserves factuelles autorisées, sans transformer un rejet en réussite ni ajouter un diagnostic ou un exercice. Relever les réponses mal formées et les replis avec chaque LLM, sans changer les paramètres FP4.
- GPT‑OSS : aucune image. Qwen : seulement le pic et les deux accords existants ; jamais la vidéo complète.
- Note après nouvel essai : ne doit pas réapparaître. Annuler côté navigateur ne garantit pas l'arrêt côté serveur LLM.

### Assistant pendant l'essai — nouveau parcours optionnel

- Après préparation de la source, sélectionner le modèle existant, « Vérifier » son alias et activer l'assistant live. Cocher les images avant le live si Qwen visuel autorisé. Aucun changement FP4, poids ou serveur.
- Démarrer : la pose/guide doivent continuer pendant une analyse LLM lente. Le retour distingue une observation provisoire et son intervalle source ; il ne valide pas l'exécution du geste ni une mesure.
- Vérifier absence d'images GPT‑OSS ; Qwen reçoit au plus deux JPEG récents/chronologiques seulement après consentement et demande de son outil. Aucun rattrapage d'images pré-consentement.
- Tester les sept parcours ; la rotation reste un guide sans angle. Suivi perdu/partiel doit être décrit comme tel, pas comme un mouvement réussi.
- « Pause » : retour assistant effacé, caméra/pose/personnage toujours actifs. Décocher, changer modèle/images ou finir l'essai : retour effacé, pas de réponse tardive, réactivation volontaire nécessaire. Intervalle/âge/provisoire lisibles ; détails repliés, pas de texte libre du modèle sur la caméra. Vérifier petit écran et animations réduites.
- Ralentir le LLM : budget total 10 s maximum en live, réduit selon l'âge des observations, 30 s pour la note ; aucune nouvelle échéance à chaque outil. Tester attente avant en-têtes et corps reçu très lentement. Réponse expirée masquée/repli explicite, aucune file de fenêtres.
- Demander deux notes simultanées, ou une note pendant le live : une seule analyse, deuxième demande refusée/état occupé, aucun empilement. Le slot ne doit pas être réutilisé tant qu'un ancien worker non coopératif n'est pas sorti.
- Annuler pendant une génération, puis remplacer la séance : le transport local doit se fermer et aucune ancienne note/fenêtre ne doit réapparaître. Observer séparément durée de calcul et VRAM sur Windows : la déconnexion HTTP **ne garantit pas** que le runtime abandonne le calcul GPU. Noter ce comportement avant d'augmenter la charge.
- Couper source/tunnel : contrôler arrêt existant et disparition des retours, y compris après retour à une page mise en cache.
- Confirmer que le JSON/TXT final ne contient aucun texte live, JPEG, prompt ni token. La fenêtre courte est distincte de la courbe et de l'unique preuve finale.
- Mesurer RAM/VRAM et durée réelle avec/sans images ; les tests simulés ne prouvent pas la compatibilité du serveur avec les nouveaux outils. Voir [mémoire, consentement et API live](live-harness.md).

## Retour utile et anonyme

- Commit, système, caméra/résolution, mode/versions et diagnostic technique.
- Identifier aussi le hash de pose, les versions du runtime/driver et les alias/variantes FP4 effectivement installés. Les exports ne contiennent pas encore toute cette provenance : la consigner séparément pour la campagne.
- Étapes d'échec, message exact, fréquence, résultat attendu.
- Démarrage/cadence/retards et RAM/VRAM avant/après ; alias des LLM existants sans chemin personnel.
- Mauvais côté, repère faux, pic parasite, faux rejet/acceptation ou caméra non arrêtée : priorité maximale.
- Screenshots fictifs/anonymes seulement. Aucune vidéo patient, visage, note nominative, clé ou poids dans une issue publique.

La précision exige une référence indépendante par protocole. Les seuils techniques du prototype ne sont pas des seuils cliniques.
