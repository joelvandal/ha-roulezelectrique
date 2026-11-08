# Club Roulez Électrique — Intégration Home Assistant

Connectez vos bornes de recharge [Club Roulez Électrique](https://roulezelectrique.club) à Home Assistant : télémétrie en direct pour chaque borne de votre compte, plus le contrôle à distance (démarrer/arrêter, limite de courant de charge, verrou) pour les vendeurs qui le permettent.

---

## Bornes prises en charge

Un appareil HA **par borne**, plus un appareil **Compte** pour les statistiques du programme. Ce que chaque vendeur reçoit :

| Vendeur | Capteurs télémétrie | En ligne | En charge | Branché | Démarrer/Arrêter | Curseur de courant | Verrou |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **OCPP** (toute borne OCPP 1.6J connectée à la plateforme) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Wallbox** (compte lié) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **IYILO** (anciennement AVE ; compte lié) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Tesla** Wall Connector (compte lié) | ✅ | ✅ | ✅ | ✅ | ✅² | — | — |
| **Sigenergy AC** (compte lié) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Sigenergy DC** (compte lié) | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |

La disponibilité du contrôle est décidée **côté serveur** (les indicateurs `controllable` / `current_limit_controllable` de la plateforme) : une borne OCPP doit être en ligne (WebSocket actif), et les vendeurs infonuagiques (Wallbox, IYILO, Sigenergy AC et DC, Tesla) nécessitent un compte lié actif (Tesla exige aussi le consentement au contrôle à distance, voir plus bas). Quand le contrôle est temporairement indisponible, l'entité existe mais s'affiche comme *indisponible* — elle n'échoue jamais silencieusement.

**Nouveau (v0.11.1) :** les nouveaux contrôles (démarrer/arrêter, courant maximal) apparaissent automatiquement dès qu'une borne devient contrôlable, sans recharger l'intégration. Il en va de même pour une borne ajoutée à votre compte plus tard, et pour une borne dont le contrôle n'est offert qu'une fois en ligne (par exemple une borne hors ligne au démarrage de Home Assistant) : son interrupteur et son curseur apparaissent dès qu'elle est contrôlable. Une borne retirée de votre compte conserve ses entités, affichées comme indisponibles, jusqu'à ce que vous les supprimiez ou rechargiez l'intégration.

**Nouveau (v0.11.0) :** l'intégration s'appelle maintenant **Club Roulez Électrique** et utilise le logo officiel du Club ainsi que sa feuille comme icône. Changement de nom et d'images seulement : aucune modification fonctionnelle.

**Nouveau (v0.10.1) :** le curseur « Courant max (EVduty) » fonctionne maintenant pendant une recharge en cours (il était refusé jusque-là) ; la borne n'est plus redémarrée. Pour dépasser la valeur d'installation, la confirmation reste requise dans l'application ou le tableau de bord.

**Nouveau (v0.10.0) :** les valeurs en direct d'IYILO et de Tesla sont maintenant rafraîchies par la plateforme environ toutes les 2 minutes tant que Home Assistant est utilisé (elles restaient vides si le site ou l'application n'était pas ouvert), et les Tesla Wall Connector obtiennent l'**interrupteur démarrer/arrêter**. ² Démarrer/arrêter sur Tesla active/désactive l'horaire « recharge permise » propre au Wall Connector — cela **remplace tout horaire de recharge réglé dans l'application Tesla**, et exige un compte lié avec le consentement au contrôle à distance (reliez Tesla de nouveau si l'interrupteur est absent). Les bornes BEQ et EVduty (API) ne sont pas couvertes.

**Nouveau (v0.9.0) :** trois réglages propres aux bornes IYILO — Plug & Charge, fuseau horaire et redémarrage — voir *Entités* ci-dessous.

**Nouveau (v0.5.0) :** Sigenergy AC et DC obtiennent maintenant l'interrupteur de démarrer/arrêter (via le même appel synchrone que Wallbox/IYILO — la plateforme distingue AC/DC en coulisses). Seule Sigenergy AC garde le curseur de courant maximal ; il n'existe pas d'API de limite de courant pour le DC.

Les capteurs supplémentaires par vendeur (ci-dessous) sont créés **uniquement pour les bornes capables de les rapporter** — un Tesla Wall Connector n'obtient jamais de capteur de température, un Wallbox jamais de capteur NIV, etc. C'est décidé par la plateforme, borne par borne (via la liste `capabilities` renvoyée par le serveur pour chaque borne), ce qui reste juste automatiquement à mesure que la plateforme ajoute des vendeurs ou de nouvelles capacités — y compris le capteur binaire **Branché**, lui aussi entièrement piloté par cette liste depuis la v0.5.0 (voir ci-dessous).

| Vendeur | Énergie/sessions à vie | Courant mesuré | Température | Batterie % | Dernière connexion | Début de session | Vitesse de charge / Autonomie ajoutée | Type de connexion | NIV |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **OCPP** | ✅ | — | rare¹ | rare¹ | ✅ | ✅ | — | — | — |
| **Wallbox** | ✅ | — | — | — | ✅ | — | ✅ | — | — |
| **IYILO** | ✅ | — | — | — | — | ✅ | — | — | — |
| **Tesla** | ✅ | — | — | — | — | — | — | — | ✅ |
| **Sigenergy AC** | ✅ | ✅ | ✅ | — | — | ✅ | — | ✅ | — |
| **Sigenergy DC** | ✅ | — | — | — | — | — | — | — | — |

¹ Seules les bornes qui envoient réellement une lecture de température/SoC dans leurs rapports afficheront une valeur ; la plupart ne le font pas. Le capteur est créé pour chaque borne OCPP (afin qu'il apparaisse dès qu'une borne commence à le rapporter) mais reste *inconnu* jusque-là.

---

## Entités

### Par borne

**Capteurs**
- **Puissance** (kW)
- **Énergie de session** (kWh) — énergie livrée dans la **session en cours** ; se remet à zéro à chaque session
- **Statut** (énum : available, preparing, charging, suspended_evse, suspended_ev, finishing, reserved, unavailable, faulted) — les codes de diagnostic propres au vendeur (ex. codes Tesla Wall Connector, diagnostics Sigenergy), quand la plateforme en a pour cette borne, sont joints en attributs supplémentaires de ce capteur
- **Courant** (A)
- **Tension** (V)
- **Dernière session** (horodatage)
- **Énergie totale** (kWh) — énergie cumulée sur toutes les sessions jamais enregistrées pour cette borne ; voir *Tableau de bord Énergie* ci-dessous
- **Sessions totales** (compte)
- **Température** (°C) — OCPP (quand rapportée) et Sigenergy AC
- **Niveau de batterie** (%) — OCPP seulement, quand la borne le rapporte (rare)
- **Courant mesuré** (A) — Sigenergy AC seulement ; le tirage *réel*, distinct du capteur « Courant » ci-dessus, qui reste la limite configurée
- **Dernière connexion** (horodatage) — OCPP, Wallbox
- **Début de session** (horodatage) — OCPP, IYILO, Sigenergy AC (non disponible depuis l'infonuagique Wallbox)
- **Vitesse de charge** (km/h) et **Autonomie ajoutée** (km) — Wallbox seulement
- **Type de connexion** (ethernet/wifi/cellulaire) — Sigenergy AC seulement
- **NIV** — Tesla seulement, le NIV du véhicule connecté
- **Signal Wi-Fi** (%) — OCPP seulement ; activé par défaut
- **Charge maximale** (%) — OCPP seulement ; désactivé par défaut
- **Charge minimale** (%) — OCPP seulement ; désactivé par défaut
- **Limite de courant de la borne** (A) — OCPP seulement ; désactivé par défaut
- **Intervalle de battement** (s) — OCPP seulement ; désactivé par défaut
- **Intervalle de mesure** (s) — OCPP seulement ; désactivé par défaut

Les capteurs de télémétrie (puissance, énergie, courant, tension, température, niveau de batterie, courant mesuré, vitesse de charge, autonomie ajoutée) passent *indisponibles* quand la borne est hors ligne ou que ses données sont périmées. Statut, dernière session, énergie/sessions à vie, dernière connexion, début de session, type de connexion, NIV et les six diagnostics de configuration OCPP ci-dessus restent lisibles même quand la borne est hors ligne.

**Diagnostics de configuration OCPP (nouveau en v0.6.0)** — les six capteurs ci-dessus (Signal Wi-Fi, Charge maximale, Charge minimale, Limite de courant de la borne, Intervalle de battement, Intervalle de mesure) sont lus par le serveur directement dans la configuration `GetConfiguration` que la borne rapporte d'elle-même, environ une fois par heure — ce ne sont **pas** des mesures en direct, une valeur peut donc avoir jusqu'à une heure de retard sur la réalité (c'est aussi pourquoi ils restent lisibles hors ligne, contrairement aux capteurs de télémétrie ci-dessus). Ils sont créés **par borne**, pas par vendeur : uniquement pour la borne OCPP précise qui a effectivement rapporté cette clé avec une valeur plausible. La plupart des bornes de la flotte (EVduty/Elmec) ne rapportent que l'intervalle de battement et l'intervalle de mesure ; les bornes Wallbox Pulsar Plus qui parlent OCPP rapportent en plus le signal Wi-Fi, la charge min/max et la limite de courant. Seul **Signal Wi-Fi** est activé par défaut ; les cinq autres sont désactivés à l'installation — activez-les dans les paramètres de l'entité si vous le souhaitez. Une borne liée depuis moins d'une heure n'a pas encore eu sa configuration lue par le serveur : ces entités n'existent donc pas encore pour elle. Ils apparaissent d'eux-mêmes à la mise à jour suivant cette première lecture horaire (depuis la v0.11.1 ; les versions précédentes exigeaient un rechargement).

**Capteurs binaires**
- **En ligne** (connectivité) — tous les vendeurs
- **En charge** — tous les vendeurs
- **Branché** — piloté par la plateforme (liste `capabilities`) plutôt que par une liste de vendeurs codée en dur ; couvre actuellement OCPP, Wallbox, IYILO, Tesla et Sigenergy AC/DC

**Contrôles**
- **Interrupteur de charge** (démarrer/arrêter) — OCPP, Wallbox, IYILO, Sigenergy AC et DC, et (v0.10.0+) les Tesla Wall Connector dont le compte permet le contrôle à distance — l'interrupteur est créé dès que la plateforme déclare la borne contrôlable. Les commandes sont confirmées de bout en bout : les commandes OCPP sont interrogées jusqu'à ce que la borne les accepte/rejette ; les autres vendeurs répondent de façon synchrone (le résultat est déjà connu à la réponse) ; les échecs apparaissent en notification d'erreur HA et l'interrupteur revient en arrière (pas de faux état).
- **Courant maximal** (curseur numérique, A) — OCPP (smart-charging `SetChargingProfile`), Wallbox, IYILO, Sigenergy AC. **Les bornes EVduty/Elmec ont un curseur distinct** (« Courant max (EVduty) ») : le serveur les pilote avec une seule commande de profil de charge, au format accepté par le fabricant. Appliquer une valeur **ne redémarre pas** la borne et **fonctionne pendant une recharge** (corrigé en v0.10.1 ; les versions précédentes étaient refusées pendant une recharge). Son plafond est la valeur d'installation relevée sur la borne, jamais au-dessus. Une borne affiche l'un OU l'autre curseur, jamais les deux. Si vous aviez installé la v0.11.0 et qu'une borne EVduty/Elmec affiche un second curseur « Courant max » en permanence indisponible, c'est un reste de cette version : vous pouvez le supprimer sans risque (paramètres de l'entité, puis Supprimer) ; le curseur « Courant max (EVduty) » est celui qui fonctionne. Les limites viennent du serveur (typiquement 6 A jusqu'au maximum de la borne). Depuis la v0.6.0, quand une borne OCPP rapporte elle-même sa limite de courant matérielle dans sa configuration, ce maximum est utilisé comme plafond — par exemple, les bornes Wallbox Pulsar Plus en OCPP qui rapportent 48 A obtiennent un plafond de 48 A au lieu du maximum générique de 32 A. Non disponible pour Sigenergy DC (aucune API de limite de courant côté DC).
- **Interrupteur de verrou** — Wallbox seulement (activé = verrouillé).
- **Interrupteur Plug & Charge** — **nouveau en v0.9.0, IYILO seulement.** Active/désactive le réglage Plug & Charge de la borne. Classé dans la section Configuration de l'appareil (un réglage, pas un contrôle de charge principal).
- **Fuseau horaire** (liste déroulante) — **nouveau en v0.9.0, IYILO seulement.** Affiche et modifie le fuseau horaire configuré sur la borne. La liste des choix vient de la plateforme ; si la borne est actuellement réglée sur un fuseau horaire que la plateforme n'offre pas comme choix, cette valeur reste affichée quand même (jamais remplacée silencieusement par autre chose) — elle est simplement impossible à sélectionner à nouveau dans la liste tant que la plateforme ne l'offre pas. Classé dans Configuration.
- **Redémarrer** (bouton) — **nouveau en v0.9.0, IYILO seulement.** Redémarre physiquement la borne et **interrompt toute session de charge en cours** — c'est une action réelle et perturbatrice, pas une simple actualisation. Home Assistant ne demande aucune confirmation avant d'exécuter l'appui sur un bouton, et un bouton peut aussi être déclenché par un script, une automatisation ou un assistant vocal. Il est donc **désactivé par défaut** : allez le chercher dans la section Configuration de l'appareil et activez-le une fois, délibérément, avant qu'il ne puisse être pressé. Il n'est **pas** bloqué pendant une session en cours : une borne coincée dans une session fantôme est justement le cas où il faut la redémarrer.
- **Actualiser** (bouton) — **nouveau.** Toutes les bornes. Appuyez dessus pour forcer une vérification immédiate des données du serveur — la seule entité de cette intégration qui ne dépend jamais de `controllable`/du vendeur et qui est toujours disponible. Utile pour un changement fait en dehors de Home Assistant (ex. depuis l'application mobile Club Roulez Électrique), qui n'apparaît autrement dans HA qu'au prochain sondage prévu (voir **Intervalle de mise à jour** ci-dessous). L'action native de Home Assistant Core « Actualiser l'entité » (`homeassistant.update_entity`, accessible depuis la fenêtre de détail de l'entité ou dans les automatisations/scripts) fait exactement la même chose et fonctionne aussi — ce bouton est simplement un raccourci en un clic depuis l'application compagnon.

Les trois réglages IYILO ci-dessus (Plug & Charge, fuseau horaire, redémarrage) deviennent tous *indisponibles ensemble* dès que les réglages de cette borne ne sont pas contrôlables en ce moment (compte IYILO inactif ou borne retirée) — une condition distincte de la disponibilité de l'interrupteur de charge lui-même, puisqu'une borne peut rester joignable pour le contrôle de charge alors que ses réglages ne le sont pas.

### Appareil Compte

- **Récompenses** (CAD) : total, client, ambassadeur, filleul, parrain
- **Invitations** : en attente, acceptées, référées
- **Énergie à vie** (kWh) — un cumul à vie sur toutes vos bornes qui peut occasionnellement être ajusté à la baisse quand la plateforme corrige des données de session dupliquées ou erronées (un recomptage périodique, pas un compteur en direct) ; voir *Tableau de bord Énergie* ci-dessous
- **Nombre de bornes**

---

## Tableau de bord Énergie

Utilisez le capteur **Énergie totale** de chaque borne comme source lorsque vous ajoutez une borne au tableau de bord Énergie de Home Assistant. C'est un cumul à vie qui peut occasionnellement être ajusté à la baisse quand la plateforme corrige des données de session dupliquées ou erronées (un recomptage périodique, pas un compteur en direct) — il reste le bon capteur pour le tableau de bord Énergie. Le capteur **Énergie de session** se remet à 0 au début de chaque session de charge, il n'est donc **pas** approprié ici (voir *Limitations connues*).

---

## Prérequis

- Home Assistant **2024.11.0** ou plus récent
- Un compte Club Roulez Électrique sur [roulezelectrique.club](https://roulezelectrique.club)
- Un jeton d'API depuis votre profil (voir Configuration)

---

## Installation

### Via HACS (recommandé)

1. Ajoutez ce dépôt comme dépôt personnalisé HACS :
   - HACS → Intégrations → ⋮ → Dépôts personnalisés
   - URL : `https://github.com/joelvandal/ha-roulezelectrique`
   - Catégorie : Integration
2. Cherchez « Club Roulez Électrique » et installez.
3. Redémarrez Home Assistant.

### Manuel

1. Copiez `custom_components/roulezelectrique/` dans le dossier `config/custom_components/` de votre HA.
2. Redémarrez Home Assistant.

---

## Configuration

### Étape 1 — Obtenir votre jeton d'API

1. Connectez-vous sur [roulezelectrique.club](https://roulezelectrique.club).
2. Allez dans **Profil → Intégrations → Home Assistant**.
3. Cliquez **Activer**. Votre jeton s'affiche **une seule fois** — copiez-le maintenant.

### Étape 2 — Ajouter l'intégration dans HA

1. Paramètres → Appareils et services → Ajouter une intégration.
2. Cherchez « Club Roulez Électrique ».
3. Collez votre jeton d'API et cliquez sur Soumettre — c'est tout (l'URL de la plateforme est intégrée).

Vos bornes apparaissent comme appareils HA en quelques secondes. L'interface est disponible en **français et en anglais**.

---

## Options

Après la configuration, ouvrez les paramètres de l'intégration pour ajuster :

- **Intervalle de mise à jour** (30–900 secondes, défaut 30) : à quelle fréquence HA interroge pour de nouvelles données. L'intégration ralentit automatiquement si le serveur la limite en débit. C'est aussi la seule façon dont un changement fait en dehors de Home Assistant (ex. depuis l'application mobile Club Roulez Électrique) est détecté — voir le bouton **Actualiser** ci-dessous pour forcer une vérification immédiate plutôt que d'attendre.

---

## Gestion du jeton

Votre jeton d'API peut être renouvelé ou révoqué à tout moment depuis **Profil → Intégrations → Home Assistant** sur la plateforme. Si le jeton devient invalide, l'intégration arrête d'interroger et vous invite à vous **ré-authentifier** directement dans HA (Paramètres → Appareils et services) — collez simplement le nouveau jeton.

---

## Diagnostics

L'intégration prend en charge le téléchargement des diagnostics intégré à HA (Paramètres → Appareils et services → Club Roulez Électrique → Télécharger les diagnostics). Le fichier est **caviardé** : le jeton d'API, l'identifiant du compte, ainsi que le nom, le numéro de série et le NIV de chaque borne y sont masqués. Le reste (statut, puissance, fournisseur, modèle, capacités, totaux de récompenses) est conservé pour faciliter les rapports de bogue.

---

## Mise à jour

- **Depuis v0.10.x :** renommée **Club Roulez Électrique**, avec le logo officiel du Club et sa feuille comme icône. Rien à refaire : vos entités, leur historique, vos tableaux de bord et automatisations sont inchangés (les identifiants d'entités sont conservés). L'appareil Compte est renommé « Club Roulez Électrique » automatiquement au prochain rechargement ; un appareil que vous avez renommé vous-même garde votre nom. Les noms affichés des entités du compte suivent le nom de l'appareil, mais leurs identifiants ne changent pas. Le titre de l'intégration dans Paramètres → Appareils et services garde son ancien texte pour les installations existantes ; seules les nouvelles configurations reçoivent le nouveau titre.

- **Depuis v0.2.4 ou antérieur :** les capteurs au niveau du compte (récompenses, invitations, énergie à vie, nombre de bornes) avaient un identifiant interne dupliqué qui est corrigé automatiquement au premier rechargement de l'intégration après la mise à jour — vos entités existantes, leur historique et tout tableau de bord/automatisation qui les référence sont préservés (aucun réajout, aucune nouvelle entité).
- **Depuis v0.3.x :** les nouveaux capteurs par borne (Énergie totale, Sessions totales, Température, Niveau de batterie, Courant mesuré, Dernière connexion, Début de session, Vitesse de charge, Autonomie ajoutée, Type de connexion, NIV) apparaissent automatiquement au premier rechargement pour chaque borne dont le vendeur peut les rapporter — aucun réajout, aucun changement de configuration nécessaire. Les identifiants d'entités existants ne changent pas, mais la classe d'état du capteur **Énergie à vie** au niveau du compte passe de `total_increasing` à `total` (il peut maintenant être corrigé à la baisse, ex. après un nettoyage de données, sans que Home Assistant l'interprète à tort comme une remise à zéro du compteur). Home Assistant peut journaliser un avis ponctuel « les métadonnées statistiques ont changé » pour ce capteur : c'est normal et sans conséquence, ses statistiques à long terme et son historique continuent de fonctionner normalement.
- **Depuis v0.4.x :** Sigenergy AC et DC obtiennent maintenant l'interrupteur démarrer/arrêter (contrôle à distance, compte lié actif requis), et le capteur binaire **Branché** couvre désormais aussi OCPP et Sigenergy AC/DC (auparavant limité à Wallbox/IYILO/Tesla). Ces nouvelles entités apparaissent automatiquement au premier rechargement pour les bornes concernées — aucun réajout, aucun changement de configuration nécessaire.
- **Depuis v0.5.x :** six nouveaux capteurs de diagnostic OCPP (Signal Wi-Fi, Charge maximale, Charge minimale, Limite de courant de la borne, Intervalle de battement, Intervalle de mesure) apparaissent pour les bornes OCPP admissibles au premier rechargement suivant la lecture horaire de leur configuration — aucun réajout, aucun changement de configuration nécessaire (voir *Entités* ci-dessus pour le détail par borne et l'activation par défaut).

---
- **Depuis v0.9.x :** les Tesla Wall Connector obtiennent l'interrupteur démarrer/arrêter (seulement si le compte Tesla a été lié avec le consentement au contrôle à distance — sinon reliez Tesla de nouveau), au premier rechargement. Les capteurs IYILO et Tesla portent maintenant des valeurs même quand l'application/le site est fermé.
- **Depuis v0.8.x :** les bornes IYILO obtiennent trois nouvelles entités — l'interrupteur **Plug & Charge**, la liste **Fuseau horaire** et le bouton **Redémarrer** (voir *Entités* ci-dessus), qui apparaissent automatiquement au premier rechargement après la mise à jour, sauf **Redémarrer**, livré désactivé et à activer à la main. Cette intégration obtient aussi son tout premier type d'entité **liste déroulante (select)** : si une automatisation ou un script filtre les entités par domaine (ex. seulement `switch.*`), sachez qu'une entité `select.*` existe désormais par borne IYILO. Aucun autre vendeur n'est concerné. Ces entités exigent aussi que la mise à jour côté plateforme soit en service ; d'ici là, elles n'apparaissent tout simplement pas.

## Limitations connues

- **Les valeurs IYILO et Tesla se rafraîchissent environ toutes les 2 minutes**, pas toutes les 30 s, et seulement tant que Home Assistant sonde activement (la plateforme cesse de rafraîchir quelques minutes après la dernière sonde). IYILO n'autorise qu'une seule connexion par compte : un rafraîchissement peut occasionnellement vous déconnecter de l'application IYILO. Démarrer/arrêter sur Tesla **remplace l'horaire configuré dans l'application Tesla** (il passe par l'horaire de recharge propre au Wall Connector) ; il n'y a pas de curseur de courant pour Tesla.
- Les bornes Sigenergy DC obtiennent l'interrupteur démarrer/arrêter mais **pas** le curseur de courant maximal — il n'existe pas d'API de limite de courant côté DC.
- Le capteur **Énergie de session** mesure la session de charge en cours seulement et se remet à 0 à chaque session — ce n'est **pas** un compteur cumulatif à vie, il n'est donc **pas recommandé comme source du tableau de bord Énergie de Home Assistant** (le tableau de bord Énergie attend un total toujours croissant). Le capteur **Énergie totale** de chaque borne (et celui du compte) est le capteur cumulatif — voir *Tableau de bord Énergie* ci-dessus.
- **La force du signal WiFi via l'API infonuagique d'un vendeur n'est disponible pour aucune borne, chez aucun vendeur.** L'appareil de Tesla rapporte bien une valeur de force du signal, mais seulement via son API réseau locale sur le même LAN — l'API infonuagique que lit cette plateforme ne la transporte pas, il n'y a donc aucun moyen de l'exposer ici pour Tesla ou tout autre vendeur par cette voie. Le capteur diagnostic **Signal Wi-Fi** décrit ci-dessus est distinct : il vient de la configuration `GetConfiguration` que la borne OCPP rapporte elle-même (ex. Wallbox Pulsar Plus en OCPP), pas d'une API infonuagique en direct, et n'existe donc que pour les bornes OCPP qui la rapportent.
- Les capteurs **Température** et **Niveau de batterie** sur les bornes OCPP n'affichent une valeur que pour le petit nombre de bornes dont le micrologiciel rapporte réellement ces lectures ; la plupart restent *inconnues* en permanence, ce qui est attendu (le capteur est tout de même créé afin qu'il commence à fonctionner dès qu'une borne se met à le rapporter).
- L'intégration livre sa propre icône/logo de marque (dossier `brand/`, pris en charge depuis Home Assistant 2026.3.0). Sur les versions HA plus anciennes, l'intégration fonctionne bien mais s'affiche sans logo.
- **Plug & Charge, fuseau horaire et redémarrage sont exclusifs à IYILO** — aucune borne d'un autre vendeur n'obtient ces entités, par conception (la plateforme n'expose pas ce type de réglage pour OCPP, Wallbox, Tesla ou Sigenergy). Le bouton Redémarrer n'a aucune étape de confirmation intégrée (Home Assistant n'en offre pas pour les boutons), raison pour laquelle il est livré désactivé jusqu'à ce que vous l'activiez vous-même. La plateforme n'expose par ailleurs délibérément **aucun** contrôle de mise à jour du micrologiciel, pour aucun vendeur — Redémarrer ne fait que relancer la borne avec son micrologiciel actuel.

---

## Licence

MIT — voir [LICENSE](LICENSE).
