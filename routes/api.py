"""Routes API : questions, participants, départements, partage."""

import csv
import io

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user

from extensions import db
from helpers import (
    csrf_valid, get_form_with_access, login_required, send_share_notification,
)
from models import (
    AdminUser, Form, FormShare, GroupDepartment, GroupParticipant, Question,
)

bp = Blueprint("api", __name__)


# ── Questions ─────────────────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/questions", methods=["POST"])
@login_required
def api_question_add(form_id):
    get_form_with_access(form_id, "editor")
    data = request.get_json() or {}
    max_order = (
        db.session.query(db.func.max(Question.order))
        .filter_by(form_id=form_id)
        .scalar()
    ) or 0
    q = Question(
        form_id=form_id,
        order=max_order + 1,
        qtype=data.get("qtype", "text"),
        label=data.get("label", "Nouvelle question"),
        description=data.get("description", ""),
        required=bool(data.get("required", False)),
    )
    q.options = data.get("options", [])
    q.config  = data.get("config", {})
    db.session.add(q)
    db.session.commit()
    return jsonify(q.to_dict()), 201


@bp.route("/api/forms/<int:form_id>/questions/<int:q_id>", methods=["PUT"])
@login_required
def api_question_update(form_id, q_id):
    get_form_with_access(form_id, "editor")
    q = Question.query.filter_by(id=q_id, form_id=form_id).first_or_404()
    data = request.get_json() or {}
    q.label       = data.get("label",       q.label)
    q.description = data.get("description", q.description)
    q.qtype       = data.get("qtype",       q.qtype)
    q.required    = bool(data.get("required", q.required))
    if "options" in data:
        q.options = data["options"]
    if "config" in data:
        q.config = data["config"]
    db.session.commit()
    return jsonify(q.to_dict())


@bp.route("/api/forms/<int:form_id>/questions/<int:q_id>", methods=["DELETE"])
@login_required
def api_question_delete(form_id, q_id):
    get_form_with_access(form_id, "editor")
    q = Question.query.filter_by(id=q_id, form_id=form_id).first_or_404()
    db.session.delete(q)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/forms/<int:form_id>/questions/reorder", methods=["POST"])
@login_required
def api_questions_reorder(form_id):
    get_form_with_access(form_id, "editor")
    data = request.get_json() or {}
    for i, qid in enumerate(data.get("order", [])):
        Question.query.filter_by(id=qid, form_id=form_id).update({"order": i})
    db.session.commit()
    return jsonify({"ok": True})


# ── Participants (Groupe) ─────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/groupe/participants", methods=["GET"])
@login_required
def api_groupe_participants_list(form_id):
    participants = (
        GroupParticipant.query
        .filter_by(form_id=form_id)
        .order_by(GroupParticipant.name)
        .all()
    )
    return jsonify([
        {"id": p.id, "name": p.name, "department": p.department or ""}
        for p in participants
    ])


@bp.route("/api/forms/<int:form_id>/groupe/participants", methods=["POST"])
@login_required
def api_groupe_participant_add(form_id):
    get_form_with_access(form_id, "editor")
    data       = request.get_json() or {}
    name       = (data.get("name") or "").strip()
    department = (data.get("department") or "").strip() or None
    if not name:
        return jsonify({"error": "Nom requis"}), 400
    if GroupParticipant.query.filter_by(form_id=form_id, name=name).first():
        return jsonify({"error": "Ce participant existe déjà"}), 409
    p = GroupParticipant(form_id=form_id, name=name, department=department)
    db.session.add(p)
    db.session.commit()
    return jsonify({"id": p.id, "name": p.name, "department": p.department or ""}), 201


@bp.route("/api/forms/<int:form_id>/groupe/participants/<int:p_id>", methods=["DELETE"])
@login_required
def api_groupe_participant_delete(form_id, p_id):
    get_form_with_access(form_id, "editor")
    p = GroupParticipant.query.filter_by(id=p_id, form_id=form_id).first_or_404()
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/forms/<int:form_id>/groupe/participants/import", methods=["POST"])
@login_required
def api_groupe_participants_import(form_id):
    """Import en masse depuis un collé (noms seuls, sans département)."""
    get_form_with_access(form_id, "editor")
    data  = request.get_json() or {}
    names = [n.strip() for n in data.get("names", "").splitlines() if n.strip()]
    added, skipped = 0, 0
    for name in names:
        if GroupParticipant.query.filter_by(form_id=form_id, name=name).first():
            skipped += 1
            continue
        db.session.add(GroupParticipant(form_id=form_id, name=name))
        added += 1
    db.session.commit()
    return jsonify({"added": added, "skipped": skipped})


