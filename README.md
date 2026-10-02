# Kiné Motion Local

Application web locale de capture et d'analyse **expérimentale** de la flexion du coude. Les résultats sont des angles apparents 2D, pas des mesures cliniques validées. Aucun diagnostic ni programme thérapeutique automatique.

## Ce qui a été développé

- Interface épurée : caméra au centre, contrôles courts, compte rendu et assistant repliés.
- Personnage animé directement sur le retour caméra pour illustrer le geste. Choix gauche/droite, guide masquable, respect de la préférence « réduire les animations ».
- Ouverture de l'aperçu puis démarrage explicite de l'essai. Sélection de caméra, arrêt immédiat, permission refusée/déconnexion/vidéo illisible gérées.
- Webcam sans audio ou clip local ; images non inversées pour l'analyse, aperçu caméra miroir uniquement.
- Repères épaule/coude/poignet et angle apparent en direct. Cadrage, occlusion, absence de pose et plusieurs personnes entraînent un retour explicite.
- Horodatage des clips à partir du temps **de la vidéo**, sans inventer de temps pour les images répétées. Une seule requête image à la fois ; caméra bloquée ou vidéo immobile : aucun nouvel échantillon.
- Retour retardé de plus d'une seconde : repères masqués, indication de retard. Arrêt à deux minutes indépendant d'une requête bloquée.
- Courbe temporelle brute, durée observée, couverture des images et aperçu de l'image du pic. Les lacunes ne sont pas interpolées.
- Export explicite du brouillon `.txt` et des données de test `.json`, sans jeton de séance ni pixels. Les exports restent **non validés**.
- Séance éphémère : toutes les images non retenues sont libérées ; au plus une image de preuve en mémoire serveur. Effacement au nouvel essai, à l'annulation ou après 15 minutes, même sans nouvelle requête.
- Dépendances de pose verrouillées avec hashes, modèle vérifié par SHA-256, diagnostic RAM/GPU/disque, lanceur multiplateforme, tests et contrôle avant publication.

**LLM inchangés : GPT‑OSS et Qwen 3.6 en FP4 restent ton choix.** Aucun poids LLM n'a été installé, remplacé ou reconfiguré. Le harness, ses outils, ses requêtes et les options des serveurs existants n'ont pas été modifiés. La pose utilise le délégué CPU ; cela ne garantit pas l'absence de ressources graphiques auxiliaires selon la plateforme. Aucune compatibilité, occupation VRAM ou vitesse des deux LLM n'est certifiée ici.

## Essayer immédiatement l'interface

Après récupération de la branche `camera-guidance-local`, depuis la racine du dépôt :

```sh
python -m scripts.start_local --demo
```

