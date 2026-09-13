"""
LeCorbeauMarket — backend réel (Flask + SQLite)
================================================
Ce serveur remplace le stockage local du navigateur par une vraie base de
données partagée : les comptes, les produits, les commandes et les
formations existent sur le serveur, pas seulement sur le téléphone de
la personne qui les a créés.

Ce que ce serveur fait :
  - comptes clients / vendeurs / administrateur, avec mots de passe
    hachés (jamais stockés en clair)
  - protection CSRF sur toutes les requêtes qui modifient des données
  - produits liés à un vendeur précis
  - commandes suivant le parcours :
    en_attente -> confirmee (ou refusee) -> livree
  - notifications internes (consultables via l'API)
  - formations gérées par l'administrateur

Ce que ce serveur NE fait PAS (et ne doit pas prétendre faire) :
  - il ne vérifie pas lui-même auprès d'Orange/Telmob/Telecel qu'un
    paiement a été reçu — cela demande un vrai compte marchand et
    l'API officielle de chaque opérateur, à ajouter plus tard
  - il n'envoie pas de notification push sur un téléphone fermé — les
    notifications sont consultables via l'API tant que l'application
    est ouverte, ou par une future intégration SMS/e-mail
"""
import re
import os
import secrets
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

import db

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))  # définissez SECRET_KEY en production, sinon tout le monde est déconnecté à chaque redémarrage
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

ADMIN_PHONE_SEED = "67547490"  # le compte administrateur initial est rattaché à ce numéro
PRIX_ACCES = "5 500 FCFA"
OPERATEURS = {
    "orange": {"nom": "Orange Money", "numero": "67 54 74 90"},
    "telmob": {"nom": "Telmob (Onatel)", "numero": "72 95 24 45"},
    "telecel": {"nom": "Telecel Money", "numero": "58 23 43 53"},
}


# ---------------------------------------------------------------- helpers
def error(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


def require_login(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            return error("Connexion requise", 401)
        return f(*a, **kw)
    return wrapper


def require_role(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return error("Connexion requise", 401)
            if session.get("role") not in roles:
                return error("Accès refusé pour ce rôle", 403)
            return f(*a, **kw)
        return wrapper
    return deco


def require_csrf(f):
    @wraps(f)
    def wrapper(*a, **kw):
        token = request.headers.get("X-CSRFToken")
        if not token or token != session.get("csrf_token"):
            return error("Jeton de sécurité (CSRF) invalide ou manquant", 403)
        return f(*a, **kw)
    return wrapper


def current_user_row(conn):
    return conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()


PHONE_RE = re.compile(r"^[0-9]{8,15}$")


# ------------------------------------------------------------------- auth
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "client"
    operateur = (data.get("operateur") or "").strip()
    reference_paiement = (data.get("reference_paiement") or "").strip()

    if role not in ("client", "vendeur"):
        return error("Rôle invalide")
    if not name or len(name) < 2:
        return error("Nom invalide")
    if not PHONE_RE.match(phone):
        return error("Numéro de téléphone invalide")
    if len(password) < 6:
        return error("Le mot de passe doit contenir au moins 6 caractères")
    if operateur not in OPERATEURS:
        return error("Opérateur de paiement invalide")
    if not reference_paiement:
        return error("La référence de paiement est obligatoire")

    conn = db.get_db()
    existing = conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone()
    if existing:
        conn.close()
        return error("Ce numéro de téléphone a déjà un compte")

    pwd_hash = generate_password_hash(password)
    cur = conn.execute(
        """INSERT INTO users (name, phone, password_hash, role, actif, operateur, reference_paiement, created_at)
           VALUES (?,?,?,?,0,?,?,?)""",
        (name, phone, pwd_hash, role, operateur, reference_paiement, db.now()),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "user_id": user_id,
                     "message": "Compte créé. Il sera activé dès que votre paiement sera vérifié."})


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""

    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user["password_hash"], password):
        return error("Numéro ou mot de passe incorrect", 401)
    if not user["actif"]:
        return jsonify({"ok": False, "error": "compte_en_attente",
                         "message": "Votre paiement n'a pas encore été validé par l'administrateur."}), 403

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["csrf_token"] = secrets.token_hex(16)
    return jsonify({
        "ok": True,
        "user": {"id": user["id"], "name": user["name"], "phone": user["phone"], "role": user["role"]},
        "csrf_token": session["csrf_token"],
    })


@app.route("/api/auth/logout", methods=["POST"])
@require_login
@require_csrf
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"ok": True, "user": None})
    conn = db.get_db()
    u = current_user_row(conn)
    conn.close()
    if not u:
        session.clear()
        return jsonify({"ok": True, "user": None})
    return jsonify({"ok": True, "user": {"id": u["id"], "name": u["name"], "phone": u["phone"], "role": u["role"]},
                     "csrf_token": session.get("csrf_token")})


