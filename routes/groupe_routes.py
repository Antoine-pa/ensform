"""Routes admin pour le module Groupes (page, graphe, exports)."""

import io

from flask import Blueprint, flash, jsonify, redirect, render_template, send_file, url_for

from extensions import db
from helpers import (
    get_form_with_access, groupe_edges, groupe_exte_respondents,
    groupe_node_colors, groupe_participants, groupe_respondents, login_required,
)
from models import GroupDepartment, GroupParticipant

bp = Blueprint("groupe", __name__)


@bp.route("/admin/forms/<int:form_id>/groupe")
@login_required
def admin_groupe(form_id):
    form = get_form_with_access(form_id, "reader")
    participants = (
        GroupParticipant.query
        .filter_by(form_id=form_id)
        .order_by(GroupParticipant.name)
        .all()
    )
    groupe_q    = next((q for q in form.questions if q.qtype == "groupe"), None)
    dept_colors = {
        d.name: d.color
        for d in GroupDepartment.query.filter_by(form_id=form_id).all()
    }
    all_depts = sorted({p.department for p in participants if p.department})
    for dept in all_depts:
        if dept not in dept_colors:
            dept_colors[dept] = "#ffffff"
    return render_template(
        "admin/groupe.html",
        form=form,
        participants=participants,
        groupe_q=groupe_q,
        dept_colors=dept_colors,
        all_depts=all_depts,
    )


@bp.route("/admin/forms/<int:form_id>/groupe/graph-data")
@login_required
def admin_groupe_graph_data(form_id):
    form             = get_form_with_access(form_id, "reader")
    participants     = groupe_participants(form_id)
    edges            = groupe_edges(form)
    respondents      = groupe_respondents(form_id)
    node_colors      = groupe_node_colors(form_id)
    exte_respondents = groupe_exte_respondents(form_id)
    from groupe.graph import build_graph_data
    return jsonify(build_graph_data(participants, edges, respondents, node_colors, exte_respondents))


@bp.route("/admin/forms/<int:form_id>/groupe/export/dot")
@login_required
def admin_groupe_export_dot(form_id):
    form         = get_form_with_access(form_id, "reader")
    participants = groupe_participants(form_id)
    edges        = groupe_edges(form)
    respondents  = groupe_respondents(form_id)
    node_colors      = groupe_node_colors(form_id)
    exte_respondents = groupe_exte_respondents(form_id)
    from groupe.graph import generate_dot
    dot_src = generate_dot(form.title, participants, edges, respondents, node_colors, exte_respondents)
    return send_file(
        io.BytesIO(dot_src.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"groupes_{form.slug}.dot",
    )


@bp.route("/admin/forms/<int:form_id>/groupe/export/png")
@login_required
def admin_groupe_export_png(form_id):
    form         = get_form_with_access(form_id, "reader")
    participants = groupe_participants(form_id)
    edges        = groupe_edges(form)
    respondents  = groupe_respondents(form_id)
    node_colors      = groupe_node_colors(form_id)
    exte_respondents = groupe_exte_respondents(form_id)
    from groupe.graph import generate_png
    png = generate_png(form.title, participants, edges, respondents, node_colors, exte_respondents)
    if png is None:
        flash(
            "Graphviz (commande `dot`) est introuvable. "
            "Installez-le avec : sudo apt install graphviz",
            "warning",
        )
        return redirect(url_for("groupe.admin_groupe", form_id=form_id))
    return send_file(
        io.BytesIO(png),
        mimetype="image/png",
        as_attachment=True,
        download_name=f"groupes_{form.slug}.png",
    )
