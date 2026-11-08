# Club Roulez Électrique — Intégration Home Assistant / Home Assistant Integration

Connectez vos bornes de recharge [Club Roulez Électrique](https://roulezelectrique.club) à Home Assistant : télémétrie en direct, plus le contrôle à distance (démarrer/arrêter, limite de courant, verrou) pour les vendeurs qui le permettent.

Connect your [Club Roulez Électrique](https://roulezelectrique.club) EV chargers to Home Assistant: live telemetry, plus remote control (start/stop, current limit, lock) for the vendors that support it.

**📖 Documentation complète / Full documentation:**

- 🇫🇷 **[README-FR.md](README-FR.md)** — installation, configuration, entités, limitations, mise à jour
- 🇬🇧 **[README-EN.md](README-EN.md)** — installation, setup, entities, limitations, upgrading

---

**Nouveau / New (v0.11.1) :** Les nouveaux contrôles (démarrer/arrêter, courant maximal) apparaissent automatiquement dès qu'une borne devient contrôlable, sans recharger l'intégration. / New controls (start/stop, max current) now appear automatically as soon as a charger becomes controllable, with no reload.

**Nouveau / New (v0.11.0) :** L'intégration s'appelle maintenant « Club Roulez Électrique » et adopte le logo officiel du Club ; aucun changement fonctionnel. / The integration is now called "Club Roulez Électrique" and uses the official Club logo; no functional change.

**Nouveau / New (v0.10.2) :** Le fichier de diagnostics masque désormais aussi l'identifiant du compte, ainsi que le nom, le numéro de série et le NIV de chaque borne. / The diagnostics file now also masks the account identifier, and each charger's name, serial number and VIN.

**Nouveau / New (v0.10.1) :** Le curseur « Courant max (EVduty) » fonctionne maintenant aussi pendant une recharge, et ne redémarre plus la borne. / The "Max current (EVduty)" slider now also works during a charge, and no longer reboots the charger. Détails / Details: README-FR.md, README-EN.md.

**Nouveau / New (v0.10.0) :** Valeurs en direct IYILO et Tesla rafraîchies par la plateforme (~2 min) ; interrupteur démarrer/arrêter pour les Tesla Wall Connector (remplace l'horaire de l'application Tesla). / IYILO and Tesla live values refreshed by the platform (~2 min); start/stop switch for Tesla Wall Connectors (overrides the Tesla app's schedule). Détails / Details: README-FR.md, README-EN.md.

**Nouveau / New (v0.7.0) :** Le curseur de courant maximal fonctionne enfin sur les bornes EVduty/Elmec, qui rejetaient jusqu'ici la commande OCPP utilisée. Attention : appliquer une valeur redémarre la borne 30-60 s, et la commande est refusée pendant une recharge. Voir la doc complète ci-dessus.

**New (v0.7.0):** The max-current slider finally works on EVduty/Elmec chargers, which until now rejected the OCPP command it used. Note: applying a value reboots the charger for 30-60 s, and the command is refused while a session is in progress. See the full docs above.

## Licence / License

MIT — see [LICENSE](LICENSE).
