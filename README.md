# kine-motion-local

Prototype d'assistant local de bilan fonctionnel pour kinésithérapeute. Le projet vise à décrire certains mouvements filmés selon des protocoles définis, à préparer un brouillon de compte rendu et à présenter les preuves nécessaires à sa revue par le professionnel.

Le dépôt possède maintenant un premier calcul expérimental, exécuté uniquement sur des repères synthétiques. Il n'y a pas encore de capture vidéo, de moteur de pose, d'interface de revue ou de validation clinique. Le premier parcours visé est supervisé au cabinet, avec une personne et une caméra. Il devra rester utilisable sans Internet et sans modèle de langage.

## Exécuter le prototype actuel

Depuis la racine du dépôt, avec Python 3.11 ou plus récent :

```sh
python3 -m packages.harness.demo
python3 -m unittest discover -s tests -v
```

La démo construit trois images de pose fictives, calcule un angle apparent de flexion du coude, rattache la valeur à son image d'origine et imprime un compte rendu marqué « brouillon non validé ». Le code utilise uniquement la bibliothèque standard de Python ; aucun téléchargement ou service externe n'est nécessaire à cette démo.

Les contrôles de qualité sont encore des entrées explicites de l'essai : le logiciel ne sait pas encore détecter automatiquement si la vue est correcte ou si la caméra a bougé. Leur absence bloque la mesure. Les règles provisoires de trois images exploitables et de couverture de 80 % servent uniquement aux tests du prototype ; elles ne sont pas des seuils cliniques validés.

## Documents de départ

- [Destination et limites d'usage](docs/intended-use.md)
- [Périmètre du premier prototype](docs/scope-v1.md)
- [Exigences vérifiables](docs/requirements.md)
- [Matrice d'acceptation](docs/acceptance-matrix.md)
- [Matrice de mesurabilité](protocols/measurement-capabilities.yaml)
- [Registre initial des risques](docs/risk-register.md)

Les mesures devront être liées à leur capture, protocole, convention de calcul et version logicielle. Une capture insuffisante conduit à une limitation ou à une absence de mesure explicite. Le kinésithérapeute pourra corriger et refuser les sorties proposées, puis valider explicitement un rapport. Les données réelles de patients, captures, secrets et poids de modèles resteront hors du dépôt GitHub.
