# Livraison multi-protocoles et poste webcam distant

État : 2 octobre 2026, branche `camera-guidance-local`. Suite du premier incrément décrit dans `progress-2026-10-02.md`.

## Réalisé

- Catalogue serveur unique de sept mouvements : coude, genou, épaule, hanche, tronc, inclinaison latérale du cou, rotation guidée du cou.
- Personnage permanent : animation adaptée, sens gauche/droite, visage frontal pour les vues de face, version statique si animations réduites.
- Guide de cadrage indicatif sur le retour caméra ; vue et repères requis changent avec le mouvement. La silhouette n'est pas un alignement biomécanique automatique de la personne.
- Adaptateur de pose généralisé aux oreilles, épaules, coudes, poignets, hanches, genoux et chevilles. Filtrage de chaque point puis qualité du protocole choisi : repères du bras non requis pour le genou.
- Conventions 2D en pixels, abstention, réserves systématiques sur les nouveaux protocoles. Inclinaison du cou = proxy tête/épaules, rotation = **aucun angle**.
- Rapports déterministes adaptés au mouvement, courbes pour les mesures quantifiées, preuve du pic concordante ; export JSON version 1.1 avec métadonnées de protocole.
- Aller-retour affiché en ms, P95 et volume JPEG dans les données de test. Anciens repères effacés après 1 s, y compris pendant une requête suivante lente.
- Changement de protocole après résultat : ancienne séance/preuve/note révoquées ; vue de capture à reconfirmer.
- `scripts.start_client` : tunnel OpenSSH lié à 127.0.0.1, contrôle d'empreinte conservé, pas de shell intermédiaire ni d'arguments SSH arbitraires, vérification bornée de disponibilité avant ouverture du navigateur.
- `--remote-client` pour identifier le parcours distant sans exposer l'API au LAN. Caméra dans le navigateur du client ; calcul et modèles existants sur le Windows sans webcam.
- README, conventions, guide des deux postes, checklist GPU, capacités et liste priorisée d'améliorations actualisés.

## LLM préservés

Aucun fichier de `packages/harness/` modifié. Aucun poids, alias par défaut, URL, option de vision ou réglage FP4 changé. GPT‑OSS et Qwen 3.6 restent ceux configurés par l'utilisateur.

Le harness est toujours un contrat de coude : les nouveaux protocoles sont refusés par une garde API (`409`) avant l'appel LLM ; le bouton correspondant est désactivé. Leur compte rendu reste descriptif et déterministe. Cela évite une note de coude appliquée à tort au cou/genou sans étendre implicitement les permissions du harness.

## Vérifications obtenues

- **42 tests Python + 18 tests JavaScript = 60 tests réussis** sur le Mac Intel de développement.
- Tests Python : anciens parcours conservés, angles/conventions et aspect d'image, côté droit, conversion des indices MediaPipe, points masqués/non finis, qualité propre au genou, confirmations et couverture requises, sept parcours terminés, rotation sans nombre/image du pic, API et garde du harness, validation du lanceur SSH.
- Tests JavaScript : capture/annulation existantes, protocole transmis/verrouillé pendant l'essai, assistant refusé hors coude, rotation sans courbe chiffrée, anciennes données retirées, repères périmés, personnage permanent même sans animation et dessin des connexions sélectionnées sans interpolation sur occlusion.
- Interface inspectée dans le navigateur intégré : sept options présentes, vue de face/profil adaptée, personnage visible et limites de rotation affichées. Aucune caméra physique ouverte pour cette vérification.
- Moteur réel : modèle SHA-256 vérifié, initialisation et abstention sur une **image noire**, dans l'environnement de pose local. Pas de preuve de précision ni de détection positive d'une personne. Le délégué CPU du Mac utilise aussi des ressources OpenGL auxiliaires.
- Contrôle de diff/artefacts/secrets usuels avant publication ; scan non exhaustif. Captures de l'interface fictive gardées seulement dans `.cache`, pas dans Git.
- CI Linux/Windows configurée pour les 60 tests sans poids ni GPU. Les résultats d'exécution distante sont à vérifier sur le commit publié ; cela ne teste pas MediaPipe natif, SSH Windows, webcam ou RTX.

## Non réalisé sur le matériel de l'utilisateur

Connexion au Windows GPU, activation d'OpenSSH, modification du pare-feu, authentification, tunnel réel, webcam physique du client, test de mouvements réels et exécution des deux LLM : **non effectués ici**. Installation du profil de pose natif Windows à vérifier, séparément de la CI synthétique.

Les seuils de visibilité, couverture, cadence et retard restent provisoires. Pas de calibration neutre, filtrage des pics, tracking d'identité, correction humaine des points, comptes applicatifs multi-utilisateurs ou validation clinique. Un seul navigateur de test à la fois.

Le test ne rend pas le guide automatiquement « accurate » : comparer à une référence indépendante par mouvement, corriger les erreurs observées et rejouer les cas. Priorités proposées : calibration/qualité automatique, pics robustes/correction humaine, parcours multi-mouvements, stabilité de liaison puis revue professionnelle.