@bp.route("/api/forms/<int:form_id>/groupe/participants/upload", methods=["POST"])
@login_required
def api_groupe_participants_upload(form_id):
    """Import depuis un fichier CSV : colonnes Prénom;NOM;Département."""
    get_form_with_access(form_id, "editor")
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Aucun fichier"}), 400
    try:
        content = f.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return jsonify({"error": "Impossible de lire le fichier"}), 400

    added, skipped, errors_list = 0, 0, []
    first_line = content.lstrip().split("\n")[0] if content.strip() else ""
    delimiter  = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    for lineno, row in enumerate(reader, start=1):
        if not row or all(c.strip() == "" for c in row):
            continue
        if lineno == 1 and any(
            c.strip().lower() in ("prénom", "prenom", "nom", "département", "departement")
            for c in row
        ):
            continue
        if len(row) < 2:
            errors_list.append(f"Ligne {lineno} ignorée : moins de 2 colonnes")
            continue
        prenom = row[0].strip()
        nom    = row[1].strip()
        dept   = row[2].strip() if len(row) >= 3 else ""
        name   = f"{prenom} {nom}".strip()
        if not name:
            continue
        if GroupParticipant.query.filter_by(form_id=form_id, name=name).first():
            skipped += 1
            continue
        p = GroupParticipant(form_id=form_id, name=name, department=dept if dept else None)
        db.session.add(p)
        if dept and not GroupDepartment.query.filter_by(form_id=form_id, name=dept).first():
            db.session.add(GroupDepartment(form_id=form_id, name=dept, color="#ffffff"))
        added += 1
    db.session.commit()
    return jsonify({"added": added, "skipped": skipped, "errors": errors_list})


# ── Départements ──────────────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/groupe/departments", methods=["GET"])
@login_required
def api_groupe_departments_get(form_id):
    get_form_with_access(form_id, "reader")
    depts = GroupDepartment.query.filter_by(form_id=form_id).order_by(GroupDepartment.name).all()
    return jsonify({d.name: d.color for d in depts})


@bp.route("/api/forms/<int:form_id>/groupe/departments", methods=["POST"])
@login_required
def api_groupe_departments_save(form_id):
    get_form_with_access(form_id, "editor")
    data = request.get_json() or {}
    for dept_name, color in data.items():
        dept_name = dept_name.strip()
        color     = color.strip()
        if not dept_name:
            continue
        row = GroupDepartment.query.filter_by(form_id=form_id, name=dept_name).first()
        if row:
            row.color = color
        else:
            db.session.add(GroupDepartment(form_id=form_id, name=dept_name, color=color))
    db.session.commit()
    return jsonify({"ok": True})


# ── Partage ───────────────────────────────────────────────────────────────────

@bp.route("/admin/forms/<int:form_id>/share")
@login_required
def admin_form_share(form_id):
    from flask import render_template
    form = get_form_with_access(form_id, "owner")
    shares = FormShare.query.filter_by(form_id=form_id).all()
    return render_template("admin/share.html", form=form, shares=shares)


@bp.route("/api/forms/<int:form_id>/share", methods=["POST"])
@login_required
def api_form_share_add(form_id):
    get_form_with_access(form_id, "owner")
    data  = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    role  = data.get("role", "reader")
    if role not in ("reader", "editor"):
        return jsonify({"error": "Rôle invalide."}), 400
    if not email or "@" not in email:
        return jsonify({"error": "Email invalide."}), 400
    form = Form.query.get_or_404(form_id)

    target = AdminUser.query.filter_by(email=email).first()
    has_account = target is not None

    if target and form.owner_id == target.id:
        return jsonify({"error": "Cette personne est déjà propriétaire du formulaire."}), 400

    existing = FormShare.query.filter_by(form_id=form_id, email=email).first()
    if existing:
        existing.role = role
        if target and not existing.user_id:
            existing.user_id = target.id
    else:
        db.session.add(FormShare(
            form_id=form_id,
            user_id=target.id if target else None,
            email=email,
            role=role,
        ))
    db.session.commit()

    share = FormShare.query.filter_by(form_id=form_id, email=email).first()
    send_share_notification(email, form.title, role, current_user.email, has_account)

    status = "active" if has_account else "pending"
    return jsonify({"ok": True, "id": share.id, "email": email, "role": role, "status": status})


@bp.route("/api/forms/<int:form_id>/share/<int:share_id>", methods=["DELETE"])
@login_required
def api_form_share_remove(form_id, share_id):
    get_form_with_access(form_id, "owner")
    share = FormShare.query.get_or_404(share_id)
    if share.form_id != form_id:
        abort(404)
    db.session.delete(share)
    db.session.commit()
    return jsonify({"ok": True})
