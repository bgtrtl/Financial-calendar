# Calendrier earnings → Proton Calendar

Génère chaque jour un fichier `docs/earnings.ics` avec les dates de publication de résultats de votre watchlist, auquel Proton Calendar s'abonne.

## Mise en place (≈ 10 min)

1. **Clé API** : créez un compte gratuit sur finnhub.io et copiez votre clé.
2. **Dépôt GitHub** : créez un dépôt (ex. `earnings-ics`) et déposez-y :
   - `generate_ics.py`
   - `tickers.txt` (votre liste, un ticker par ligne)
   - `.github/workflows/update-earnings.yml`
3. **Secret** : Settings → Secrets and variables → Actions → New repository secret
   - Nom : `FINNHUB_API_KEY`, valeur : votre clé.
4. **Premier lancement** : onglet Actions → « Mise à jour du calendrier earnings » → Run workflow.
   Le fichier `docs/earnings.ics` apparaît dans le dépôt.
5. **URL du flux** (dépôt public) :
   `https://raw.githubusercontent.com/<votre-compte>/earnings-ics/main/docs/earnings.ics`
6. **Proton** : calendar.proton.me → Paramètres → Calendriers → Autres calendriers →
   « Ajouter un calendrier depuis une URL » → collez l'URL.

## Bon à savoir

- Le dépôt doit être **public** pour que Proton lise l'URL : votre liste de tickers est donc visible. Si c'est gênant, donnez au dépôt un nom neutre.
- Les événements sont sur la journée entière, avec « avant l'ouverture » / « après la clôture » dans le titre. L'heure exacte du call n'est pas fournie par l'offre gratuite.
- Couverture : surtout les actions US. Pour un titre européen, essayez le format Finnhub (ex. `MC.PA`), sans garantie.
- Proton actualise les abonnements environ toutes les 16 h : un changement de date peut mettre jusqu'à une journée à apparaître.
- Pour ajouter ou retirer une valeur : modifiez `tickers.txt` sur GitHub, le flux se met à jour au prochain passage.
