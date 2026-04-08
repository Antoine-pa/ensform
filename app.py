"""
ENSForm – Point d'entrée de l'application Flask.
Configure l'app, enregistre les blueprints, exécute les migrations au démarrage.
"""

import hashlib
import os
import subprocess
from datetime import timedelta

from flask import Flask, jsonify, render_template, request as flask_request

from extensions import db, login_manager
from helpers import _csrf_token, gen_public_id
from models import AdminUser, Form, GroupingSession, GroupingSlot, GroupingAssignment, qtype_icon


# ──────────────────────────────────────────────────────────────────────────────
# Création de l'application
# ──────────────────────────────────────────────────────────────────────────────

_BASE_DIR     = os.path.abspath(os.path.dirname(__file__))
_INSTANCE_DIR = os.path.join(_BASE_DIR, "instance")
os.makedirs(_INSTANCE_DIR, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-me-in-production"),
    SQLALCHEMY_DATABASE_URI=os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(_INSTANCE_DIR, 'forms.db')}",
    ),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    AUTH_ENABLED=os.environ.get("AUTH_ENABLED", "true").lower() != "false",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_DURATION=timedelta(days=7),
    REMEMBER_COOKIE_SAMESITE="Lax",
)

# ── Initialisation des extensions ─────────────────────────────────────────────

db.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def _load_user(user_id: str):
    return AdminUser.query.get(int(user_id))


# ── Template globals ──────────────────────────────────────────────────────────

app.jinja_env.globals["csrf_token"] = _csrf_token
app.jinja_env.globals["qtype_icon"] = qtype_icon


def _asset_hash(filename):
    """Short content hash for cache busting static assets."""
    path = os.path.join(_BASE_DIR, "static", filename)
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except FileNotFoundError:
        return "0"


app.jinja_env.globals["asset_hash"] = _asset_hash


# ── Enregistrement des blueprints ─────────────────────────────────────────────

from routes.auth import bp as auth_bp
from routes.admin import bp as admin_bp
from routes.groupe_routes import bp as groupe_bp
from routes.api import bp as api_bp
from routes.public import bp as public_bp
from routes.grouping import bp as grouping_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(groupe_bp)
app.register_blueprint(api_bp)
app.register_blueprint(public_bp)
app.register_blueprint(grouping_bp)

# Passer la config AUTH_ENABLED au blueprint admin pour le dashboard
admin_bp.config_auth_enabled = app.config.get("AUTH_ENABLED", True)


# ── Endpoint de déploiement à distance ────────────────────────────────────────

@app.route("/api/deploy", methods=["POST"])
def remote_deploy():
    token = os.environ.get("DEPLOY_TOKEN", "")
    provided = (flask_request.headers.get("Authorization") or "").replace("Bearer ", "")
    if not token or not provided or token != provided:
        return jsonify({"error": "unauthorized"}), 401
    try:
        pull = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=_BASE_DIR, capture_output=True, text=True, timeout=30,
        )
        pip = subprocess.run(
            [os.path.join(_BASE_DIR, "venv", "bin", "pip"), "install", "-r",
             os.path.join(_BASE_DIR, "requirements.txt"), "-q"],
            cwd=_BASE_DIR, capture_output=True, text=True, timeout=60,
        )
        restart = subprocess.run(
            ["sudo", "systemctl", "restart", "ensform"],
            capture_output=True, text=True, timeout=15,
        )
        return jsonify({
            "ok": True,
            "git": pull.stdout.strip() or pull.stderr.strip(),
            "pip": "done",
            "restart": restart.returncode == 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Route racine ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ──────────────────────────────────────────────────────────────────────────────
# Démarrage : migrations + super-admin
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

    with db.engine.connect() as _conn:
        for _sql in [
            "ALTER TABLE group_participants ADD COLUMN department VARCHAR(200)",
            "ALTER TABLE forms ADD COLUMN owner_id INTEGER REFERENCES admin_users(id)",
            "ALTER TABLE forms ADD COLUMN public_id VARCHAR(10)",
            "ALTER TABLE form_shares ADD COLUMN email VARCHAR(255)",
            "DROP INDEX IF EXISTS ix_forms_slug",
            "DROP INDEX IF EXISTS uq_forms_slug",
        ]:
            try:
                _conn.execute(db.text(_sql))
                _conn.commit()
            except Exception:
                pass

        # SQLite: remove UNIQUE constraint baked into forms.slug column definition
        try:
            row = _conn.execute(db.text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='forms'"
            )).fetchone()
            if row and "UNIQUE" in (row[0] or ""):
                _conn.execute(db.text("""
                    CREATE TABLE IF NOT EXISTS _forms_new (
                        id             INTEGER PRIMARY KEY,
                        title          VARCHAR(200) NOT NULL,
                        description    TEXT DEFAULT '',
                        slug           VARCHAR(200) NOT NULL,
                        public_id      VARCHAR(10) UNIQUE,
                        created_at     DATETIME,
                        updated_at     DATETIME,
                        is_published   BOOLEAN DEFAULT 0,
                        allow_multiple BOOLEAN DEFAULT 1,
                        owner_id       INTEGER REFERENCES admin_users(id)
                    )
                """))
                _conn.execute(db.text("""
                    INSERT OR IGNORE INTO _forms_new
                    SELECT id, title, description, slug, public_id,
                           created_at, updated_at, is_published,
                           allow_multiple, owner_id
                    FROM forms
                """))
                _conn.execute(db.text("DROP TABLE forms"))
                _conn.execute(db.text("ALTER TABLE _forms_new RENAME TO forms"))
                _conn.commit()
        except Exception:
            pass

    _forms_without_pid = Form.query.filter(
        (Form.public_id == None) | (Form.public_id == "")
    ).all()
    for _f in _forms_without_pid:
        _f.public_id = gen_public_id()
    if _forms_without_pid:
        db.session.commit()

    _admin_id = os.environ.get("ADMIN_ID", "").strip()
    _admin_pw = os.environ.get("ADMIN_PASSWORD", "").strip().strip('"')
    if _admin_id and _admin_pw:
        _admin = AdminUser.query.filter_by(email=_admin_id).first()
        if not _admin:
            _admin = AdminUser(email=_admin_id, is_verified=True)
            _admin.set_password(_admin_pw)
            db.session.add(_admin)
            db.session.commit()
        else:
            changed = False
            if not _admin.is_verified:
                _admin.is_verified = True
                changed = True
            if not _admin.check_password(_admin_pw):
                _admin.set_password(_admin_pw)
                changed = True
            if changed:
                db.session.commit()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
