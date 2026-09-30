# kine-motion-local

Prototype d'assistant local de bilan fonctionnel pour kinésithérapeute. Le projet vise à décrire certains mouvements filmés selon des protocoles définis, à préparer un brouillon de compte rendu et à présenter les preuves nécessaires à sa revue par le professionnel.

Le dépôt est en phase de cadrage : aucun moteur de capture, de mesure ou de génération n'est encore disponible, et aucune performance clinique n'est revendiquée. Le premier parcours visé est supervisé au cabinet, avec une personne et une caméra. Il devra rester utilisable sans Internet et sans modèle de langage.

## Documents de départ

- [Destination et limites d'usage](docs/intended-use.md)
- [Périmètre du premier prototype](docs/scope-v1.md)
- [Exigences vérifiables](docs/requirements.md)
- [Matrice d'acceptation](docs/acceptance-matrix.md)
- [Matrice de mesurabilité](protocols/measurement-capabilities.yaml)
- [Registre initial des risques](docs/risk-register.md)

Les mesures devront être liées à leur capture, protocole, convention de calcul et version logicielle. Une capture insuffisante conduit à une limitation ou à une absence de mesure explicite. Le kinésithérapeute pourra corriger et refuser les sorties proposées, puis valider explicitement un rapport. Les données réelles de patients, captures, secrets et poids de modèles resteront hors du dépôt GitHub.
