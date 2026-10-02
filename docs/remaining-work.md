# Points restants — avant et après les essais

État au 2 octobre 2026. « Test technique » signifie essai volontaire non clinique sur le poste cible. Les tests automatiques ne remplacent ni une validation de vidéo réelle ni un pilote auprès de patients.

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

## Avant de conclure au bon fonctionnement du parcours réel

- Reproduire l'installation sur la machine GPU et consigner système, versions, modèle de pose, commit et pilotes ; vérifier la CI distante.
- Tester une détection **positive** du corps : un succès sur image vide prouve l'initialisation et l'abstention seulement.
- Vérifier le fonctionnement sans accès externe à froid et à chaud : trafic de perception, dépendances et journaux. Aucun firewall système n'a été activé ici.
- Vérifier les licences du code, des poids et des dépendances ; décider la licence du projet avant redistribution d'un paquet offline.
- Finaliser avec un kiné la fiche versionnée **de chaque mouvement** : position, côté/direction, vue, consigne, début/fin, motifs d'arrêt et critères de rejet. Le guide est une illustration, pas un protocole médical approuvé. Ne pas assimiler le proxy du cou à l'amplitude cervicale.
- Annoter indépendamment des clips autorisés : bonnes vues, poignet masqué, hors plan, fond difficile, personne supplémentaire et résultats attendus. Aucun clip personnel dans Git.
- Vérifier physiquement permissions, caméra externe, débranchement, veille, caméra occupée, changement de caméra et rechargement. L'arrêt testé avec média simulé n'est pas certifié pour toutes les caméras.
- Mesurer les images **présentées**, perdues/sautées et traitées : le compteur actuel donne les traitements, pas le nombre exact de pertes caméra. P95 d'aller-retour et volume JPEG ajoutés ; isoler capture/réseau/calcul/écran, tester Wi‑Fi/Ethernet et valider le seuil provisoire d'expiration des repères de 1 s.
- Vérifier SSH sur le Windows : empreinte, compte, restriction du pare-feu, transferts autorisés, port occupé, interruption/reprise et webcam du client. Pas d'API ni de LLM exposés au LAN directement. Pour plusieurs utilisateurs, revoir l'authentification et l'isolation : une nouvelle séance révoque actuellement la précédente.
- Résoudre les changements silencieux de personne après perte de suivi ; le refus de plusieurs personnes ne fournit pas une identité de suivi persistante.
- Compléter la qualité : flou, éclairage, taille corporelle, stabilité/hors-plan automatiques. Le seuil de visibilité/pré­sence de 0,5 est technique et provisoire, pas une borne d'erreur angulaire.
- Filtrer/contrôler les pics parasites : **le maximum reste brut** ; une seule image bruitée peut fournir le pic. Définir filtre, fenêtre, provenance et test sans masquer un vrai maximum.
- Développer une segmentation validée avant de compter les répétitions. L'excursion brute des données de test n'est ni une amplitude passive ni un nombre de répétitions.
- Traduire tous les motifs détaillés de rejet et temporiser les alertes ; vérifier la compréhension des confirmations manuelles.
- Ajouter aux exports hash de pose, paramètres, dépendances et commit. Actuellement : convention, protocole/pipeline de mesure et version de capture sont présents.
- Fixer avant le test les seuils techniques d'acceptation, conditions d'arrêt et cas de non-régression. Les 5 images/s actuelles n'atteignent pas l'objectif provisoire de 15 mises à jour/s du document de départ.

## LLM / harness — volontairement non modifiés

- Inventorier les poids exacts GPT‑OSS/Qwen 3.6 FP4 ; mesurer RAM/VRAM, contexte et chargements sur la RTX sans changer leur configuration à ce stade.
- Tester réponses réelles, outils successifs, disponibilité et pannes ; un alias annoncé ne valide pas ces capacités.
- Finaliser le contrat des futurs outils : schémas, permissions, limites, timeout, panne et preuves.
- Fournir au harness un instantané temporel complet et figé si nécessaire. Le nouveau résumé sert au navigateur/export ; il n'a pas été ajouté au contexte LLM.
- Définir une éventuelle séquence d'images Qwen, nombre maximal, références et consentement. **Qwen reçoit toujours au plus une image**, pas une vidéo ; GPT‑OSS ne reçoit aucune image.
- Traiter réponses tronquées/format de sortie ; contrôler diagnostic, mauvais côté, nombres en lettres, affirmation inventée et rejet décrit comme réussite.
- Annulation et limite totale **côté serveur** du harness : le navigateur bloque les doubles clics/ignore les réponses révoquées, mais ne tue pas une génération déjà lancée chez le LLM.
- Historique technique minimal : versions, outils/preuves, durée, erreurs/repli, sans données identifiantes.
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

Le contrat multi-protocoles du harness pourra être une étape séparée si autorisée ; les modèles et leur FP4 restent inchangés.
