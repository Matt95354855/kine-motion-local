# kine-motion-local

Prototype d'assistant local de bilan fonctionnel pour kinésithérapeute. Le projet vise à décrire certains mouvements filmés selon des protocoles définis, à préparer un brouillon de compte rendu et à présenter les preuves nécessaires à sa revue par le professionnel.

Le dépôt possède un parcours expérimental local : webcam ou vidéo choisie dans le navigateur, échantillonnage d'images, moteur de pose interchangeable, calcul d'angle apparent, contrôle de qualité, brouillon déterministe et harness pour LLM local. Aucune précision clinique n'est établie. Il n'y a pas encore de dossier patient, de stockage, de revue clinique complète ni de programme d'exercices.

## Exécuter le prototype actuel

Depuis la racine du dépôt, avec Python 3.11 ou plus récent :

```sh
python3 -m packages.harness.demo
python3 -m unittest discover -s tests -v
```

La démo construit trois images de pose fictives, calcule un angle apparent de flexion du coude, rattache la valeur à son image d'origine et imprime un compte rendu marqué « brouillon non validé ». Le code utilise uniquement la bibliothèque standard de Python ; aucun téléchargement ou service externe n'est nécessaire à cette démo.

Pour vérifier le parcours navigateur et API sans modèle de pose, lancer :

```sh
python3 -m services.api.server --demo-pose
```

Ouvrir ensuite `http://127.0.0.1:8765`. Le mode `--demo-pose` **ignore les pixels** et fabrique une pose : il vérifie le transport et l'interface, pas l'analyse de la vidéo. Le navigateur demande seulement la caméra vidéo, avec `audio: false`, ou lit un fichier vidéo local. Il envoie des JPEG échantillonnés au serveur lié à `127.0.0.1` ; le serveur ne les enregistre pas sur disque. La prévisualisation webcam est en miroir, mais les images analysées ne le sont pas.

Un adaptateur [MediaPipe Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python) peut analyser les pixels si les dépendances compatibles et un modèle `.task` sont déjà installés localement :

```sh
python3 -m services.api.server --pose-model /chemin/vers/pose_landmarker.task --experimental-pose
```

Cet adaptateur n'a pas été exécuté sur le poste cible. Les versions des dépendances, les licences du modèle, la précision et le trafic réseau doivent être vérifiés avant toute capture réelle. La [documentation du paquet MediaPipe](https://pypi.org/project/mediapipe/) indique l'envoi de métriques d'utilisation à Google : le mode réel n'est donc pas déclaré conforme à l'objectif « aucun trafic externe » tant que ce point n'est pas résolu et testé. Aucun modèle n'est téléchargé automatiquement.

Les contrôles de vue de profil et de stabilité de caméra restent des confirmations manuelles après l'essai. S'ils ne sont pas confirmés, aucune valeur n'est publiée. Les règles provisoires de trois images exploitables et de couverture de 80 % servent uniquement aux tests ; elles ne sont pas des seuils cliniques validés. Une deuxième personne détectée entraîne un refus. Les captures ne sont pas conservées, hormis une image de preuve en mémoire jusqu'à l'expiration de la séance ou son remplacement.

Le harness [décrit ici](docs/tool-integration.md) expose uniquement des outils de lecture liés à la séance. Sans LLM, le brouillon déterministe reste disponible. Un serveur local compatible `llama.cpp` peut être configuré avec `--llm-url http://127.0.0.1:8080 --llm-model NOM`. L'option supplémentaire `--llm-vision` autorise l'envoi d'une unique image de preuve à un modèle visuel local compatible ; elle est désactivée par défaut. La note du modèle reste distincte du brouillon et doit être revue. Aucune intégration avec un vrai modèle ou avec les outils futurs de l'utilisateur n'a encore été validée.

## Documents de départ

- [Destination et limites d'usage](docs/intended-use.md)
- [Périmètre du premier prototype](docs/scope-v1.md)
- [Exigences vérifiables](docs/requirements.md)
- [Matrice d'acceptation](docs/acceptance-matrix.md)
- [Matrice de mesurabilité](protocols/measurement-capabilities.yaml)
- [Registre initial des risques](docs/risk-register.md)

Les mesures devront être liées à leur capture, protocole, convention de calcul et version logicielle. Une capture insuffisante conduit à une limitation ou à une absence de mesure explicite. Le kinésithérapeute pourra corriger et refuser les sorties proposées, puis valider explicitement un rapport. Les données réelles de patients, captures, secrets et poids de modèles resteront hors du dépôt GitHub.
