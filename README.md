# Kiné Motion Local

Application web de capture et d'analyse **expérimentale** de mouvements, pour un poste unique ou deux ordinateurs reliés par un tunnel privé. Les résultats sont des projections 2D, pas des examens cliniques validés. Aucun diagnostic ni programme thérapeutique automatique.

## Ce qui a été développé

- Interface épurée : caméra au centre, contrôles courts, compte rendu et assistant repliés.
- **Personnage permanent** directement sur le retour caméra, animé selon le mouvement choisi. Choix gauche/droite, respect de la préférence « réduire les animations » (personnage statique, jamais masqué).
- Sept parcours : coude, genou, épaule, hanche, tronc, inclinaison du cou et rotation guidée du cou. Cadrage et confirmations adaptés ; détails ci-dessous.
- Ouverture de l'aperçu puis démarrage explicite de l'essai. Sélection de caméra, arrêt immédiat, permission refusée/déconnexion/vidéo illisible gérées.
- Webcam sans audio ou clip local ; images non inversées pour l'analyse, aperçu caméra miroir uniquement.
- Repères du mouvement sélectionné et projection angulaire en direct. Cadre indicatif sur l'image, occlusion, absence de pose et plusieurs personnes entraînent un retour explicite. Un poignet masqué ne bloque pas un essai du genou.
- Horodatage des clips à partir du temps **de la vidéo**, sans inventer de temps pour les images répétées. Une seule requête image à la fois ; caméra bloquée ou vidéo immobile : aucun nouvel échantillon.
- Retour retardé de plus d'une seconde : repères masqués ; anciens repères également effacés après une seconde en attendant la requête suivante. Aller-retour affiché en ms, P95 et volume JPEG dans l'export. Arrêt à deux minutes indépendant d'une requête bloquée.
- Courbe temporelle brute, durée observée, couverture des images et aperçu de l'image du pic. Les lacunes ne sont pas interpolées.
- Export explicite du brouillon `.txt` et des données de test `.json`, sans jeton de séance ni pixels. Les exports restent **non validés**.
- Séance éphémère : toutes les images non retenues sont libérées ; au plus une image de preuve en mémoire serveur. Effacement au nouvel essai, à l'annulation ou après 15 minutes, même sans nouvelle requête.
- Dépendances de pose verrouillées avec hashes, modèle vérifié par SHA-256, diagnostic RAM/GPU/disque, lanceur multiplateforme, tests et contrôle avant publication.
- Lanceur du poste webcam : connexion SSH chiffrée vers le Windows, authentification et contrôle de clé par OpenSSH. API et LLM restent sur la boucle locale du Windows ; aucune webcam requise sur le serveur.

**LLM inchangés : GPT‑OSS et Qwen 3.6 en FP4 restent ton choix.** Aucun poids LLM n'a été installé, remplacé ou reconfiguré. Le harness, ses outils, ses requêtes et les options des serveurs existants n'ont pas été modifiés. Il reste limité au coude ; l'API refuse les autres protocoles avant de l'appeler afin de ne pas rédiger une note de coude pour le cou ou le genou. Les nouveaux mouvements ont leur propre brouillon déterministe. La pose utilise le délégué CPU ; cela ne garantit pas l'absence de ressources graphiques auxiliaires selon la plateforme. Aucune compatibilité, occupation VRAM ou vitesse des deux LLM n'est certifiée ici.

## Mouvements disponibles

| Parcours | Vue demandée | Ce que le prototype décrit |
| --- | --- | --- |
| Coude · flexion | Profil | 180° moins l'angle épaule–coude–poignet |
| Genou · flexion | Profil | 180° moins l'angle hanche–genou–cheville |
| Épaule · élévation latérale | Face | Angle coude–épaule–hanche |
| Hanche · flexion | Profil | 180° moins l'angle épaule–hanche–genou |
| Tronc · inclinaison latérale | Face | Axe médian épaules–bassin relatif à la verticale de l'image |
| Cou · inclinaison latérale | Face | Proxy : axe des oreilles relatif à l'axe des épaules, **pas l'amplitude cervicale** |
| Cou · rotation guidée | Face | Personnage et repères uniquement ; **aucun angle calculé** |

Les calculs corrigent le rapport largeur/hauteur avant l'angle. Les nouveaux protocoles quantifiés sont toujours marqués « capture limitée » avec la réserve de non-validation, même si les repères sont tous présents. Le maximum est brut, sans filtrage ni calibration initiale. Aucun test de force, manœuvre douloureuse/provocative ou diagnostic ajouté. Voir [les conventions et limites](docs/movement-protocols.md).

Le guide et le cadre sont **illustratifs** : ils ne valident pas automatiquement la posture. La direction demandée n'est pas reconnue automatiquement. Les tests serviront à mesurer et corriger les erreurs ; ils ne rendent pas automatiquement le guide précis.

