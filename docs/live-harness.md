# Harness continu : mémoire, budgets et retour caméra

Développement des points 1 à 4 : assistant pendant l'essai, mémoire courte, analyses bornées/annulables et retour caméra concis. GPT‑OSS, Qwen 3.6, FP4, URLs, alias et paramètres de génération restent inchangés. Le transport HTTP de l'application est désormais interruptible ; aucun modèle installé ni serveur Windows/SSH configuré ici.

## Fonctionnement

La caméra reste dans le navigateur du Mac ; l'API, la pose et les serveurs LLM tournent sur le Windows à travers le tunnel déjà prévu. Le personnage et le guide restent permanents. Ce montage ne nécessite pas de webcam Windows.

Le navigateur envoie toujours au plus une image de pose à la fois, cadence cible 5 Hz. Un circuit distinct consulte le harness chaque seconde. Il déclenche une analyse asynchrone après au moins trois observations récentes, avec un intervalle minimal de trois secondes entre démarrages LLM. Un seul slot est partagé entre le live et la note finale, sans file d'attente : les fenêtres intermédiaires ne sont pas empilées. Une note demandée pendant une analyse reçoit `409 analysis_busy`, sans démarrer un second traitement. Cela ne promet ni trois secondes de calcul ni une cadence garantie.

L'assistant est décoché par défaut. Sélectionner le modèle existant, « Vérifier » son alias puis activer le live après préparation de la source ou pendant l'essai. La vérification d'alias ne qualifie ni outils, ni vision, ni performances. Toute nouvelle source/séance, fin/arrêt, changement de modèle ou de consentement suspend l'assistant ; une réactivation est volontaire.

## Mémoire et consentement

- Fenêtre bornée à **5 secondes et 25 observations de pose**, selon le temps source et le temps de réception serveur. Pas d'interpolation des lacunes.
- Jusqu'à **deux JPEG de 1 Mo maximum chacun**, espacés d'au moins une seconde de temps source, uniquement après consentement live aux images. Aucun rattrapage d'images capturées avant ce consentement.
- Les images sont ordonnées et portent leurs séquences/horodatages dans l'outil visuel. Elles expirent avec la fenêtre ; révocation visuelle et fin d'essai libèrent le buffer.
- Un instantané indépendant et borné est copié pour l'analyse en cours. Sa mémoire peut subsister jusqu'au retour d'un appel LLM déjà engagé ; arrêter ne retire pas des pixels déjà reçus par le serveur d'inférence.
- Aucun JPEG, prompt, token ni observation live dans les exports finaux. Aucun historique de conversation live ou vidéo sur disque.
- Les données structurées de l'essai existant restent distinctes : au plus 600 poses pour la courbe/mesure finale et une image de preuve. Elles ne sont pas une vidéo conservée et ne constituent pas la mémoire du LLM.
- La purge libère des références en mémoire, sans garantie de zéroisation RAM/swap ou d'effacement des copies faites par un autre processus.

GPT‑OSS reçoit exclusivement les observations structurées. Qwen visuel nécessite **les deux autorisations** : option serveur existante `--qwen-vision`, puis case utilisateur images. Le modèle doit demander l'outil `get_recent_capture_images` ; cette option donne accès aux deux images récentes, pas à une vidéo ni à un contrôle libre de la webcam.

## Sortie volontairement limitée

Outils de lecture seulement : `get_live_observation`, `get_protocol_definition` et, si autorisé, `get_recent_capture_images`. Arguments `{}` exclusivement ; aucune commande, fichier arbitraire ou autre séance. Au plus quatre tours et quatre appels d'outils.

Le modèle répond uniquement avec `window_ref`, `observation_code` et `requires_professional_review:true`. Les codes autorisés sont `awaiting_frames`, `pose_visible`, `tracking_lost`, `tracking_partial`, `guide_only`. Le code doit correspondre aux observations disponibles ; la phrase française est produite par l'application, jamais du texte médical libre. La vue, la stabilité, le côté et la précision ne sont pas automatiquement validés. Une rotation guidée reste sans angle.

Sans LLM ou en cas d'outil inconnu, format mal formé, mauvaise référence ou code incompatible, l'observation déterministe est conservée. Le résultat expose sa source `llm` ou `deterministic` et un motif de repli sans copier des messages d'erreur externes. Il reste **provisoire**, distinct de la mesure et de la note finale.

