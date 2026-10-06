# Kiné Motion Local

Prototype expérimental de capture et d'analyse du mouvement en local. Les projections 2D ne sont pas des examens cliniques validés ; aucun diagnostic ni programme thérapeutique automatique.

## Version complète à tester

L'application et la livraison du 6 octobre 2026 sont sur **[camera-guidance-local](https://github.com/Matt95354855/kine-motion-local/tree/camera-guidance-local)**. Cette branche `main` contient uniquement ce README d'orientation.

```sh
git clone --branch camera-guidance-local https://github.com/Matt95354855/kine-motion-local.git
cd kine-motion-local
git rev-parse HEAD
```

- [README complet : installation Windows, poste webcam et assistant local](https://github.com/Matt95354855/kine-motion-local/blob/camera-guidance-local/README.md)
- [Livraison du 6 octobre : harness continu et note finale sécurisée](https://github.com/Matt95354855/kine-motion-local/blob/camera-guidance-local/docs/progress-2026-10-06.md)
- [Checklist des tests Windows/GPU et SSH](https://github.com/Matt95354855/kine-motion-local/blob/camera-guidance-local/docs/gpu-test-checklist.md)
- [Travaux et vérifications encore nécessaires](https://github.com/Matt95354855/kine-motion-local/blob/camera-guidance-local/docs/remaining-work.md)

GPT-OSS et Qwen 3.6 FP4 restent configurés comme auparavant. La pose tourne sur le CPU du serveur Windows ; la webcam reste sur le poste utilisateur. Les tests automatiques sont simulés et ne remplacent pas les essais réels GPU, LLM, webcam ou SSH. Conserver le SHA de chaque version testée ; ne pas publier de captures personnelles, secrets ou poids sur GitHub.
