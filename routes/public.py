"""Routes publiques : formulaire et page de remerciement."""

import json
import time
from collections import defaultdict

from flask import Blueprint, abort, redirect, render_template, request, url_for

from extensions import db
from helpers import groupe_participants, request_fingerprint
from models import Answer, Form, Response

bp = Blueprint("public", __name__)

# Rate limiting: {IP: [timestamps]} — max 10 submissions per minute
_submit_log: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW = 60  # seconds


def _rate_limited(ip: str) -> bool:
    now = time.time()
    _submit_log[ip] = [t for t in _submit_log[ip] if now - t < _RATE_WINDOW]
    if len(_submit_log[ip]) >= _RATE_LIMIT:
        return True
    _submit_log[ip].append(now)
    return False


@bp.route("/f/<public_id>/<slug>", methods=["GET", "POST"])
@bp.route("/f/<public_id>", methods=["GET", "POST"])
def public_form(public_id, slug=None):
    form = Form.query.filter_by(public_id=public_id, is_published=True).first_or_404()

    participants: list[str] = groupe_participants(form.id) if form.has_groupe else []
    errors: dict = {}

    if request.method == "POST":
        ip = request.headers.get("X-Real-IP", request.remote_addr)
        if _rate_limited(ip):
            abort(429)

        fp              = None
        respondent_name = None
        participant_set = set(participants)

        groupe_q = next((q for q in form.questions if q.qtype == "groupe"), None)
        if groupe_q:
            id_type = request.form.get(f"g_{groupe_q.id}_identity_type", "")
            if id_type == "list":
                name = request.form.get(f"g_{groupe_q.id}_identity_name", "").strip()
                if name:
                    if name not in participant_set:
                        errors[f"g_{groupe_q.id}_identity"] = (
                            f"« {name} » ne figure pas dans la liste des participants."
                        )
                    else:
                        respondent_name = name
                        existing = Response.query.filter_by(
                            form_id=form.id, respondent_name=name
                        ).first()
                        if existing:
                            errors[f"g_{groupe_q.id}_identity"] = (
                                f"« {name} » a déjà soumis ce formulaire."
                            )
        elif not form.allow_multiple:
            fp = request_fingerprint()
            if Response.query.filter_by(form_id=form.id, fingerprint=fp).first():
                errors["__duplicate"] = "Vous avez déjà soumis ce formulaire."

        if not errors:
            for q in form.questions:
                if q.qtype == "groupe":
                    id_type = request.form.get(f"g_{q.id}_identity_type", "").strip()
                    phone   = request.form.get(f"g_{q.id}_phone", "").strip()
                    if q.required and not id_type:
                        errors[f"g_{q.id}_identity"] = "Ce champ est obligatoire."
                    elif id_type == "exte":
                        allow_exte = (q.config or {}).get("allow_exte", True)
                        if not allow_exte:
                            errors[f"g_{q.id}_identity"] = (
                                "Les personnes extérieures ne sont pas autorisées."
                            )
                        else:
                            exte_name = request.form.get(
                                f"g_{q.id}_exte_name", ""
                            ).strip()
                            if not exte_name:
                                errors[f"g_{q.id}_exte_name"] = (
                                    "Veuillez saisir votre nom et prénom."
                                )
                            if not phone:
                                errors[f"g_{q.id}_phone"] = (
                                    "Le numéro de téléphone est obligatoire."
                                )
                    elif id_type == "list":
                        cfg        = q.config or {}
                        allow_exte = cfg.get("allow_exte", True)
                        id_name    = request.form.get(f"g_{q.id}_identity_name", "").strip()
                        if id_name and id_name not in participant_set:
                            errors[f"g_{q.id}_identity"] = (
                                f"« {id_name} » ne figure pas dans la liste des participants."
                            )
                        if not phone:
                            errors[f"g_{q.id}_phone"] = (
                                "Le numéro de téléphone est obligatoire."
                            )
                        max_w = int(cfg.get("max_wishes", 3))
                        for i in range(max_w):
                            wtype = request.form.get(
                                f"g_{q.id}_wish_{i}_type", "personne"
                            )
                            if wtype == "list":
                                wname = request.form.get(
                                    f"g_{q.id}_wish_{i}_name", ""
                                ).strip()
                                if wname and wname not in participant_set:
                                    errors[f"g_{q.id}_wish_{i}"] = (
                                        f"« {wname} » ne figure pas dans la liste des participants."
                                    )
                                if wname and id_name and wname == id_name:
                                    errors[f"g_{q.id}_wish_{i}"] = (
                                        "Vous ne pouvez pas vous sélectionner vous-même."
                                    )
                            elif wtype == "exte":
                                if not allow_exte:
                                    errors[f"g_{q.id}_wish_{i}_exte"] = (
                                        "Les personnes extérieures ne sont pas autorisées."
                                    )
                                else:
                                    ewname = request.form.get(
                                        f"g_{q.id}_wish_{i}_exte_name", ""
                                    ).strip()
                                    if not ewname:
                                        errors[f"g_{q.id}_wish_{i}_exte"] = (
                                            "Veuillez saisir le prénom et nom (ex : Marie Dupont)."
                                        )
                elif q.qtype == "checkbox":
                    if q.required and not request.form.getlist(f"q_{q.id}"):
                        errors[q.id] = "Ce champ est obligatoire."
                else:
                    if q.required and not request.form.get(f"q_{q.id}", "").strip():
                        errors[q.id] = "Ce champ est obligatoire."

        if not errors:
            resp = Response(
                form_id=form.id,
                fingerprint=fp,
                respondent_name=respondent_name,
            )
            db.session.add(resp)
            db.session.flush()

            for q in form.questions:
                if q.qtype == "checkbox":
                    val = json.dumps(request.form.getlist(f"q_{q.id}"))

                elif q.qtype == "groupe":
                    id_type = request.form.get(f"g_{q.id}_identity_type", "")
                    phone   = request.form.get(f"g_{q.id}_phone", "").strip()

                    if id_type == "exte":
                        exte_name = request.form.get(
                            f"g_{q.id}_exte_name", ""
                        ).strip()
                        val = json.dumps({
                            "identity_type": "exte",
                            "identity_name": exte_name,
                            "phone":         phone,
                            "wishes":        [],
                        })
                    elif id_type == "list":
                        id_name    = request.form.get(
                            f"g_{q.id}_identity_name", ""
                        ).strip()
                        max_wishes = int(q.config.get("max_wishes", 3))
                        wishes     = []
                        for i in range(max_wishes):
                            wtype = request.form.get(
                                f"g_{q.id}_wish_{i}_type", "personne"
                            )
                            if wtype == "list":
                                wname = request.form.get(
                                    f"g_{q.id}_wish_{i}_name", ""
                                ).strip()
                                wishes.append({
                                    "type": "list" if wname else "personne",
                                    "name": wname,
                                })
                            elif wtype == "exte":
                                ewname = request.form.get(
                                    f"g_{q.id}_wish_{i}_exte_name", ""
                                ).strip()
                                wishes.append({"type": "exte", "name": ewname})
                            else:
                                wishes.append({"type": "personne", "name": ""})
                        val = json.dumps({
                            "identity_type": "list",
                            "identity_name": id_name,
                            "phone":         phone,
                            "wishes":        wishes,
                        })
                    else:
                        val = json.dumps({})

                else:
                    val = request.form.get(f"q_{q.id}", "").strip()

                db.session.add(Answer(
                    response_id=resp.id,
                    question_id=q.id,
                    value=val,
                ))

            db.session.commit()
            return redirect(url_for("public.public_thanks", public_id=form.public_id, slug=form.slug))

    return render_template(
        "public/form.html",
        form=form,
        participants=participants,
        errors=errors,
        prev=request.form,
    )


@bp.route("/f/<public_id>/<slug>/merci")
@bp.route("/f/<public_id>/merci")
def public_thanks(public_id, slug=None):
    form = Form.query.filter_by(public_id=public_id).first_or_404()
    return render_template("public/thanks.html", form=form)
