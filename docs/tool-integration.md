# Contrat d'intégration des futurs outils de caméra et du LLM

Le harness ne découvre pas librement des outils sur la machine. L'application enregistre explicitement ceux qu'elle autorise pour **la séance courante**. Le modèle ne peut fournir ni identifiant d'un autre dossier, ni chemin de fichier, ni commande système dans les arguments des outils actuels.

## Outil de perception

Un moteur de pose implémente `packages.pose.adapter.PoseEngine` : `detect(jpeg_bytes, timestamp_ms, side) -> PoseObservation` et `close()`. La sortie précise largeur, hauteur, épaule, coude, poignet et, si nécessaire, un motif de rejet. Les coordonnées de repères sont normalisées dans l'image non miroir ; `side` désigne le côté anatomique confirmé par l'utilisateur. Le moteur doit refuser ou signaler explicitement zéro ou plusieurs personnes. L'application conserve au plus une image JPEG de preuve en mémoire et ne stocke pas la vidéo.

L'adaptateur MediaPipe fourni est expérimental. Un autre moteur pourra être branché via une fabrique passée à `SessionManager`, sans modifier la formule géométrique ni le rendu du rapport. La confirmation du plan de vue et de la stabilité reste séparée de la détection de repères.

## Harness pendant la capture

Le nouveau circuit live utilise un instantané indépendant de la fenêtre récente : cinq secondes/25 observations et jusqu'à deux JPEG après consentement. Il expose `get_live_observation`, `get_protocol_definition` et éventuellement `get_recent_capture_images`, avec arguments vides, références temporelles et au plus quatre tours/appels. Le modèle ne fournit que des codes techniques vérifiés ; l'application rend la phrase, sans texte clinique libre. Les images répétées ne sont attachées qu'une fois au contexte, et aucun pixel ni résultat live n'est exporté avec la mesure finale. Consulter [le contrat complet et ses limites](live-harness.md).

Live et note finale partagent un slot sans file. `InferenceControl` impose une seule échéance pour tous les tours/outils (10 s maximum live, 30 s note) ; `ControlledChatClient` utilise `complete_controlled` lorsque disponible. Le transport fourni coupe localement la connexion à l'annulation ou au dépassement. Un adaptateur qui n'implémente que `complete` ne peut pas être interrompu physiquement : son retour tardif est rejeté et le slot reste réservé jusqu'à son retour. Ne pas appeler cette annulation une garantie d'arrêt GPU distant. Aucun paramètre de génération ni poids n'est changé.

## Outils exposés au modèle pour la note finale

Le registre actuel offre `get_session_measurements`, `get_capture_observation`, `get_protocol_definition` et `assemble_report_draft`. Ils n'acceptent aucun argument produit par le modèle et lisent uniquement l'instantané de séance injecté par l'application. Un outil de lecture supplémentaire peut être enregistré par le code avec `ToolRegistry.register_read_only(name, description, handler)` ; le `handler` reçoit le `ToolContext` de cette séance. L'extension doit borner sa sortie, s'abstenir de modifier des données et être testée contre les accès hors séance.

Deux profils sont proposés : `gpt_oss` (texte seulement) et `qwen36` (texte et, éventuellement, image). Les adresses d'inférence sont acceptées uniquement en HTTP loopback explicite, sans redirection ni proxy. Le contrôle « Vérifier le modèle » interroge `/v1/models` sans envoyer de données de séance. Il distingue modèle détecté, nom absent et serveur inaccessible ; il ne prouve ni la qualité du modèle, ni la prise en charge effective des outils ou des images.

Pour Qwen, `--qwen-vision` autorise le mode visuel côté serveur, mais **chaque demande** exige en plus la case d'accord cochée dans l'interface. `get_capture_keyframe` fournit au harness une seule image JPEG de preuve, jamais un chemin arbitraire ou la vidéo entière. Le harness l'insère comme `image_url` en données base64 dans le message adressé au modèle visuel local. Une demande d'image avec GPT-OSS est refusée. Ce chemin attend un test réel de compatibilité avec le modèle et le serveur retenus. Sans consentement visuel, le LLM ne voit que les mesures, motifs de qualité et références de preuve structurés. Les anciens paramètres `--llm-*` restent utilisables pour un profil personnalisé.

### Note finale à vocabulaire fermé — 6 octobre 2026

La note finale reste disponible **pour le coude uniquement**. Le modèle ne produit plus le texte affiché. Il reçoit `supported_fact_codes`, issu de la mesure courante, dans le message initial et l'outil `get_capture_observation`, puis répond avec exactement trois champs :

```json
{
  "measurement_ref": "identifiant-de-la-mesure-courante",
  "fact_codes": ["measurement_recorded", "protocol_experimental"],
  "requires_professional_review": true
}
```

Cet exemple correspond à une mesure de statut `valid` sans réserve de qualité ; l'identifiant doit être celui de la séance réelle autorisée. Le statut impose un seul code :

| Statut de la mesure | Code requis |
| --- | --- |
| `valid` | `measurement_recorded` |
| `limited` | `measurement_limited` |
| `rejected` | `measurement_rejected` |
| `not_performed` | `movement_not_performed` |

`protocol_experimental` est toujours requis. Les motifs de qualité reconnus ajoutent leurs codes ; un motif inconnu devient `quality_limitation_unclassified`, sans recopier son texte. Le catalogue et les phrases françaises sont définis dans [le module de note finale](../packages/harness/final_note.py). Le modèle doit restituer **exactement l'ensemble fourni**, sans ajout, omission ni doublon. L'ordre de sa liste est libre ; l'application fixe l'ordre et la formulation affichés.

Champ supplémentaire, ancienne réponse avec `text`, code incompatible avec la mesure, référence différente ou revue autre que `true` : aucune note proposée (`proposed_note: null`), motif de repli et brouillon déterministe conservé. Les images ne permettent pas d'ajouter une conclusion. Aucun diagnostic, exercice, dosage, angle ou nombre en lettres produit par le modèle n'entre dans la note affichée.

Le harness reste borné à quatre tours et quatre appels d'outils ; noms et arguments imprévus sont refusés. La note est une restitution technique non validée, séparée du compte rendu. `requires_professional_review:true` et la mention de revue ne constituent pas une signature professionnelle : le parcours d'acceptation/correction signé reste à développer. Aucun outil ne permet au LLM de valider un rapport ou un exercice. Le prompt et le contrat de sortie évoluent, **pas** les poids, alias, URLs, quantification FP4 ou paramètres de génération des serveurs existants.

## Informations nécessaires pour brancher les outils fournis

Pour chaque outil : son nom et sa version, son point d'entrée local, le format exact des entrées et sorties, le type de média accepté, sa convention de coordonnées et de latéralité, son modèle ou ses poids, les conditions de licence, ses besoins réseau et son comportement en erreur. Pour le LLM : l'URL loopback, le nom du modèle, la prise en charge des appels d'outils et des images, ainsi que les limites de contexte et de mémoire sur le poste cible.
