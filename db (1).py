"""
Base de données de LeCorbeauMarket.
Utilise SQLite : un seul fichier, aucune installation de serveur de base
de données nécessaire. Convient parfaitement pour démarrer ; le jour où
LeCorbeauMarket aura beaucoup d'utilisateurs, on pourra migrer vers
PostgreSQL sans changer la logique de l'application.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lecorbeaumarket.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('client','vendeur','admin')) DEFAULT 'client',
    actif INTEGER NOT NULL DEFAULT 0,
    operateur TEXT,
    reference_paiement TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS produits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendeur_id INTEGER NOT NULL,
    nom TEXT NOT NULL,
    categorie TEXT,
    description TEXT,
    prix TEXT,
    contact TEXT,
    actif INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(vendeur_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS commandes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    produit_id INTEGER NOT NULL,
    acheteur_id INTEGER NOT NULL,
    vendeur_id INTEGER NOT NULL,
    quantite INTEGER NOT NULL DEFAULT 1,
    operateur TEXT,
    reference_paiement TEXT,
    statut TEXT NOT NULL CHECK(statut IN ('en_attente','confirmee','refusee','livree')) DEFAULT 'en_attente',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(produit_id) REFERENCES produits(id),
    FOREIGN KEY(acheteur_id) REFERENCES users(id),
    FOREIGN KEY(vendeur_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS formations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titre TEXT NOT NULL,
    categorie TEXT,
    description TEXT,
    contenu TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    lu INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now():
    return datetime.utcnow().isoformat()


def notify(conn, user_id, ntype, message):
    conn.execute(
        "INSERT INTO notifications (user_id, type, message, lu, created_at) VALUES (?,?,?,0,?)",
        (user_id, ntype, message, now()),
    )
