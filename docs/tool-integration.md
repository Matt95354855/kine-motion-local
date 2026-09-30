# Contrat d'intégration des futurs outils de caméra et du LLM

Le harness ne découvre pas librement des outils sur la machine. L'application enregistre explicitement ceux qu'elle autorise pour **la séance courante**. Le modèle ne peut fournir ni identifiant d'un autre dossier, ni chemin de fichier, ni commande système dans les arguments des outils actuels.

## Outil de perception

Un moteur de pose implémente `packages.pose.adapter.PoseEngine` : `detect(jpeg_bytes, timestamp_ms, side) -> PoseObservation` et `close()`. La sortie précise largeur, hauteur, épaule, coude, poignet et, si nécessaire, un motif de rejet. Les coordonnées de repères sont normalisées dans l'image non miroir ; `side` désigne le côté anatomique confirmé par l'utilisateur. Le moteur doit refuser ou signaler explicitement zéro ou plusieurs personnes. L'application conserve au plus une image JPEG de preuve en mémoire et ne stocke pas la vidéo.

L'adaptateur MediaPipe fourni est expérimental. Un autre moteur pourra être branché via une fabrique passée à `SessionManager`, sans modifier la formule géométrique ni le rendu du rapport. La confirmation du plan de vue et de la stabilité reste séparée de la détection de repères.

## Outils exposés au modèle

Le registre actuel offre `get_session_measurements`, `get_capture_observation`, `get_protocol_definition` et `assemble_report_draft`. Ils n'acceptent aucun argument produit par le modèle et lisent uniquement l'instantané de séance injecté par l'application. Un outil de lecture supplémentaire peut être enregistré par le code avec `ToolRegistry.register_read_only(name, description, handler)` ; le `handler` reçoit le `ToolContext` de cette séance. L'extension doit borner sa sortie, s'abstenir de modifier des données et être testée contre les accès hors séance.

Si `--llm-vision` est activé avec un LLM sur `127.0.0.1`, `get_capture_keyframe` fournit au harness une seule image JPEG de preuve, jamais un chemin arbitraire ou la vidéo entière. Le harness l'insère comme `image_url` en données base64 dans le message adressé au modèle visuel local. Ce chemin attend un test réel de compatibilité avec le modèle et le serveur retenus. Sans cette option, le LLM ne voit que les mesures, motifs de qualité et références de preuve structurés.

Le harness limite les appels d'outils, refuse les noms et arguments imprévus, exige une référence de mesure connue et écarte les notes contenant des nombres. Le brouillon déterministe est toujours conservé, même si le modèle échoue. Une note générée reste une proposition distincte ; aucun outil ne permet au LLM de valider un rapport ou un exercice.

## Informations nécessaires pour brancher les outils fournis

Pour chaque outil : son nom et sa version, son point d'entrée local, le format exact des entrées et sorties, le type de média accepté, sa convention de coordonnées et de latéralité, son modèle ou ses poids, les conditions de licence, ses besoins réseau et son comportement en erreur. Pour le LLM : l'URL loopback, le nom du modèle, la prise en charge des appels d'outils et des images, ainsi que les limites de contexte et de mémoire sur le poste cible.
