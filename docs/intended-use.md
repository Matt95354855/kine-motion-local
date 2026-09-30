# Destination et limites d'usage — version de travail

## Destination envisagée

Le logiciel est destiné à aider un kinésithérapeute, au cabinet et sous sa supervision, à préparer un premier bilan fonctionnel descriptif. Pour des mouvements lents définis par un protocole, il vise à recueillir une vidéo depuis une caméra, à estimer certains indicateurs observables, à présenter leur qualité et leur provenance, puis à préparer un brouillon de compte rendu révisable. Le professionnel décide de la réalisation du mouvement, examine les éléments proposés et valide explicitement toute version finale.

Le parcours initial concerne une seule personne suivie, une seule caméra et un poste local. Une webcam sur ordinateur est la première source de capture envisagée. Un smartphone appairé sur le réseau local est une extension prévue ; le calcul principal reste sur l'ordinateur. Le matériel cible déclaré dans le cahier est une NVIDIA RTX A4500 (20 Go de mémoire GPU) et 28 Go de RAM ; la faisabilité réelle doit être mesurée sur ce poste.

## Nature des sorties

- **Mesure visuelle estimée** : angle apparent, excursion observée, durée ou répétitions, uniquement pour le protocole et les conditions de capture où l'indicateur a été défini. Les unités, le côté anatomique, la convention, le statut de qualité et la preuve sont associés au résultat.
- **Déclaration** : douleur, gêne, restrictions ou contexte rapportés par la personne ou renseignés par le professionnel ; leur source reste visible.
- **Mesure manuelle** : par exemple une amplitude passive ou une mesure instrumentée saisie par le professionnel ; elle n'est jamais attribuée à la caméra.
- **Rédaction et suggestions** : texte de brouillon et, plus tard, candidats issus d'un catalogue d'exercices approuvé. Ils ne valent ni interprétation clinique ni programme patient tant que le professionnel ne les a pas approuvés.

Les sorties `valid`, `limited`, `rejected` et `not_performed` doivent rester distinctes. Un résultat rejeté n'a pas de valeur numérique publiée et porte des raisons compréhensibles. Une qualité de capture acceptable n'est pas une preuve de précision clinique : celle-ci nécessite une validation séparée par protocole et par domaine d'usage.

## Limites actuelles

Le prototype ne conclut pas à une pathologie, une lésion, une cause de douleur, une force musculaire ou une guérison à partir d'images RGB. Il ne prétend pas mesurer une amplitude articulaire anatomique totale à partir d'un angle 2D, ni isoler des structures non visibles. Il ne choisit pas seul un traitement et ne publie pas de programme autonome à domicile. En l'absence de capture adéquate, il doit afficher la limite, proposer une reprise ou laisser une saisie manuelle.

Avant tout usage clinique envisagé, la destination précise, les protocoles actifs, la performance métrologique, la protection des données et les exigences réglementaires applicables devront être établis par les personnes compétentes. Ce document n'attribue aucune qualification ou classe réglementaire au produit.
