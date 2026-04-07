"""Routes admin : tableau de bord, CRUD formulaires, builder, réponses, export."""

import csv
import io
import json
import os
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, send_file, url_for
from flask_login import current_user
from sqlalchemy import or_

from extensions import db
from helpers import (
    decode_value, gen_public_id, get_form_with_access, login_required,
    make_slug,
)
from models import (
    Form, FormShare, GroupParticipant, Question, Response,
    QUESTION_TYPES,
)

bp = Blueprint("admin", __name__)


# ── Tableau de bord ───────────────────────────────────────────────────────────

@bp.route("/admin")
@login_required
def admin_dashboard():
    shared_forms = []
    is_superadmin = False
    if bp.config_auth_enabled and current_user.is_authenticated:
        admin_id = os.environ.get("ADMIN_ID", "")
        if admin_id and current_user.email == admin_id:
            forms = Form.query.order_by(Form.updated_at.desc()).all()
            is_superadmin = True
        else:
            forms = Form.query.filter_by(owner_id=current_user.id).order_by(Form.updated_at.desc()).all()
            shares = FormShare.query.filter(
                or_(FormShare.user_id == current_user.id, FormShare.email == current_user.email)
            ).all()
            if shares:
                share_map = {s.form_id: s.role for s in shares}
                shared_forms = Form.query.filter(Form.id.in_(share_map.keys())).order_by(Form.updated_at.desc()).all()
                for f in shared_forms:
                    f._share_role = share_map.get(f.id, "reader")
    else:
        forms = Form.query.order_by(Form.updated_at.desc()).all()
    return render_template("admin/dashboard.html", forms=forms, shared_forms=shared_forms, is_superadmin=is_superadmin)


# ── CRUD formulaire ──────────────────────────────────────────────────────────

@bp.route("/admin/forms/new", methods=["GET", "POST"])
@login_required
def admin_form_new():
    from flask import request
    if request.method == "POST":
        title = request.form.get("title", "").strip() or "Nouveau formulaire"
        form = Form(
            title=title,
            description=request.form.get("description", ""),
            slug=make_slug(title),
            public_id=gen_public_id(),
            allow_multiple="allow_multiple" in request.form,
            owner_id=current_user.id if current_user.is_authenticated else None,
        )
        db.session.add(form)
        db.session.commit()
        flash("Formulaire créé avec succès.", "success")
        return redirect(url_for("admin.admin_form_builder", form_id=form.id))
    return render_template("admin/form_new.html")


@bp.route("/admin/forms/<int:form_id>/edit", methods=["GET", "POST"])
@login_required
def admin_form_edit(form_id):
    from flask import request
    form = get_form_with_access(form_id, "editor")
    if request.method == "POST":
        new_title = request.form.get("title", form.title).strip() or form.title
        form.title          = new_title
        form.description    = request.form.get("description", "")
        form.slug           = make_slug(new_title, exclude_form_id=form.id)
        form.allow_multiple = "allow_multiple" in request.form
        form.updated_at     = datetime.utcnow()
        db.session.commit()
        flash("Paramètres enregistrés.", "success")
        return redirect(url_for("admin.admin_form_builder", form_id=form.id))
    return render_template("admin/form_edit.html", form=form)


@bp.route("/admin/forms/<int:form_id>/delete", methods=["POST"])
@login_required
def admin_form_delete(form_id):
    form = get_form_with_access(form_id, "owner")
    db.session.delete(form)
    db.session.commit()
    flash("Formulaire supprimé.", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/admin/forms/<int:form_id>/duplicate", methods=["POST"])
@login_required
def admin_form_duplicate(form_id):
    original = get_form_with_access(form_id, "reader")
    new_title = f"Copie de {original.title}"
    copy = Form(
        title=new_title,
        description=original.description,
        slug=make_slug(new_title),
        public_id=gen_public_id(),
        allow_multiple=original.allow_multiple,
        is_published=False,
        owner_id=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(copy)
    db.session.flush()
    for q in original.questions:
        nq = Question(
            form_id=copy.id, order=q.order, qtype=q.qtype,
            label=q.label, description=q.description, required=q.required,
        )
        nq.options = q.options
        nq.config  = q.config
        db.session.add(nq)
    for p in original.participants:
        db.session.add(GroupParticipant(form_id=copy.id, name=p.name, department=p.department))
    db.session.commit()
    flash("Formulaire dupliqué.", "success")
    return redirect(url_for("admin.admin_form_builder", form_id=copy.id))


@bp.route("/admin/forms/<int:form_id>/publish", methods=["POST"])
@login_required
def admin_form_publish(form_id):
    form = get_form_with_access(form_id, "owner")
    form.is_published = not form.is_published
    form.updated_at   = datetime.utcnow()
    db.session.commit()
    verb = "publié" if form.is_published else "dépublié"
    flash(f"Formulaire {verb}.", "success")
    return redirect(url_for("admin.admin_form_builder", form_id=form_id))


# ── Éditeur visuel ────────────────────────────────────────────────────────────

@bp.route("/admin/forms/<int:form_id>/builder")
@login_required
def admin_form_builder(form_id):
    form = get_form_with_access(form_id, "editor")
    questions_json = json.dumps([q.to_dict() for q in form.questions])
    public_url     = url_for("public.public_form", public_id=form.public_id, slug=form.slug, _external=True)
    return render_template(
        "admin/form_builder.html",
        form=form,
        questions_json=questions_json,
        qtypes=QUESTION_TYPES,
        public_url=public_url,
    )


# ── Réponses / Export ─────────────────────────────────────────────────────────

@bp.route("/admin/forms/<int:form_id>/responses")
@login_required
def admin_form_responses(form_id):
    form = get_form_with_access(form_id, "reader")
    responses = (
        Response.query
        .filter_by(form_id=form_id)
        .order_by(Response.submitted_at.desc())
        .all()
    )
    return render_template(
        "admin/responses.html",
        form=form,
        responses=responses,
        decode_value=decode_value,
    )


@bp.route("/admin/forms/<int:form_id>/responses/export.csv")
@login_required
def admin_form_export_csv(form_id):
    form = get_form_with_access(form_id, "reader")
    responses = (
        Response.query
        .filter_by(form_id=form_id)
        .order_by(Response.submitted_at.asc())
        .all()
    )
    output  = io.StringIO()
    writer  = csv.writer(output)
    headers = ["ID", "Date", "Répondant"]
    for q in form.questions:
        headers.append(q.label)
    writer.writerow(headers)
    for resp in responses:
        by_qid = {a.question_id: a.value for a in resp.answers}
        row = [
            resp.id,
            resp.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
            resp.respondent_name or "",
        ]
        for q in form.questions:
            row.append(decode_value(by_qid.get(q.id, "")))
        writer.writerow(row)
    filename = f"reponses_{form.slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


@bp.route(
    "/admin/forms/<int:form_id>/responses/<int:response_id>/delete",
    methods=["POST"],
)
@login_required
def admin_response_delete(form_id, response_id):
    get_form_with_access(form_id, "editor")
    resp = Response.query.filter_by(id=response_id, form_id=form_id).first_or_404()
    db.session.delete(resp)
    db.session.commit()
    flash("Réponse supprimée.", "success")
    return redirect(url_for("admin.admin_form_responses", form_id=form_id))