## Ton installation : Windows GPU + poste webcam

Installer la pose uniquement sur le Windows suivant la section suivante, puis :

```powershell
.\.venv\Scripts\python.exe -m scripts.start_local --experimental-pose --remote-client
```

Sur le poste webcam, avec Python et OpenSSH, depuis le dépôt :

```sh
python -m scripts.start_client --server 192.168.1.30 --user mon_compte
```

Remplacer l'IP et le compte par ceux du Windows. Le navigateur du **client** s'ouvre sur `http://127.0.0.1:8765`, ouvre sa webcam et transmet les images au Windows dans le tunnel. Pas de CUDA, de poids ou de moteur de pose à installer sur ce client. OpenSSH Server doit être activé et limité au réseau privé sur Windows : suivre le [guide complet des deux machines](docs/two-machine-setup.md), notamment la vérification d'empreinte et du pare-feu. Cette connexion réelle n'a pas été testée sur ton matériel.

## Essayer immédiatement l'interface

Après récupération de la branche `camera-guidance-local`, depuis la racine du dépôt :

```sh
python -m scripts.start_local --demo
```

Sur macOS/Linux, utiliser `python3` si `python` n'existe pas ; sur Windows, `py -3.11` est également possible. Ouvrir [l'application locale](http://127.0.0.1:8765), **pas** le fichier HTML directement.

Ce mode utilise seulement Python (3.11 conseillé), sans installation de pose. **La démo ignore les pixels et fabrique des repères.** Elle teste le parcours caméra/vidéo, pas la précision des mouvements. Les résultats sont marqués « simulé » dans l'écran et l'export.

1. Choisir le mouvement et le côté anatomique (ou la direction du guide), ouvrir la caméra ou importer un clip.
2. Vérifier la vue de face/profil demandée et la caméra stable. Ces confirmations restent humaines.
3. Démarrer l'essai ; le personnage illustre le geste, sans dosage prescrit. Arrêter en cas de douleur/gêne.
4. Terminer pour voir le résultat ; « Arrêter » interrompt et rejette la mesure. La rotation du cou n'a pas de résultat angulaire.
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

Sans serveur LLM, la capture, les calculs, la courbe et le brouillon déterministe fonctionnent. La note proposée par le LLM reste séparée des mesures et n'est disponible que pour le coude à ce stade. Voir [le harness existant](docs/tool-integration.md).

## Vérifications et diagnostic

```sh
python -m unittest discover -s tests -v
node --test tests/test_capture_core.cjs tests/test_web_lifecycle.cjs tests/test_guide.cjs
python -m scripts.check_repository
```

Dans l'environnement de pose installé :

```sh
python -m scripts.check_install --pose-smoke
python -m scripts.benchmark_pose --frames 30
```

Le microbenchmark utilise **des images vides** : ses chiffres ne représentent ni le suivi d'une personne ni les performances GPU/LLM. Le diagnostic affiche uniquement des informations techniques locales ; aucune photo, aucune identité, aucun secret.

La première livraison avait **26 tests Python et 11 tests JavaScript réussis**, puis [en CI sur Linux et Windows](https://github.com/Matt95354855/kine-motion-local/actions/runs/36998467450), sans poids ni GPU. La suite multi-protocoles/tunnel ajoute des tests de conventions, qualité par mouvement, absence de mesure de rotation, refus des notes hors coude et changements de protocole. Résultats actualisés dans [le suivi multi-protocoles](docs/progress-multi-protocol.md). Interface inspectée dans le navigateur intégré ; modèle réel initialisé et absence de pose vérifiée sur image noire sur Mac. Les tests physiques webcam, SSH entre tes postes, mouvements réels, mode hors réseau et RTX ne constituent pas des validations acquises.

## Suite du projet

- [Travail réalisé et preuves](docs/progress-2026-10-02.md)
- [Points restants avant et après les tests](docs/remaining-work.md)
- [Guide de test sur la machine GPU](docs/gpu-test-checklist.md)
- [Connexion des deux machines](docs/two-machine-setup.md), [protocoles POC](docs/movement-protocols.md)
- [Destination du logiciel](docs/intended-use.md), [périmètre](docs/scope-v1.md), [exigences](docs/requirements.md)
- [Matrice d'acceptation](docs/acceptance-matrix.md), [capacités mesurables](protocols/measurement-capabilities.yaml), [risques](docs/risk-register.md)

Pas encore de dossier patient, base de séances, correction manuelle des repères, validation professionnelle signée, comptage fiable des répétitions, catalogue d'exercices approuvé ou capture smartphone sécurisée. Ne pas publier de captures personnelles, de poids, de certificats ou de dossiers réels sur GitHub. Le choix d'une licence du projet et la revue des licences tierces restent ouverts.
