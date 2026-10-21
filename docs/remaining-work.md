# Points restants — avant et après les essais

État actualisé au **7 octobre 2026** ; le tableau initial ci-dessous conserve l'avancement préparé le 2 octobre. « Test technique » signifie essai volontaire non clinique sur le poste cible. Les tests automatiques ne remplacent ni une validation de vidéo réelle ni un pilote auprès de patients. Les protections, vérifications et limites sont suivies dans [l'avancement du 7 octobre](progress-2026-10-07.md).

**Complément du 7 octobre :** causes/scores des repères, comptes et intervalles de pertes, contexte du pic brut, interruption capture persistante et provenance code/pose/capture/LLM ont été ajoutés. Voir [le périmètre et les limites](analysis-robustness-2026-10-07.md). Il reste à qualifier les erreurs sur des clips autorisés/annotés avant tout changement de seuil, de résolution ou d'estimateur ; pas de jugement automatique du geste ni de précision clinique acquise.

## Les cinq premiers points de la liste initiale

| Point | Travail réalisé | Reste à vérifier |
| --- | --- | --- |
| 1. Environnement reproductible | Python/Node identifiés, dépendances verrouillées avec hashes, modèle SHA-256, diagnostic local. | Installation Windows/Linux, pilote RTX et machine propre. |
| 2. Vrai moteur de pose | Modèle local préparé ; MediaPipe initialisé ; image vide traitée avec abstention ; délégué CPU. | Corps réel, latéralité, occlusions, qualité et réseau sur le poste cible. |
| 3. Choix des modèles | GPT‑OSS et Qwen 3.6 en FP4 conservés selon la dernière demande. | Variante/révision, alias et hash des poids existants à inventorier sur le poste GPU. |
| 4. Ressources RTX | Diagnostic RAM, VRAM/pilote via `nvidia-smi`, disque ; pose sur CPU. | Charge réelle des LLM existants ; contexte et chargement non reconfigurés. |
| 5. Vérification des modèles | Intégrité/smoke test de pose ; vérification d'alias LLM existante conservée. | Réponses et outils des vrais LLM, image Qwen, pannes et dépassements : non exécutés. |

## Points déjà avancés dans cette livraison

- Démarrage simple, diagnostic de ressources manquantes, installation explicite avant séance.
- Aperçu avant essai, choix de caméra, latéralité visible et miroir d'affichage seulement.
- Horodatage de fichier issu du temps vidéo ; premier échantillon avant lecture ; images immobiles/répétées ignorées.
- Durée/taille/cadence bornées, un seul traitement image en vol, pas de file qui accumule les images.
- Démarrages doubles bloqués ; annulation avant permission prise en compte ; flux tardif arrêté.
- Arrêt média immédiat avant l'attente réseau ; nouvelle séance protégée des réponses tardives, y compris celles du harness existant.
- Guide **permanent**, adapté à sept mouvements ; cadre indicatif et repères propres à chaque mouvement, courbe brute, durée/couverture ; image du pic horodatée si une mesure existe.
- Cou : proxy d'inclinaison tête/épaules explicitement limité ; rotation guidée sans angle inventé. Genou, épaule, hanche et tronc : projections expérimentales.
- Poste webcam séparé du Windows GPU : lanceur de tunnel OpenSSH, API/LLM toujours sur 127.0.0.1, guide d'installation privé ; liaison réelle restant à tester.
- Rejets de pose absente, plusieurs personnes, repères masqués/hors cadre ; dimensions JPEG bornées avant décompression.
- Confirmations humaines de profil/stabilité, nouvel essai ; résultats/exports explicitement expérimentaux/brouillons.
- Expiration automatique et libération des captures sans requête ultérieure.
- Clip géométrique synthétique, tests supplémentaires, CI synthétique Linux/Windows et scan avant publication.
- README, matrice d'acceptation et checklist de test actualisés.
- Harness live optionnel pendant capture, indépendant des requêtes de pose ; mémoire glissante 5 s/25 observations, jusqu'à deux JPEG après consentement, références temporelles. Codes d'observation vérifiés, sans texte clinique libre ; voir [le détail et les limites](live-harness.md).
- Arrêt/changement de modèle/images avec versions de contrôle monotones, protection contre les anciennes requêtes et résultat obsolète masqué ; aucun retour live dans l'export final.
- Points 3–4 du parcours temps réel : slot LLM unique partagé live/note sans file, budget total 10 s/30 s et transport HTTP interruptible ; retour caméra court contrôlé, âge actualisé, pause indépendante et personnage permanent. Voir les limites du runtime distant dans [le contrat live](live-harness.md).
- Points 1–2 de l'audit du 6 octobre : regroupement des changements live pour une version de test identifiable sur `camera-guidance-local`, et note finale à codes factuels exacts vérifiés contre la mesure. Ancien JSON `text`, ajout/omission de fait et réponse contradictoire écartés ; formulation française déterministe et brouillon conservé. Aucun changement des modèles FP4. Voir [le contrat final](tool-integration.md).
- Audit du 7 octobre : watchdog source/traitement navigateur et réception/temps source serveur, interruption persistante, capture illisible rejetée, valeur/preuve finale supprimées. Annulation du slot LLM signalée avant d'attendre un éventuel verrou de pose ; test de cette course ajouté.
- Manifeste automatique : commit/hash, pose/options, protocole, navigateur/caméra, configuration LLM au démarrage et tentatives live/note agrégées. Versions/poids/quantification inconnus explicitement `null`, [fiche du premier essai](test-record-template.md) pour compléter sur le GPU.