Sur macOS/Linux, utiliser `python3` si `python` n'existe pas ; sur Windows, `py -3.11` est également possible. Ouvrir [l'application locale](http://127.0.0.1:8765), **pas** le fichier HTML directement.

Ce mode utilise seulement Python (3.11 conseillé), sans installation de pose. **La démo ignore les pixels et fabrique des repères.** Elle teste le parcours caméra/vidéo, pas la précision des mouvements. Les résultats sont marqués « simulé » dans l'écran et l'export.

1. Choisir le côté anatomique, ouvrir la caméra ou importer un clip.
2. Vérifier la vue de profil et la caméra stable. Ces confirmations restent humaines.
3. Démarrer l'essai ; le guide illustre la flexion/extension, sans dosage prescrit.
4. Terminer pour voir le résultat ; « Arrêter » interrompt et rejette la mesure.
5. Consulter les limites puis exporter un brouillon si nécessaire.

Limites techniques : clip ≤ 200 Mo / 2 minutes, essai ≤ 2 minutes / 600 images, cadence cible 5 images/s, JPEG ≤ 1 Mo. Utiliser un MP4 H.264 ou un WebM pris en charge par le navigateur. L'analyse n'est pas une acquisition exhaustive image par image : si le traitement ralentit, des images intermédiaires sont sautées. Le passage de l'onglet en arrière-plan interrompt l'essai par sécurité.

## Installer la pose réelle sur ta machine GPU

Effectuer l'installation **avant** une séance, avec Internet. Le profil testé utilise Python **3.11.14**, MediaPipe **0.10.21**, NumPy **1.26.4** et OpenCV **4.11.0.86**. Le verrou transitif complet est dans `infra/requirements-pose.lock`. L'interface ne requiert ni Node ni compilation ; Node 25.2.0 est utilisé pour ses tests uniquement.

### Windows — PowerShell

Python 3.11.14 n'a pas d'installateur Windows fourni par Python.org ; les versions 3.11 récentes sont publiées sous forme de sources. Pour conserver la même version sans revenir à un ancien Python, utiliser un petit environnement d'installation isolé et le runtime géré par uv. Un Python déjà disponible via `py` sert seulement à préparer cet environnement. [Source Python](https://www.python.org/downloads/release/python-31114/), [installation uv](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
git clone --branch camera-guidance-local https://github.com/Matt95354855/kine-motion-local.git
cd kine-motion-local
py -m venv .setup
.\.setup\Scripts\python.exe -m pip install uv==0.9.8
.\.setup\Scripts\python.exe -m uv python install 3.11.14
.\.setup\Scripts\python.exe -m uv venv --python 3.11.14 .venv
.\.setup\Scripts\python.exe -m uv pip sync --python .\.venv\Scripts\python.exe --require-hashes infra/requirements-pose.lock
.\.venv\Scripts\python.exe -m scripts.prepare_pose --download
.\.venv\Scripts\python.exe -m scripts.check_install --pose-smoke
.\.venv\Scripts\python.exe -m scripts.start_local --experimental-pose
```

### Linux / macOS

```sh
git clone --branch camera-guidance-local https://github.com/Matt95354855/kine-motion-local.git
cd kine-motion-local
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r infra/requirements-pose.lock
.venv/bin/python -m scripts.prepare_pose --download
.venv/bin/python -m scripts.check_install --pose-smoke
.venv/bin/python -m scripts.start_local --experimental-pose
```

Si le dépôt est déjà cloné, récupérer puis sélectionner cette branche en préservant les modifications locales. Les poids de pose sont téléchargés uniquement par la commande explicite `--download` ; ni le lanceur ni une séance ne téléchargent de modèle. Un fichier dont le hash diffère n'est pas remplacé silencieusement.

Si Python 3.11.14 n'est pas déjà installé sur Linux/macOS, uv 0.9.8 peut également préparer ce runtime puis `.venv` avec `uv python install 3.11.14` et `uv venv --python 3.11.14 .venv`. Ne pas remplacer un environnement existant qui contient les serveurs LLM ; la pose reste dans le `.venv` de ce dépôt.

La RTX n'est pas nécessaire à la pose dans ce profil. Le diagnostic relève les informations NVIDIA si `nvidia-smi` est disponible, mais ne lance ni test CUDA ni LLM. **Windows/Linux et la RTX A4500 restent à vérifier sur ton matériel.** Ne pas confondre installation réussie et précision clinique.

MediaPipe reste derrière le drapeau `--experimental-pose` : dépendances natives, licences et trafic sortant doivent être examinés sur le poste cible. L'objectif « aucune sortie réseau pendant la séance » n'est pas encore certifié. Tester avec des scènes fictives puis des mouvements volontaires non cliniques ; ne pas utiliser de données de patients pour ce premier essai.

## Garder tes serveurs LLM existants

Le lanceur conserve les variables et options actuelles : `KINE_GPT_OSS_URL`, `KINE_GPT_OSS_MODEL`, `KINE_QWEN36_URL`, `KINE_QWEN36_MODEL`, ou les options `--gpt-oss-url`, `--gpt-oss-model`, `--qwen-url`, `--qwen-model`. Il ne change ni leur quantification FP4 ni leur configuration d'inférence.

Les serveurs déjà démarrés doivent écouter sur la boucle locale avec les endpoints existants `/v1/models` et `/v1/chat/completions`. Les alias doivent correspondre exactement à ceux annoncés par les serveurs. GPT‑OSS reste textuel. L'envoi d'une image à Qwen demeure un double consentement explicite : option existante `--qwen-vision` et case « Joindre l'image » pour la demande concernée. Aucun envoi automatique.

Sans serveur LLM, la capture, les calculs, la courbe et le brouillon déterministe fonctionnent. La note proposée par le LLM reste séparée des mesures. Voir [le harness existant](docs/tool-integration.md).

## Vérifications et diagnostic

```sh
python -m unittest discover -s tests -v
node --test tests/test_capture_core.cjs tests/test_web_lifecycle.cjs
python -m scripts.check_repository
```

Dans l'environnement de pose installé :

```sh
python -m scripts.check_install --pose-smoke
python -m scripts.benchmark_pose --frames 30
```

Le microbenchmark utilise **des images vides** : ses chiffres ne représentent ni le suivi d'une personne ni les performances GPU/LLM. Le diagnostic affiche uniquement des informations techniques locales ; aucune photo, aucune identité, aucun secret.

Au 2 octobre 2026 : **26 tests Python et 11 tests JavaScript réussis** sur le Mac Intel de développement ; interface inspectée dans le navigateur intégré ; modèle réel initialisé et absence de pose vérifiée sur image noire. La CI synthétique Linux/Windows est ajoutée, sans poids ni GPU ; son résultat distant est à consulter après publication. Les tests physiques webcam, les mouvements réels, le mode hors réseau et la RTX ne constituent pas des validations acquises.

## Suite du projet

- [Travail réalisé et preuves](docs/progress-2026-10-02.md)
- [Points restants avant et après les tests](docs/remaining-work.md)
- [Guide de test sur la machine GPU](docs/gpu-test-checklist.md)
- [Destination du logiciel](docs/intended-use.md), [périmètre](docs/scope-v1.md), [exigences](docs/requirements.md)
- [Matrice d'acceptation](docs/acceptance-matrix.md), [capacités mesurables](protocols/measurement-capabilities.yaml), [risques](docs/risk-register.md)

Pas encore de dossier patient, base de séances, correction manuelle des repères, validation professionnelle signée, comptage fiable des répétitions, catalogue d'exercices approuvé ou capture smartphone sécurisée. Ne pas publier de captures personnelles, de poids, de certificats ou de dossiers réels sur GitHub. Le choix d'une licence du projet et la revue des licences tierces restent ouverts.
