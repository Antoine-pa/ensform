"""Fonctions utilitaires partagées pour ENSForm."""

import hashlib
import json
import os
import random
import secrets
import smtplib
import ssl
import string
from functools import wraps

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import abort, current_app, flash, redirect, request, session, url_for
from flask_login import current_user, logout_user
from flask_login import login_required as _flask_login_required
from slugify import slugify

from extensions import db
from models import (
    AdminUser, Form, FormShare, GroupDepartment, GroupParticipant,
    Question, Response,
)


# ── CSRF ──────────────────────────────────────────────────────────────────────

def _csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(32)
    return session["_csrf"]


def csrf_valid() -> bool:
    token = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
    return secrets.compare_digest(session.get("_csrf", "x"), token)


# ── login_required personnalisé ───────────────────────────────────────────────

def login_required(f):
    """Wrapper autour de flask_login.login_required.
    Vérifie aussi que l'email est validé (double sécurité).
    Désactivable via AUTH_ENABLED=false."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_app.config.get("AUTH_ENABLED", True):
            return f(*args, **kwargs)
        result = _flask_login_required(f)(*args, **kwargs)
        if current_user.is_authenticated and not current_user.is_verified:
            logout_user()
            session.clear()
            flash("Veuillez vérifier votre adresse e-mail.", "warning")
            return redirect(url_for("auth.auth_login"))
        return result
    return decorated


# ── Email ─────────────────────────────────────────────────────────────────────

def _smtp_config():
    return {
        "server":   os.environ.get("MAIL_SERVER", ""),
        "port":     int(os.environ.get("MAIL_PORT", "25")),
        "username": os.environ.get("MAIL_USERNAME", ""),
        "password": os.environ.get("MAIL_PASSWORD", ""),
        "sender":   os.environ.get("MAIL_FROM", os.environ.get("MAIL_USERNAME", "") or "noreply@localhost"),
        "use_tls":  os.environ.get("MAIL_USE_TLS", "false").lower() != "false",
    }


def _send_email(to_email: str, subject: str, txt: str, html: str) -> bool:
    cfg = _smtp_config()
    if not cfg["server"]:
        current_app.logger.warning("⚠  Email non configuré. Destinataire : %s", to_email)
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"ENSForm <{cfg['sender']}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html",  "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["server"], cfg["port"], timeout=10) as smtp:
            smtp.ehlo()
            if cfg["use_tls"]:
                smtp.starttls(context=ctx)
                smtp.ehlo()
            if cfg["username"] and cfg["password"]:
                smtp.login(cfg["username"], cfg["password"])
            smtp.sendmail(cfg["sender"], to_email, msg.as_string())
        return True
    except Exception as exc:
        current_app.logger.error("Erreur envoi email : %s", exc)
        return False


def send_verification_email(to_email: str, code: str) -> bool:
    cfg = _smtp_config()
    if not cfg["server"]:
        current_app.logger.warning(
            "⚠  Email non configuré. Code de vérification pour %s : %s", to_email, code
        )
        return False
    txt = (
        f"Bonjour,\n\n"
        f"Votre code de vérification ENSForm est :\n\n"
        f"  {code}\n\n"
        f"Ce code est valable 10 minutes.\n"
        f"Si vous n'avez pas fait cette demande, ignorez ce message."
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px">
  <h2 style="color:#0d6efd">ENSForm</h2>
  <p>Votre code de vérification :</p>
  <div style="font-size:2.2rem;letter-spacing:10px;font-family:monospace;
              font-weight:700;text-align:center;background:#f8f9fa;
              border-radius:8px;padding:16px 0;color:#212529">{code}</div>
  <p style="color:#6c757d;font-size:.9em">
    Ce code expire dans <strong>10 minutes</strong>.<br>
    Si vous n'avez pas fait cette demande, ignorez ce message.
  </p>
</body></html>"""
    return _send_email(to_email, "Code de vérification – ENSForm", txt, html)