## Avant de conclure au bon fonctionnement du parcours réel

- Reproduire l'installation sur la machine GPU et consigner système, versions, modèle de pose, commit et pilotes ; vérifier la CI distante.
- Tester une détection **positive** du corps : un succès sur image vide prouve l'initialisation et l'abstention seulement.
- Vérifier le fonctionnement sans accès externe à froid et à chaud : trafic de perception, dépendances et journaux. Aucun firewall système n'a été activé ici.
- Vérifier les licences du code, des poids et des dépendances ; décider la licence du projet avant redistribution d'un paquet offline.
- Finaliser avec un kiné la fiche versionnée **de chaque mouvement** : position, côté/direction, vue, consigne, début/fin, motifs d'arrêt et critères de rejet. Le guide est une illustration, pas un protocole médical approuvé. Ne pas assimiler le proxy du cou à l'amplitude cervicale.
- Annoter indépendamment des clips autorisés : bonnes vues, poignet masqué, hors plan, fond difficile, personne supplémentaire et résultats attendus. Aucun clip personnel dans Git.
- Vérifier physiquement permissions, caméra externe, débranchement, veille, caméra occupée, changement de caméra et rechargement. L'arrêt testé avec média simulé n'est pas certifié pour toutes les caméras.
- Qualifier la détection des **images qui cessent d'arriver** : trois secondes déclenchent désormais « capture interrompue », même après reprise. Tester vraie webcam, lenteur pose, coupure tunnel, onglet suspendu et fin naturelle de fichier. Détecter des pixels figés lorsque les horodatages continuent d'avancer reste à étudier ; distinguer gel, perte réseau et pose absente.
- Mesurer les images **présentées**, perdues/sautées et traitées : le compteur actuel donne les traitements, pas le nombre exact de pertes caméra. P95 d'aller-retour et volume JPEG ajoutés ; isoler capture/réseau/calcul/écran, tester Wi‑Fi/Ethernet et valider le seuil provisoire d'expiration des repères de 1 s.
- Vérifier SSH sur le Windows : empreinte, compte, restriction du pare-feu, transferts autorisés, port occupé, interruption/reprise et webcam du client. Pas d'API ni de LLM exposés au LAN directement. Pour plusieurs utilisateurs, revoir l'authentification et l'isolation : une nouvelle séance révoque actuellement la précédente.
- Résoudre les changements silencieux de personne après perte de suivi ; le refus de plusieurs personnes ne fournit pas une identité de suivi persistante.
- Compléter la qualité : flou, éclairage, taille corporelle, stabilité/hors-plan automatiques. Le seuil de visibilité/pré­sence de 0,5 est technique et provisoire, pas une borne d'erreur angulaire.
- Filtrer/contrôler les pics parasites : **le maximum reste brut** ; une seule image bruitée peut fournir le pic. Définir filtre, fenêtre, provenance et test sans masquer un vrai maximum.
- Développer une segmentation validée avant de compter les répétitions. L'excursion brute des données de test n'est ni une amplitude passive ni un nombre de répétitions.
- Traduire tous les motifs détaillés de rejet et temporiser les alertes ; vérifier la compréhension des confirmations manuelles.
- Vérifier le manifeste exporté contre le SHA réellement lancé et compléter la fiche des runtimes/poids LLM : alias/endpoint ne prouvent pas leur révision ou le FP4 effectif. Redémarrer après mise à jour ; l'instantané de provenance est pris au démarrage serveur. Ne comparer que des essais dont la configuration est identifiée.
- Fixer avant le test les seuils techniques d'acceptation, conditions d'arrêt et cas de non-régression. Les 5 images/s actuelles n'atteignent pas l'objectif provisoire de 15 mises à jour/s du document de départ.

## LLM / harness — modèles inchangés, circuit live ajouté

