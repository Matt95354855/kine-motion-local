# Deux machines : Windows pour le calcul, autre poste pour la webcam

Ce parcours ne change ni GPT‑OSS, ni Qwen 3.6, ni le FP4. Le Windows n'a besoin d'aucune webcam.

```text
Poste webcam                      Windows GPU
navigateur + webcam               API Kiné + pose CPU + LLM existants
http://127.0.0.1:8765   ← SSH →    http://127.0.0.1:8765
                 images JPEG →    calcul
                 résultats   ←    calcul
```

L'interface entière est servie par le Windows à travers le tunnel. Les pixels viennent du navigateur du **poste webcam**. L'aperçu reste sur ce poste ; seules les images échantillonnées sont transmises pendant l'essai. Le micro reste désactivé. Une seule personne/un seul navigateur de test à la fois : démarrer une nouvelle séance révoque la précédente.

Le tunnel utilise OpenSSH, avec authentification et contrôle de l'empreinte du Windows. La caméra nécessite un contexte sûr ; l'adresse locale du navigateur le permet, alors qu'une simple adresse HTTP du Windows sur le réseau n'est pas adaptée. [Caméra et contextes sûrs](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [tunnel local OpenSSH](https://man.openbsd.org/ssh).

## 1. Sur le Windows GPU

Installer le dépôt et la pose selon le README. Lancer depuis la racine :

```powershell
.\.venv\Scripts\python.exe -m scripts.start_local --experimental-pose --remote-client
```

Les variables/options de tes serveurs LLM actuels restent celles du README. Les endpoints LLM doivent rester sur `127.0.0.1` **du Windows** ; ils ne sont pas ouverts au réseau ni lancés sur le client. Pour commencer sans les modèles, le parcours de capture fonctionne seul. Pour vérifier uniquement le transport/interface :

```powershell
py -m scripts.start_local --demo --remote-client
```

La démo fabrique les poses : elle ne teste pas la précision. Le drapeau `--remote-client` indique le parcours dans l'interface ; il ne prouve pas à lui seul la présence d'un tunnel et **n'élargit pas l'écoute du serveur**.

## 2. Préparer l'accès SSH sur le Windows

Cette étape système est à effectuer volontairement par le propriétaire du Windows, pas automatiquement par Kiné :

- Installer/activer **OpenSSH Server** selon la [documentation Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse).
- Autoriser le transfert de port local vers `127.0.0.1:8765` dans la configuration administrée du serveur SSH. Si une politique désactive `AllowTcpForwarding`, le tunnel sera refusé.
- Utiliser un compte Windows que tu contrôles, idéalement dédié ; une connexion SSH ordinaire donne aussi accès au compte système, pas seulement à Kiné. Ne pas partager ce compte avec des tiers. Les restrictions de compte/forwarding sont à configurer avec un administrateur avant un usage autre que personnel.
- Préférer une clé SSH protégée. Aucune clé privée ni aucun mot de passe dans Git, dans l'URL ou dans les variables de Kiné.
- Limiter le pare-feu SSH (habituellement port 22) à l'adresse privée du client ou à un VPN privé. Ne pas ouvrir 8765, les ports LLM, ni rediriger ces ports sur la box Internet. Une installation OpenSSH peut créer une règle large : vérifier sa portée.
- Relever l'adresse privée du Windows (`ipconfig`) et le nom exact du compte SSH. Le lanceur accepte un compte simple, pas une notation de domaine `DOMAINE\\utilisateur`.
- Sur le Windows, relever l'empreinte publique à comparer au premier accès :

```powershell
ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub
```

Si cette clé n'existe pas, demander à l'administrateur quelle clé hôte le serveur utilise. Ne jamais accepter une empreinte inconnue au hasard. Le lanceur ne désactive pas la vérification des clés et ne remplace pas `known_hosts`.

## 3. Sur le poste doté de la webcam

Il faut seulement Python 3.11+ et le **client OpenSSH** (`ssh`), pas MediaPipe, CUDA ou les modèles. Cloner la même branche depuis le README, puis lancer :

```sh
python -m scripts.start_client --server 192.168.1.30 --user mon_compte
```

Remplacer l'adresse et le compte par ceux du Windows. Sur macOS/Linux, `python3` peut être utilisé ; sur Windows, `py` convient. Une clé existante peut être choisie avec `--identity /chemin/cle` (chemin Windows accepté également). Un port SSH spécifique se choisit avec `--ssh-port 2222`.

Le terminal SSH demande l'authentification ; Kiné ne collecte pas le secret. Vérifier l'empreinte à partir du Windows avant la première acceptation. Le navigateur s'ouvre seulement lorsque l'API Kiné répond. Garder les deux terminaux ouverts. Ouvrir `http://127.0.0.1:8765` **sur le poste webcam**, choisir le mouvement puis autoriser sa caméra. L'adresse `localhost` pointe alors vers le tunnel local, pas vers un moteur installé sur ce poste.

`Ctrl+C` ferme le tunnel. Le Windows continue de tourner ; les séances expirent au bout de 15 minutes. Pendant un essai, une requête en erreur/timeout interrompt le parcours et coupe la caméra. Vérifier ce comportement sur les navigateurs physiques : délai maximal actuel de requête image 15 s ; les repères expirent après 1 s.

### Sans lanceur Python côté client

Avec OpenSSH installé, le même parcours peut être lancé manuellement :

```sh
ssh -F none -N -T -o StrictHostKeyChecking=ask -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=2 -o ForwardAgent=no -o ForwardX11=no -L 127.0.0.1:8765:127.0.0.1:8765 -l mon_compte 192.168.1.30
```

Puis ouvrir l'adresse locale dans le navigateur du client. Aucun mot de passe dans cette commande.

## Dépannage

- **Port déjà occupé** : choisir un autre `--port`, identique sur le Windows et dans `scripts.start_client` (ex. 8770). Le contrôle Host/Origin reste strict ; des ports différents ne sont pas pris en charge.
- **Refus SSH** : vérifier service, compte, pare-feu, empreinte et politique de transfert ; ne pas contourner la vérification.
- **Tunnel présent mais application absente** : vérifier le terminal Kiné sur Windows et le port. Le lanceur attend tant que le tunnel reste actif ; `Ctrl+C` permet de sortir.
- **Caméra absente sur le Windows** : normal. C'est le navigateur du client qui doit demander la permission.
- **Repères retardés** : préférer Ethernet ou Wi‑Fi stable, consulter les millisecondes affichées et le P95 de l'export. Il s'agit de l'aller-retour JPEG + calcul, pas d'une mesure séparée de la latence réseau.
- **SSH absent côté client** : activer le client OpenSSH par les fonctionnalités facultatives Windows ou le gestionnaire officiel du système. Pas de téléchargement pendant une séance.

## Ce qui est testé et ce qui ne l'est pas

Tests locaux : options du tunnel, refus d'injection d'arguments, écoute locale seulement, contrôle de clé conservé, détection bornée de disponibilité ; API et navigateur testés avec médias simulés. **Aucune connexion à ton Windows, installation SSH, ouverture de pare-feu ou mesure RTX n'a été effectuée ici.** La liaison SSH réelle et la webcam distante font partie de la checklist GPU.

Ce parcours personnel ne constitue pas une solution multi-utilisateur de télésoin. Smartphone, accès HTTPS direct, comptes applicatifs, droits et déploiement public restent hors périmètre.