def send_share_notification(to_email: str, form_title: str, role: str, sharer_email: str, has_account: bool) -> bool:
    role_fr = "éditeur" if role == "editor" else "lecteur"
    action = "Connectez-vous" if has_account else "Créez un compte"
    url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
    txt = (
        f"{sharer_email} a partagé le formulaire « {form_title} » avec vous "
        f"en tant que {role_fr}.\n\n"
        f"{action} sur {url}/admin/login pour y accéder."
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px">
  <h2 style="color:#0d6efd">ENSForm</h2>
  <p><strong>{sharer_email}</strong> a partagé le formulaire :</p>
  <div style="background:#f0f2f5;border-radius:8px;padding:16px;margin:16px 0">
    <strong style="font-size:1.1em">{form_title}</strong>
    <br><span style="color:#6c757d">Rôle : {role_fr}</span>
  </div>
  <p><a href="{url}/admin/login" style="background:#0d6efd;color:white;padding:10px 24px;
     border-radius:6px;text-decoration:none;display:inline-block">{action}</a></p>
  {"<p style='color:#6c757d;font-size:.9em'>Vous n'avez pas encore de compte ? Inscrivez-vous avec cette adresse email pour accéder au formulaire.</p>" if not has_account else ""}
</body></html>"""
    return _send_email(to_email, f"Formulaire partagé avec vous – {form_title}", txt, html)


# ── Slug / public_id ─────────────────────────────────────────────────────────

def make_slug(title, exclude_form_id=None):
    base = slugify(title, allow_unicode=True) or "formulaire"
    candidate = base
    suffix = 2
    while True:
        query = Form.query.filter_by(slug=candidate)
        if exclude_form_id is not None:
            query = query.filter(Form.id != exclude_form_id)
        if not query.first():
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def gen_public_id(length=8):
    chars = string.ascii_lowercase + string.digits
    for _ in range(100):
        pid = "".join(random.choices(chars, k=length))
        if not Form.query.filter_by(public_id=pid).first():
            return pid
    raise RuntimeError("Impossible de générer un public_id unique")


# ── Utilitaires divers ────────────────────────────────────────────────────────

def request_fingerprint():
    data = (request.remote_addr or "") + request.headers.get("User-Agent", "")
    return hashlib.sha256(data.encode()).hexdigest()


def decode_value(val: str) -> str:
    """Retourne une chaîne lisible depuis une valeur d'Answer."""
    if not val:
        return ""
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return ", ".join(str(x) for x in parsed)
        if isinstance(parsed, dict):
            itype = parsed.get("identity_type")
            if itype == "exte":
                name  = parsed.get("identity_name", "—")
                phone = parsed.get("phone", "")
                return name + (f" | {phone}" if phone else "")
            if itype == "list":
                name   = parsed.get("identity_name", "—")
                phone  = parsed.get("phone", "")
                wishes = []
                for w in parsed.get("wishes", []):
                    wt = w.get("type", "personne")
                    if wt in ("list", "exte"):
                        wishes.append(w.get("name", ""))
                    else:
                        wishes.append("Personne")
                wish_str = " / ".join(wishes) if wishes else "—"
                return f"{name} | {phone} | {wish_str}"
    except Exception:
        pass
    return val


# ── Helpers Groupe ────────────────────────────────────────────────────────────

def groupe_participants(form_id: int) -> list[str]:
    return [
        p.name
        for p in GroupParticipant.query
        .filter_by(form_id=form_id)
        .order_by(GroupParticipant.name)
        .all()
    ]


def groupe_respondents(form_id: int) -> list[str]:
    return [
        r.respondent_name
        for r in Response.query
        .filter(Response.form_id == form_id, Response.respondent_name.isnot(None))
        .all()
    ]


def groupe_exte_respondents(form_id: int) -> list[str]:
    groupe_q_ids = {
        q.id for q in Question.query.filter_by(form_id=form_id, qtype="groupe").all()
    }
    if not groupe_q_ids:
        return []
    names = []
    for resp in Response.query.filter_by(form_id=form_id).all():
        for ans in resp.answers:
            if ans.question_id in groupe_q_ids:
                try:
                    data = json.loads(ans.value)
                    if data.get("identity_type") == "exte":
                        name = data.get("identity_name", "").strip()
                        if name:
                            names.append(f"Exté : {name}")
                except Exception:
                    pass
    return names


def groupe_node_colors(form_id: int) -> dict[str, str]:
    dept_colors = {
        d.name: d.color
        for d in GroupDepartment.query.filter_by(form_id=form_id).all()
    }
    return {
        p.name: dept_colors.get(p.department or "", "#ffffff")
        for p in GroupParticipant.query.filter_by(form_id=form_id).all()
    }


def groupe_edges(form) -> list[tuple[str, str]]:
    groupe_q_ids = {q.id for q in form.questions if q.qtype == "groupe"}
    if not groupe_q_ids:
        return []
    edges = []
    for resp in form.responses:
        voter = resp.respondent_name
        if not voter:
            continue
        for answer in resp.answers:
            if answer.question_id not in groupe_q_ids:
                continue
            try:
                data = json.loads(answer.value or "{}")
                if data.get("identity_type") != "list":
                    continue
                for wish in data.get("wishes", []):
                    wtype = wish.get("type", "personne")
                    wname = wish.get("name", "").strip()
                    if wtype == "list" and wname:
                        edges.append((voter, wname))
                    elif wtype == "exte" and wname:
                        edges.append((voter, f"Exté : {wname}"))
            except Exception:
                pass
    return edges


# ── Contrôle d'accès ─────────────────────────────────────────────────────────

_ROLE_LEVEL = {"reader": 0, "editor": 1, "owner": 2, "admin": 3}


def user_form_role(form):
    """Retourne le rôle de l'utilisateur courant pour ce formulaire."""
    if not current_app.config.get("AUTH_ENABLED", True):
        return "owner"
    if not current_user.is_authenticated:
        return None
    admin_id = os.environ.get("ADMIN_ID", "")
    if admin_id and current_user.email == admin_id:
        return "admin"
    if form.owner_id is None or form.owner_id == current_user.id:
        return "owner"
    share = FormShare.query.filter_by(form_id=form.id, user_id=current_user.id).first()
    if not share:
        share = FormShare.query.filter_by(form_id=form.id, email=current_user.email).first()
        if share and not share.user_id:
            share.user_id = current_user.id
            db.session.commit()
    if share:
        return share.role
    return None


def get_form_with_access(form_id: int, min_role="reader"):
    """Récupère un formulaire et vérifie que l'utilisateur a le rôle minimum requis."""
    form = Form.query.get_or_404(form_id)
    role = user_form_role(form)
    if role is None or _ROLE_LEVEL.get(role, -1) < _ROLE_LEVEL.get(min_role, 0):
        abort(403)
    return form
