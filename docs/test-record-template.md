# Fiche d'essai technique — Windows GPU et poste webcam

À copier **hors du dépôt public** pour chaque essai volontaire non clinique.
Ne pas y mettre de patient, photo, clé SSH, jeton, mot de passe ou prompt privé.
Cette fiche complète le JSON exporté ; elle ne valide pas les mesures.
Si une information ne peut pas être vérifiée, écrire « inconnu », pas « conforme ».

## Identifier exactement l'essai

- Date/heure et fuseau :
- Identifiant local de l'essai, sans nom de personne :
- SHA Git sur le Windows après mise à jour et redémarrage :
- SHA Git sur le poste webcam :
- `analysis_provenance.git_commit` et `working_tree_dirty` dans l'export :
- `implementation_sha256` et périmètre déclaré :
- Mode simulé ou MediaPipe réel ; version Python/MediaPipe :
- Hash configuré/réel du modèle de pose, `hash_verified`, options :
- Protocole/version, côté, vue, début/fin, confirmations humaines :
- Navigateur/version, OS/version ; caméra/libellé, résolution, FPS :
- Dimensions JPEG encodées/analysées, cadence, durée et `capture_integrity` :
- Serveur GPU physique ou VM ; GPU/pilote, RAM/VRAM disponibles :
- Mode de liaison (Tailscale/SSH), interruptions observées, sans clé ni adresse privée à publier :

## LLM existants, sans changement de configuration

Pour **chaque** modèle sollicité :

- ID de l'application et alias exact ; endpoint de boucle locale :
- Serveur/runtime et version/build :
- Révision/variante/hash des poids déjà installés :
- Quantification constatée dans la configuration/runtime (FP4 déclaré ne suffit pas) :
- Capacités outils/images effectivement testées ; autorisation d'images :
- `llm_usage` exporté, live ou note ; trace absente/non confirmée le cas échéant :
- Générations actives et RAM/VRAM au repos avant l'essai :
- Pic pendant génération ; heure de l'arrêt/cancel, fin de génération distante :
- Retour à l'activité et à la mémoire additionnelle de repos ; logs techniques sans contenu personnel :

`completion_call_count` compte des tentatives préparées par le harness, pas la
preuve d'un envoi réseau ou d'un calcul réussi. `image_payload_attached` décrit
une pièce jointe préparée, pas sa réception effective. Un alias et un endpoint
ne prouvent ni révision des poids ni quantification. Les poids peuvent rester
chargés en VRAM après arrêt : conserver la ligne de base du runtime.

## Cas à rejouer avant comparaison des performances

| Cas | Résultat local attendu | Ce qu'il faut réellement observer sur Windows |
| --- | --- | --- |
| Essai court normal puis fin naturelle d'un clip | Pas d'interruption fabriquée si réception fraîche ; résultat reste expérimental. | Chronologie, couverture, export/manifestes cohérents. |
| Quelques images puis aucune nouvelle image pendant au moins 3 s | Capture définitivement interrompue, média/assistant arrêtés, valeur `null`, pas de preuve finale. | Coupure caméra/tunnel versus pose absente ; délai réel et absence de réponse ancienne. |
| Gel puis reprise avec une image fraîche | Ancien essai toujours rejeté ; nouvel essai explicitement requis. | Pas de reprise automatique ni de valeur restaurée. |
| Live lent puis pause/arrêt, ou note finale lente puis annulation/remplacement | Ancien résultat jamais publié ; signal d'annulation ; slot non libéré avant retour effectif du worker. | Le runtime arrête-t-il vraiment la génération ? Temps et ressources, pas seulement fermeture HTTP. |
| Live et note sollicités simultanément ou budget dépassé | Un seul slot, pas de file ; refus occupé ou repli déterministe, pas de note tardive. | Pas de plusieurs générations provenant de l'app, budgets 10 s / 30 s ; autres clients à identifier séparément. |
| Perte SSH/runtime, onglet en arrière-plan, caméra débranchée | Interruption/repli explicites ; aucune réponse ancienne réinjectée. | Arrêt effectif, ressources, nouveau départ volontaire après rétablissement. |

Le watchdog de 3 secondes est provisoire. Un moteur de pose natif bloqué n'est
pas isolé dans un processus tuable ; ne pas simuler une panne native définitive
sur une séance personnelle. Des pixels immobiles avec des horodatages frais
restent un cas distinct non détecté. Aucun de ces contrôles ne garantit que le
geste ou l'angle sont corrects.

## Conclusion de l'essai

- Cas réellement exécutés et résultat attendu/observé :
- Défauts reproduits, conditions et fréquence :
- Génération GPU réellement arrêtée : oui / non / inconnu, preuve technique :
- Comparaison précision possible : uniquement si protocole, référence annotée et configuration identifiés :
- Actions restantes et nouveau SHA à retester :

Conserver JSON/TXT et cette fiche localement, sans captures personnelles sur
GitHub. Répéter les cas après changement de code, modèle, pilote ou runtime.