# --------------------------------------------------------------- produits
@app.route("/api/produits", methods=["GET"])
def list_produits():
    q = (request.args.get("q") or "").strip().lower()
    categorie = (request.args.get("categorie") or "").strip()
    mine = request.args.get("mine") == "1"
    conn = db.get_db()
    if mine:
        if "user_id" not in session:
            conn.close()
            return error("Connexion requise", 401)
        rows = conn.execute(
            """SELECT p.*, u.name as vendeur_nom FROM produits p
               JOIN users u ON u.id = p.vendeur_id
               WHERE p.vendeur_id=? ORDER BY p.created_at DESC""",
            (session["user_id"],),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT p.*, u.name as vendeur_nom FROM produits p
               JOIN users u ON u.id = p.vendeur_id
               WHERE p.actif=1 ORDER BY p.created_at DESC"""
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        if categorie and categorie != "Tous" and r["categorie"] != categorie:
            continue
        if q and q not in r["nom"].lower() and q not in (r["categorie"] or "").lower():
            continue
        result.append(dict(r))
    return jsonify({"ok": True, "produits": result})


@app.route("/api/produits", methods=["POST"])
@require_role("vendeur", "admin")
@require_csrf
def create_produit():
    data = request.get_json(force=True, silent=True) or {}
    nom = (data.get("nom") or "").strip()
    if not nom:
        return error("Le nom du produit est obligatoire")
    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO produits (vendeur_id, nom, categorie, description, prix, contact, created_at) VALUES (?,?,?,?,?,?,?)",
        (session["user_id"], nom, data.get("categorie", ""), data.get("description", ""),
         data.get("prix", ""), data.get("contact", ""), db.now()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "id": pid})


@app.route("/api/produits/<int:pid>", methods=["PUT"])
@require_role("vendeur", "admin")
@require_csrf
def update_produit(pid):
    data = request.get_json(force=True, silent=True) or {}
    conn = db.get_db()
    p = conn.execute("SELECT * FROM produits WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return error("Produit introuvable", 404)
    if p["vendeur_id"] != session["user_id"] and session["role"] != "admin":
        conn.close()
        return error("Ce produit ne vous appartient pas", 403)
    conn.execute(
        "UPDATE produits SET nom=?, categorie=?, description=?, prix=?, contact=? WHERE id=?",
        (data.get("nom", p["nom"]), data.get("categorie", p["categorie"]),
         data.get("description", p["description"]), data.get("prix", p["prix"]),
         data.get("contact", p["contact"]), pid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/produits/<int:pid>", methods=["DELETE"])
@require_role("vendeur", "admin")
@require_csrf
def delete_produit(pid):
    conn = db.get_db()
    p = conn.execute("SELECT * FROM produits WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return error("Produit introuvable", 404)
    if p["vendeur_id"] != session["user_id"] and session["role"] != "admin":
        conn.close()
        return error("Ce produit ne vous appartient pas", 403)
    conn.execute("UPDATE produits SET actif=0 WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# -------------------------------------------------------------- commandes
@app.route("/api/commandes", methods=["POST"])
@require_login
@require_csrf
def create_commande():
    data = request.get_json(force=True, silent=True) or {}
    produit_id = data.get("produit_id")
    conn = db.get_db()
    p = conn.execute("SELECT * FROM produits WHERE id=? AND actif=1", (produit_id,)).fetchone()
    if not p:
        conn.close()
        return error("Produit introuvable")
    numero = "LCM-" + secrets.token_hex(4).upper()
    ts = db.now()
    cur = conn.execute(
        """INSERT INTO commandes (numero, produit_id, acheteur_id, vendeur_id, quantite,
           operateur, reference_paiement, statut, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (numero, produit_id, session["user_id"], p["vendeur_id"], data.get("quantite", 1),
         data.get("operateur", ""), data.get("reference_paiement", ""), "en_attente", ts, ts),
    )
    conn.commit()
    cid = cur.lastrowid
    db.notify(conn, p["vendeur_id"], "nouvelle_commande",
              f"Nouvelle commande {numero} pour « {p['nom']} »")
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": cid, "numero": numero})


@app.route("/api/commandes", methods=["GET"])
@require_login
def list_commandes():
    conn = db.get_db()
    role = session["role"]
    if role in ("vendeur", "admin"):
        rows = conn.execute(
            """SELECT c.*, p.nom as produit_nom, u.name as acheteur_nom, u.phone as acheteur_phone
               FROM commandes c
               JOIN produits p ON p.id = c.produit_id
               JOIN users u ON u.id = c.acheteur_id
               WHERE c.vendeur_id=? OR ?='admin'
               ORDER BY c.created_at DESC""",
            (session["user_id"], role),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT c.*, p.nom as produit_nom FROM commandes c
               JOIN produits p ON p.id = c.produit_id
               WHERE c.acheteur_id=? ORDER BY c.created_at DESC""",
            (session["user_id"],),
        ).fetchall()
    conn.close()
    return jsonify({"ok": True, "commandes": [dict(r) for r in rows]})


@app.route("/api/commandes/<int:cid>/statut", methods=["POST"])
@require_role("vendeur", "admin")
@require_csrf
def update_statut(cid):
    data = request.get_json(force=True, silent=True) or {}
    nouveau = data.get("statut")
    if nouveau not in ("confirmee", "refusee", "livree"):
        return error("Statut invalide")
    conn = db.get_db()
    c = conn.execute("SELECT * FROM commandes WHERE id=?", (cid,)).fetchone()
    if not c:
        conn.close()
        return error("Commande introuvable", 404)
    if c["vendeur_id"] != session["user_id"] and session["role"] != "admin":
        conn.close()
        return error("Cette commande ne vous concerne pas", 403)
    conn.execute("UPDATE commandes SET statut=?, updated_at=? WHERE id=?", (nouveau, db.now(), cid))
    label = {"confirmee": "confirmée", "refusee": "refusée", "livree": "marquée comme livrée"}[nouveau]
    db.notify(conn, c["acheteur_id"], "statut_commande",
              f"Votre commande {c['numero']} a été {label}")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ------------------------------------------------------------- formations
@app.route("/api/formations", methods=["GET"])
def list_formations():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM formations ORDER BY created_at ASC").fetchall()
    conn.close()
    return jsonify({"ok": True, "formations": [dict(r) for r in rows]})


@app.route("/api/formations", methods=["POST"])
@require_role("admin")
@require_csrf
def create_formation():
    data = request.get_json(force=True, silent=True) or {}
    titre = (data.get("titre") or "").strip()
    if not titre:
        return error("Le titre est obligatoire")
    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO formations (titre, categorie, description, contenu, created_at) VALUES (?,?,?,?,?)",
        (titre, data.get("categorie", ""), data.get("description", ""), data.get("contenu", ""), db.now()),
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "id": fid})


@app.route("/api/formations/<int:fid>", methods=["PUT"])
@require_role("admin")
@require_csrf
def update_formation(fid):
    data = request.get_json(force=True, silent=True) or {}
    conn = db.get_db()
    f = conn.execute("SELECT * FROM formations WHERE id=?", (fid,)).fetchone()
    if not f:
        conn.close()
        return error("Formation introuvable", 404)
    conn.execute(
        "UPDATE formations SET titre=?, categorie=?, description=?, contenu=? WHERE id=?",
        (data.get("titre", f["titre"]), data.get("categorie", f["categorie"]),
         data.get("description", f["description"]), data.get("contenu", f["contenu"]), fid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/formations/<int:fid>", methods=["DELETE"])
@require_role("admin")
@require_csrf
def delete_formation(fid):
    conn = db.get_db()
    conn.execute("DELETE FROM formations WHERE id=?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------- notifications
@app.route("/api/notifications", methods=["GET"])
@require_login
def list_notifications():
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "notifications": [dict(r) for r in rows]})


@app.route("/api/notifications/lues", methods=["POST"])
@require_login
@require_csrf
def mark_notifications_read():
    conn = db.get_db()
    conn.execute("UPDATE notifications SET lu=1 WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------- health
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "en ligne"})


# ---------------------------------------------------------- CORS (manuel)
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def options_handler(_any):
    return jsonify({"ok": True})


# ----------------------------------------------------------------- comptes
@app.route("/api/comptes/en_attente", methods=["GET"])
@require_role("admin")
def comptes_en_attente():
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, name, phone, role, operateur, reference_paiement, created_at FROM users WHERE actif=0 ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "comptes": [dict(r) for r in rows]})


@app.route("/api/comptes/<int:uid>/activer", methods=["POST"])
@require_role("admin")
@require_csrf
def activer_compte(uid):
    conn = db.get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        conn.close()
        return error("Compte introuvable", 404)
    conn.execute("UPDATE users SET actif=1 WHERE id=?", (uid,))
    db.notify(conn, uid, "compte_active", "Votre compte LeCorbeauMarket est activé. Vous pouvez vous connecter.")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/comptes/<int:uid>/refuser", methods=["POST"])
@require_role("admin")
@require_csrf
def refuser_compte(uid):
    conn = db.get_db()
    conn.execute("DELETE FROM users WHERE id=? AND actif=0", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET"])
def config():
    return jsonify({"ok": True, "prix_acces": PRIX_ACCES, "operateurs": OPERATEURS})


# -------------------------------------------------------------- frontend
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


def bootstrap_admin():
    """Crée le compte administrateur si la base est neuve."""
    conn = db.get_db()
    existing = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if not existing:
        pwd_hash = generate_password_hash("changez-ce-mot-de-passe")
        conn.execute(
            "INSERT INTO users (name, phone, password_hash, role, actif, created_at) VALUES (?,?,?,?,1,?)",
            ("Gontran DABRE", ADMIN_PHONE_SEED, pwd_hash, "admin", db.now()),
        )
        conn.commit()
        print(f"[LeCorbeauMarket] Compte administrateur créé : {ADMIN_PHONE_SEED} / changez-ce-mot-de-passe")
    conn.close()


db.init_db()
bootstrap_admin()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
