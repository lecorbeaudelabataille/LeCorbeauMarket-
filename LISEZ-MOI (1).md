# LeCorbeauMarket — serveur + site (prêt à héberger)

Cette version réunit tout en une seule application : le serveur Flask sert
à la fois l'API (comptes, produits, commandes, formations) et le site
(`static/index.html`). Une seule adresse internet suffira pour tout.

## Ce qui a été testé ici avec de vraies requêtes, avec succès
- Le site (`index.html`) est bien servi par le serveur
- Inscription avec paiement déclaré → compte créé mais **bloqué**
- Connexion refusée tant que le compte n'est pas activé
- L'administrateur voit le compte en attente, avec la référence de paiement, et l'active
- Une fois activé, le vendeur se connecte, publie un produit, le voit dans sa boutique
- Sécurité : jeton CSRF obligatoire, mots de passe hachés, rôles vérifiés

## Compte administrateur créé automatiquement au premier démarrage
- Téléphone : `67547490`
- Mot de passe : `changez-ce-mot-de-passe`
**Changez ce mot de passe dès le premier lancement en production.**

## Lancer en local, sur votre ordinateur
```
pip install -r requirements.txt
python3 app.py
```
Puis ouvrez `http://localhost:5000` dans un navigateur.

## Héberger réellement en ligne (étapes vérifiées, Render.com)
Render propose un plan gratuit suffisant pour démarrer. Étapes officielles :
1. Mettez ce dossier dans un dépôt GitHub (créez un compte GitHub si besoin, puis « New repository », et déposez-y les fichiers)
2. Créez un compte sur render.com (inscription possible avec le compte GitHub)
3. Dans le tableau de bord Render : **New → Web Service**, puis connectez votre dépôt
4. Renseignez :
   - **Language** : Python 3
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `gunicorn app:app`
5. Ajoutez une variable d'environnement `SECRET_KEY` avec une valeur secrète longue et unique (voir la modification ci-dessous)
6. Validez : Render construit et démarre l'application, puis vous donne une adresse du type `https://lecorbeaumarket.onrender.com`

### Modification nécessaire avant la mise en ligne
Dans `app.py`, remplacez :
```python
app.secret_key = secrets.token_hex(32)
```
par :
```python
import os
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
```
Ainsi la variable d'environnement définie sur Render est utilisée, et la
clé reste stable entre les redémarrages du serveur (sinon tout le monde
est déconnecté à chaque redémarrage).

### Point important sur la base de données
Sur le plan gratuit de la plupart des hébergeurs (Render y compris), le
disque n'est pas garanti permanent : à chaque nouveau déploiement, le
fichier `lecorbeaumarket.db` peut être réinitialisé. Pour un usage réel et
durable, deux solutions :
- Ajouter un disque persistant (option payante mais peu coûteuse chez Render)
- Migrer vers une vraie base de données hébergée séparément (PostgreSQL)

Pour démarrer et tester avec de vrais premiers utilisateurs, la version
actuelle (SQLite) suffit. On migrera ensemble quand vous serez prêt.

## Ce qui reste à savoir, sans se raconter d'histoires
- **Le paiement reste déclaratif** : aucune application seule ne peut vérifier automatiquement qu'Orange, Telmob ou Telecel a bien reçu l'argent. Cela demande un compte marchand officiel chez l'opérateur et l'intégration de son API — une démarche séparée, à faire directement avec l'opérateur concerné.
- **Pas de notification push sur téléphone fermé.** Les notifications sont consultables dans l'application quand elle est ouverte.
- Testez d'abord avec de vrais volontaires (amis, famille) avant d'inviter du monde, pour repérer les problèmes tranquillement.