Depuis la livraison du **6 octobre 2026**, la note finale, toujours limitée au coude, utilise elle aussi un vocabulaire fermé : `measurement_ref`, `fact_codes` et `requires_professional_review:true`. Les faits doivent correspondre exactement à ceux autorisés par la mesure ; l'application construit la phrase française, sans utiliser le texte libre du modèle ni ajouter de conclusion depuis une image. L'ancien champ `text` est refusé avec maintien du brouillon déterministe. Ce contrat final reste distinct du live et ne valide aucune mesure clinique. Voir [le schéma et les règles de la note](tool-integration.md#note-finale-à-vocabulaire-fermé--6-octobre-2026).

Le retour sur caméra utilise des libellés courts contrôlés : attente d'images, repères visibles, suivi perdu/partiel ou guide seul. Le texte libre reçu du modèle n'est jamais affiché dans ce retour. L'intervalle analysé, le badge provisoire et l'âge restent visibles ; les détails techniques sont repliés dans le panneau. Les annonces accessibles sont dédupliquées. Le bouton « Pause » suspend seulement l'assistant : caméra, pose et personnage continuent. Le personnage reste visible, y compris avec les animations réduites et sur petit écran.

Les résultats de plus de dix secondes sont masqués ; leur âge inclut l'ancienneté de la dernière observation à réception serveur et le calcul, **pas** une mesure complète de latence caméra/réseau. Un budget total couvre tous les tours et outils : **10 secondes maximum en live**, réduit par l'âge des observations, et **30 secondes pour la note finale**. Un résultat dépassant ce budget n'est pas publié comme une réponse du modèle ; le brouillon déterministe reste disponible.

Annulation, expiration et remplacement de séance interrompent l'attente HTTP locale, y compris avant les en-têtes ou pendant une réponse lente. Le contrôle est partagé entre tous les appels de l'analyse, pas renouvelé à chaque tour. Le slot reste réservé jusqu'à la sortie effective du worker ; un client non coopératif ne libère donc pas artificiellement la capacité. **Fermer la connexion ne garantit pas l'arrêt d'une génération GPU déjà lancée par le runtime distant** : le respect de la déconnexion et ses ressources doivent être mesurés sur Windows. Les autres programmes qui utilisent les mêmes LLM ne sont pas arbitrés par ce slot de l'application.

## API et fichiers

- `/api/status` publie les limites `live_harness` et `analysis_limits` : budgets, `max_concurrent:1`, `queue_capacity:0`, transport interruptible.
- `POST /api/harness/live/poll` : `session_id`, `token`, `model_id`, `include_image` booléen, `control_version` entier monotone. Réponse immédiate : `state`, `analysis_state`, `budget_remaining_ms`, `window`, `result`, `result_age_ms` ; aucun pixel.
- `POST /api/harness/live/stop` : `session_id`, `token`, `control_version` plus récent. Une vieille demande de polling ne peut réactiver le consentement ; un vieil arrêt ne doit pas invalider une réactivation plus récente.
- États : `warming_up`, `running`, `ready`, `unavailable`, `stale`, `busy`. Activité : `idle`, `running`, `cancelling`, `busy`. Un `ready` peut être déterministe : lire `observation_source` et `fallback_reason`.

Implémentation : `packages/harness/window.py` (buffer), `packages/harness/live.py` (outils/validation), `packages/harness/control.py` (budget/annulation), `packages/harness/local_llm.py` (transport), `services/api/inference.py` (slot partagé), `services/api/live.py` (coordination), `services/api/state.py` (séance), `services/api/server.py` (API), `apps/web/app.js` (interface).

## Vérifications et limites restantes

Tests synthétiques et clients LLM simulés : fenêtre/consentement/purge, références temporelles, outils et schémas, image opt-in, isolation des tokens, non-blocage de la pose, slot unique, arrêt/changements/réponses tardives, expiration, exports séparés et cycle de vie navigateur.

Vérification locale du 2 octobre 2026 : **97 tests Python et 34 tests JavaScript réussis**, soit 131 au total. Syntaxe JavaScript et `git diff --check` sans erreur ; scan de publication sans artefact interdit ni secret usuel détecté (non exhaustif). Ces résultats utilisent des poses/médias et clients LLM simulés, pas tes modèles/GPU/webcam ni ta liaison SSH réelle. Le contrôle GitHub publié avant ce développement ne qualifie pas ces nouveaux changements locaux. Rejouer :

```sh
python -m unittest discover -s tests -v
node --test tests/test_capture_core.cjs tests/test_web_lifecycle.cjs tests/test_guide.cjs
python -m scripts.check_repository
```

Vérification locale du **5 octobre 2026** après les points 3–4 : **139 tests Python et 56 tests JavaScript réussis (195 au total)**. Serveurs HTTP factices : délais communs, annulation pendant en-têtes/corps lents, concurrence live/note, remplacement/révocation de séance, résultats tardifs et libération des slots. Navigateur avec pixels/pose/modèle synthétiques : retour court et personnage entier à 390 px, pause sans arrêt des images. Diff/syntaxe sans erreur et scan de 82 fichiers sans signal usuel détecté, non exhaustif. Voir [la livraison détaillée](progress-2026-10-05.md). Aucun test réel GPU, caméra, LLM ou SSH ni publication GitHub pour ces changements.

Ces mentions de non-publication décrivent l'état aux **2 et 5 octobre**, pas le statut de la livraison suivante. Le regroupement du live et la sécurisation de la note finale du 6 octobre sont décrits dans [le suivi actuel](progress-2026-10-06.md), avec une distinction entre vérifications locales, publication et CI distante.

À tester sur tes postes : vraie liaison SSH, GPU accessible à la VM, appels aux serveurs GPT‑OSS/Qwen configurés, syntaxe des outils/images réellement prise en charge, délai et mémoire RAM/VRAM, webcam et réseau coupés. Aucun de ces essais matériels n'est acquis ici.

Vérification complète du **6 octobre 2026**, avec la note finale à codes factuels et le correctif de délai socket Windows : **158 tests Python et 56 tests JavaScript réussis (214 au total)**. Les protections live/annulation sont rejouées avec le nouveau contrat final ; aucun modèle réel n'est sollicité. Voir [la livraison et les consignes de versionnement](progress-2026-10-06.md).

Ce premier live décrit le suivi technique. Analyse de l'exécution, segmentation/répétitions, calibration, pics robustes, validation clinique et séances longues restent à développer. Les essais restent limités à deux minutes ; pas de streaming vidéo complet. La détection d'une caméra silencieusement figée et l'invalidation d'une capture incomplète restent à ajouter ; la présence de quelques images exploitables ne garantit pas que tout le mouvement a été reçu. La provenance des exports reste à compléter. L'arrêt physique GPU et les délais du runtime distant restent à qualifier. Un moteur natif de pose bloqué peut retarder une route métier sous verrou ; le budget du transport LLM reste indépendant, mais le watchdog natif de pose n'est pas développé ici.