- Inventorier les poids exacts GPT‑OSS/Qwen 3.6 FP4 ; mesurer RAM/VRAM, contexte et chargements sur la RTX sans changer leur configuration à ce stade.
- Tester réponses réelles, outils successifs, disponibilité et pannes ; un alias annoncé ne valide pas ces capacités.
- Finaliser le contrat des futurs outils : schémas, permissions, limites, timeout, panne et preuves.
- Qualifier les outils live et l'analyse des fenêtres de cinq secondes sur les serveurs réels. Les codes actuels décrivent uniquement le suivi technique ; exécution du geste, segmentation et répétitions ne sont pas encore analysées.
- Tester le contexte visuel Qwen (au plus deux JPEG chronologiques de la fenêtre, outil opt-in). Note finale toujours limitée à une image ; pas de vidéo complète, GPT‑OSS sans pixels.
- Qualifier la **note finale désormais fermée** avec les vrais LLM : restitution exacte des codes autorisés, rejet de l'ancien champ `text`, référence différente, codes manquants/ajoutés et essai rejeté décrit comme réussite. La formulation est déterministe et n'autorise aucune conclusion depuis l'image ; vérifier les taux de repli et l'utilité de ce parcours, sans confondre ce contrôle avec la validité de la mesure.
- Qualifier l'interruption physique **côté runtime d'inférence** : l'application borne l'analyse entière, coupe l'attente réseau et arbitre live/note sur un slot unique. Vérifier sur Windows que la génération s'arrête et que l'activité/mémoire additionnelle reviennent à leur niveau de repos ; les poids chargés peuvent rester normalement en VRAM. Les clients externes restent hors de cet arbitrage. Le watchdog d'un moteur natif de pose bloqué reste à développer.
- Compléter l'historique technique minimal : les tentatives LLM sont agrégées sans prompt/pixels/texte généré ; inventaire des versions, durées d'inférence et erreurs/repli du runtime à mesurer séparément sans données identifiantes.
- Tests d'instructions parasites et accès interséance ; comparaison des deux LLM sur les mêmes cas.

## Pendant les tests, puis selon les résultats

- Installation : démarrage froid/chaud, redémarrage du poste, ressource absente, hash incorrect, reprise après panne d'un moteur.
- Mémoire : pics RAM/VRAM et tendance après 10–20 essais ; fuite de pistes, URLs Blob et preuves.
- Rapidité : percentiles capture/pose/écran, durée des notes, saturation/cas très lents ; ne pas extrapoler le benchmark d'images vides.
- Capture : résolution, débit analysé, pertes et retard ; chronologie vidéo, début/fin et provenance du pic malgré un traitement lent.
- Repères : accord avec annotations indépendantes, miroir/lateralité, aucune association silencieuse à une autre personne.
- Mesures : écart avec une référence au même plan/convention, répétabilité, effet du fond, masquages, vêtements, éclairage, distance et morphologie.
- Qualité : mauvaises captures acceptées et bonnes rejetées, précision/couverture ; pics parasites et effet d'un futur filtre sur le vrai maximum.
- Notes : côté, protocole, données manquantes, rejet et preuve visible ; hallucinations Qwen et intérêt du repli déterministe.
- Harness : format malformé, outils interdits, boucles, limites, panne LLM, instructions parasites et refus interséance.
- Pannes : déconnexion, arrière-plan/veille, mémoire saturée ; doubles clics et annulation pendant traitement/finalisation.
- Confidentialité : trafic externe, journaux, absence de microphone et disparition des captures/jetons après annulation/expiration. La libération logique n'est pas une garantie de zéroisation de RAM/swap.
- Compréhension : retrouver la preuve, reconnaître simulation/brouillon/angle incertain ; corrections et temps réel de revue.
- Régressions : rejouer cas concernés **et** cas indépendants ; fixer ressources et paramètres.
- Priorités : mauvaise séance/inversion de côté/mesure fausse acceptée/affirmation inventée d'abord ; performances et ergonomie ensuite.

## Avant tout essai auprès de patients

- Accepter, corriger et refuser chaque résultat ; annotation des repères et saisie manuelle identifiée.
- Validation explicite avec identité du réviseur, historique et invalidation après modification.
- Dossiers protégés, accès, consentement, conservation, chiffrement/sauvegardes et effacement.
- Pilote supervisé, destination/responsabilités qualifiées et évaluation réglementaire compétente.
- Validation par protocole : domaine d'emploi, erreurs et abstention documentés.

Smartphone/HTTPS direct, qualification des nouveaux mouvements, 3D, suivi longitudinal et catalogue d'exercices approuvé restent des extensions distinctes. Le parcours à deux ordinateurs est préparé via SSH, **pas** en exposant ce serveur au réseau. Ne pas le transformer en programme autonome.

## Améliorations proposées, par priorité

1. **Calibrage au repos et qualité automatique** : repères neutres, caméra droite, cadrage/lumière/flou, contrôle du plan ; n'accepter que ce qui est réellement observable.
2. **Pics robustes et correction humaine** : vérifier les pics sur plusieurs images, afficher les données brutes, corriger/refuser des repères avec provenance et recalcul.
3. **Parcours de séance guidé** : enchaîner les mouvements choisis, comparaison descriptive gauche/droite sous conditions comparables, fiche courte par essai ; pas de prescription automatique.
4. **Retour distant plus stable** : comparer Wi‑Fi/Ethernet, cadence adaptative et budget de latence ; tests de coupure, reconnexion volontaire, détection des changements de personne.
5. **Revue et validation professionnelle** : décision explicite, identité du réviseur et historique ; avant patients seulement, gestion protégée des dossiers et des accès.

Le live peut observer la qualité du suivi de tous les parcours, sans les valider. Le contrat de rédaction finale multi-protocoles reste une étape séparée ; les modèles et leur FP4 sont inchangés.
