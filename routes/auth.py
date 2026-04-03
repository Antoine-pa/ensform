"""Routes d'authentification (register, verify, login, logout)."""

from datetime import datetime, timezone

import bcrypt
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from extensions import db
from helpers import csrf_valid, login_required, send_verification_email
from models import AdminUser, FormShare

bp = Blueprint("auth", __name__)

_MAX_VERIFY_ATTEMPTS = 5


@bp.route("/admin/register", methods=["GET", "POST"])
def auth_register():
    if current_user.is_authenticated and not session.get("pending_verify_id"):
        return redirect(url_for("admin.admin_dashboard"))
    error = None
    if request.method == "POST":
        if not csrf_valid():
            abort(403)
        email    = request.form.get("email",    "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm",  "")

        if not email or "@" not in email:
            error = "Adresse e-mail invalide."
        elif len(password) < 12:
            error = "Le mot de passe doit contenir au moins 12 caractères."
        elif password != confirm:
            error = "Les mots de passe ne correspondent pas."
        elif AdminUser.query.filter_by(email=email).first():
            error = "Cette adresse e-mail est déjà utilisée."
        else:
            user = AdminUser(email=email)
            user.set_password(password)
            code = user.set_verify_code()
            db.session.add(user)
            db.session.commit()
            ok = send_verification_email(email, code)
            session["pending_verify_id"] = user.id
            if not ok:
                flash(
                    "L'email n'a pas pu être envoyé (serveur SMTP non configuré). "
                    "Consultez les logs pour récupérer le code.",
                    "warning",
                )
            else:
                flash(f"Un code à 6 chiffres a été envoyé à {email}.", "info")
            return redirect(url_for("auth.auth_verify"))
    return render_template("auth/register.html", error=error)


@bp.route("/admin/verify", methods=["GET", "POST"])
def auth_verify():
    if current_user.is_authenticated and not session.get("pending_verify_id"):
        return redirect(url_for("admin.admin_dashboard"))
    uid = session.get("pending_verify_id")
    if not uid:
        return redirect(url_for("auth.auth_register"))
    user = AdminUser.query.get(uid)
    if not user or user.is_verified:
        session.pop("pending_verify_id", None)
        return redirect(url_for("auth.auth_login"))

    error = None
    if request.method == "POST":
        if not csrf_valid():
            abort(403)
        action = request.form.get("action", "verify")

        if action == "resend":
            if user.verify_sent_at:
                sent = user.verify_sent_at
                if sent.tzinfo is None:
                    sent = sent.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - sent).total_seconds()
                if elapsed < 60:
                    error = f"Veuillez attendre {int(60 - elapsed)} s avant de renvoyer le code."
                else:
                    code = user.set_verify_code()
                    db.session.commit()
                    send_verification_email(user.email, code)
                    flash("Nouveau code envoyé.", "info")
            else:
                code = user.set_verify_code()
                db.session.commit()
                send_verification_email(user.email, code)
                flash("Code envoyé.", "info")
        else:
            code = "".join(request.form.get("code", "").split())
            if user.failed_attempts >= _MAX_VERIFY_ATTEMPTS:
                error = "Trop de tentatives. Demandez un nouveau code."
            elif user.check_verify_code(code):
                user.is_verified      = True
                user.verify_code_hash = None
                user.failed_attempts  = 0
                pending_shares = FormShare.query.filter_by(email=user.email, user_id=None).all()
                for ps in pending_shares:
                    ps.user_id = user.id
                db.session.commit()
                session.pop("pending_verify_id", None)
                login_user(user, remember=False)
                flash("Compte vérifié. Bienvenue !", "success")
                return redirect(url_for("admin.admin_dashboard"))
            else:
                user.failed_attempts += 1
                db.session.commit()
                remaining = _MAX_VERIFY_ATTEMPTS - user.failed_attempts
                error = f"Code incorrect. {remaining} tentative(s) restante(s)."

    return render_template("auth/verify.html", email=user.email, error=error)


@bp.route("/admin/login", methods=["GET", "POST"])
def auth_login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.admin_dashboard"))
    error = None
    if request.method == "POST":
        if not csrf_valid():
            abort(403)
        email    = request.form.get("email",    "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = AdminUser.query.filter_by(email=email).first()
        if not user:
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt(4)))
            error = "Identifiants incorrects."
        elif user.is_locked():
            lu = user.locked_until
            if lu.tzinfo is None:
                lu = lu.replace(tzinfo=timezone.utc)
            secs = int((lu - datetime.now(timezone.utc)).total_seconds())
            error = f"Compte verrouillé. Réessayez dans {secs // 60}m{secs % 60:02d}s."
        elif not user.is_verified:
            session["pending_verify_id"] = user.id
            return redirect(url_for("auth.auth_verify"))
        elif not user.check_password(password):
            user.record_failed_login()
            db.session.commit()
            error = "Identifiants incorrects."
        else:
            user.record_success_login()
            db.session.commit()
            login_user(user, remember=remember)
            next_url = request.args.get("next") or url_for("admin.admin_dashboard")
            if not next_url.startswith("/"):
                next_url = url_for("admin.admin_dashboard")
            return redirect(next_url)

    return render_template("auth/login.html", error=error)


@bp.route("/admin/logout", methods=["POST"])
@login_required
def auth_logout():
    if not csrf_valid():
        abort(403)
    logout_user()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("auth.auth_login"))
