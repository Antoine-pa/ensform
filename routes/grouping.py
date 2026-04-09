"""Routes du constructeur de groupes."""

import csv
import io
import json
from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for

from extensions import db
from helpers import (
    get_form_with_access, groupe_edges, groupe_exte_respondents,
    groupe_node_colors, groupe_participants, groupe_respondents, login_required,
)
from models import (
    Answer, GroupDepartment, GroupParticipant, GroupingAssignment,
    GroupingSession, GroupingSlot, Question, Response,
)
from groupe.clustering import assign_clusters_to_slots, build_affinity_clusters, build_people_list

bp = Blueprint("grouping", __name__)


def _participant_departments(form_id: int) -> dict[str, str | None]:
    return {
        p.name: p.department
        for p in GroupParticipant.query.filter_by(form_id=form_id).all()
    }


def _session_state(session: GroupingSession, form=None) -> dict:
    """Construit le JSON d'état complet d'une session."""
    raw_edges = groupe_edges(form) if form else []

    if form:
        participant_set = set(groupe_participants(form.id))
        respondent_set  = set(groupe_respondents(form.id))
        exte_resp_set   = set(groupe_exte_respondents(form.id))
        dirty = False
        for a in session.assignments:
            if a.person_name.startswith("Exté : ") or a.person_name in exte_resp_set:
                expected = "exte"
            elif a.person_name in participant_set and a.person_name in respondent_set:
                expected = "participant"
            else:
                expected = "non_inscrit"
            if a.person_type != expected:
                a.person_type = expected
                dirty = True
        if dirty:
            db.session.commit()

    exte_requesters: dict[str, list[str]] = {}
    for src, dst in raw_edges:
        if dst.startswith("Exté : "):
            exte_requesters.setdefault(dst, [])
            if src not in exte_requesters[dst]:
                exte_requesters[dst].append(src)

    slots_data = []
    for slot in sorted(session.slots, key=lambda s: s.display_order):
        members = [a for a in session.assignments if a.slot_id == slot.id]
        members.sort(key=lambda a: a.display_order)
        slots_data.append({
            "id":       slot.id,
            "name":     slot.name,
            "capacity": slot.capacity,
            "order":    slot.display_order,
            "members":  [_person_json(m, exte_requesters) for m in members],
        })

    unassigned = sorted(
        [a for a in session.assignments if a.slot_id is None],
        key=lambda a: a.person_name,
    )
    return {
        "session_id":   session.id,
        "session_name": session.name,
        "slots":        slots_data,
        "unassigned":   [_person_json(a, exte_requesters) for a in unassigned],
        "edges":        [{"src": s, "dst": d} for s, d in raw_edges],
    }


def _person_json(a: GroupingAssignment, exte_requesters: dict | None = None) -> dict:
    d = {
        "name":         a.person_name,
        "type":         a.person_type,
        "cluster_id":   a.cluster_id,
        "department":   a.department,
        "color":        a.color or "#ffffff",
        "requested_by": [],
    }
    if a.person_type == "exte" and exte_requesters:
        d["requested_by"] = exte_requesters.get(a.person_name, [])
    return d


# ── Page principale ───────────────────────────────────────────────────────────

@bp.route("/admin/forms/<int:form_id>/grouping/")
@login_required
def grouping_page(form_id):
    form = get_form_with_access(form_id, "editor")
    sessions = GroupingSession.query.filter_by(form_id=form_id).order_by(
        GroupingSession.created_at.desc()
    ).all()
    dept_colors = {
        d.name: d.color
        for d in GroupDepartment.query.filter_by(form_id=form_id).all()
    }
    return render_template(
        "admin/grouping.html",
        form=form,
        sessions=sessions,
        dept_colors=dept_colors,
    )


# ── Créer une session ─────────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/grouping/sessions", methods=["POST"])
@login_required
def api_create_session(form_id):
    form = get_form_with_access(form_id, "editor")
    data = request.get_json() or {}

    count = GroupingSession.query.filter_by(form_id=form_id).count()
    session = GroupingSession(
        form_id=form_id,
        name=data.get("name", f"Session {count + 1}"),
    )
    db.session.add(session)
    db.session.flush()

    participants     = groupe_participants(form_id)
    edges            = groupe_edges(form)
    respondents      = groupe_respondents(form_id)
    exte_respondents = groupe_exte_respondents(form_id)
    node_colors      = groupe_node_colors(form_id)
    part_depts       = _participant_departments(form_id)

    people = build_people_list(
        participants, edges, respondents, exte_respondents,
        node_colors, part_depts,
    )

    for i, p in enumerate(sorted(people, key=lambda x: x["name"])):
        db.session.add(GroupingAssignment(
            session_id    = session.id,
            slot_id       = None,
            person_name   = p["name"],
            person_type   = p["type"],
            cluster_id    = None,
            display_order = i,
            department    = p["department"],
            color         = p["color"],
        ))

    db.session.commit()
    return jsonify({"session_id": session.id}), 201


# ── État d'une session ────────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/grouping/<int:sid>/state")
@login_required
def api_session_state(form_id, sid):
    form    = get_form_with_access(form_id, "reader")
    session = GroupingSession.query.filter_by(id=sid, form_id=form_id).first_or_404()
    return jsonify(_session_state(session, form))


# ── Auto-répartition ──────────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/grouping/<int:sid>/auto", methods=["POST"])
@login_required
def api_auto_assign(form_id, sid):
    form    = get_form_with_access(form_id, "editor")
    session = GroupingSession.query.filter_by(id=sid, form_id=form_id).first_or_404()

    if not session.slots:
        return jsonify({"error": "Créez d'abord des groupes."}), 400

    try:
        edges = groupe_edges(form)
        respondents = set(groupe_respondents(form_id))
        max_cap = max(s.capacity for s in session.slots)

        graph_names = set()
        for src, dst in edges:
            graph_names.add(src)
            graph_names.add(dst)
        active_names = graph_names | respondents

        people = [
            {
                "name":       a.person_name,
                "type":       a.person_type,
                "department": a.department,
                "color":      a.color,
            }
            for a in session.assignments
            if a.person_name in active_names
        ]

        clusters = build_affinity_clusters(people, edges, max_cap)
        slot_caps = [(s.id, s.capacity) for s in session.slots]
        result = assign_clusters_to_slots(clusters, slot_caps)

        by_name = {a.person_name: a for a in session.assignments}

        for a in session.assignments:
            a.slot_id    = None
            a.cluster_id = None

        for slot_id, members in result.items():
            for order, m in enumerate(members):
                a = by_name.get(m["name"])
                if a:
                    a.slot_id       = slot_id
                    a.cluster_id    = m.get("cluster_id")
                    a.display_order = order

        session.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(_session_state(session, form))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("auto_assign failed form_id=%s sid=%s", form_id, sid)
        err = {"error": "Échec de l'auto-répartition."}
        if current_app.debug:
            err["detail"] = str(e)
        return jsonify(err), 500


# ── CRUD groupes ──────────────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/grouping/<int:sid>/slots", methods=["POST"])
@login_required
def api_create_slot(form_id, sid):
    get_form_with_access(form_id, "editor")
    session = GroupingSession.query.filter_by(id=sid, form_id=form_id).first_or_404()
    data = request.get_json() or {}

    count = data.get("count", 1)
    capacity = data.get("capacity", 8)
    name_prefix = data.get("name_prefix", "Groupe")
    existing = len(session.slots)

    created = []
    for i in range(count):
        slot = GroupingSlot(
            session_id    = sid,
            name          = f"{name_prefix} {existing + i + 1}",
            capacity      = capacity,
            display_order = existing + i,
        )
        db.session.add(slot)
        db.session.flush()
        created.append({"id": slot.id, "name": slot.name, "capacity": slot.capacity})

    db.session.commit()
    return jsonify({"slots": created}), 201


@bp.route("/api/forms/<int:form_id>/grouping/<int:sid>/slots/<int:slot_id>", methods=["PUT"])
@login_required
def api_update_slot(form_id, sid, slot_id):
    get_form_with_access(form_id, "editor")
    slot = GroupingSlot.query.filter_by(id=slot_id, session_id=sid).first_or_404()
    data = request.get_json() or {}
    if "name" in data:
        slot.name = data["name"]
    if "capacity" in data:
        slot.capacity = max(1, int(data["capacity"]))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/forms/<int:form_id>/grouping/<int:sid>/slots/<int:slot_id>", methods=["DELETE"])
@login_required
def api_delete_slot(form_id, sid, slot_id):
    get_form_with_access(form_id, "editor")
    slot = GroupingSlot.query.filter_by(id=slot_id, session_id=sid).first_or_404()
    GroupingAssignment.query.filter_by(slot_id=slot_id).update({"slot_id": None})
    db.session.delete(slot)
    db.session.commit()
    return jsonify({"ok": True})


# ── Sauvegarde complète ───────────────────────────────────────────────────────

@bp.route("/api/forms/<int:form_id>/grouping/<int:sid>/save", methods=["POST"])
@login_required
def api_save_state(form_id, sid):
    get_form_with_access(form_id, "editor")
    session = GroupingSession.query.filter_by(id=sid, form_id=form_id).first_or_404()
    data = request.get_json() or {}

    slot_ids = {s.id for s in session.slots}
    slot_caps = {s.id: s.capacity for s in session.slots}
    slot_counts: dict[int, int] = {sid_: 0 for sid_ in slot_ids}

    assignments_data = data.get("assignments", {})
    errors = []

    for key, members in assignments_data.items():
        target_slot = int(key) if key != "null" and key is not None else None
        if target_slot is not None and target_slot not in slot_ids:
            errors.append(f"Groupe {target_slot} inconnu.")
            continue
        for order, m in enumerate(members):
            name = m.get("name", "")
            a = GroupingAssignment.query.filter_by(
                session_id=session.id, person_name=name
            ).first()
            if not a:
                continue
            a.slot_id       = target_slot
            a.cluster_id    = m.get("cluster_id")
            a.display_order = order
            if target_slot is not None:
                slot_counts[target_slot] = slot_counts.get(target_slot, 0) + 1

    for sid_, count in slot_counts.items():
        if count > slot_caps.get(sid_, 0):
            errors.append(
                f"Le groupe dépasse sa capacité ({count}/{slot_caps[sid_]})."
            )

    if errors:
        db.session.rollback()
        return jsonify({"errors": errors}), 400

    session.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})


# ── Export CSV ────────────────────────────────────────────────────────────────

def _phone_map(form_id: int) -> dict[str, str]:
    """Construit {nom_personne: téléphone} à partir des réponses groupe."""
    groupe_q_ids = {
        q.id for q in Question.query.filter_by(form_id=form_id, qtype="groupe").all()
    }
    if not groupe_q_ids:
        return {}
    phones: dict[str, str] = {}
    for resp in Response.query.filter_by(form_id=form_id).all():
        for ans in resp.answers:
            if ans.question_id not in groupe_q_ids:
                continue
            try:
                data = json.loads(ans.value or "{}")
                phone = data.get("phone", "").strip()
                if not phone:
                    continue
                if data.get("identity_type") == "list":
                    name = data.get("identity_name", "").strip()
                    if name:
                        phones[name] = phone
                elif data.get("identity_type") == "exte":
                    name = data.get("identity_name", "").strip()
                    if name:
                        phones[f"Exté : {name}"] = phone
            except Exception:
                pass
    return phones


@bp.route("/admin/forms/<int:form_id>/grouping/<int:sid>/export.csv")
@login_required
def export_csv(form_id, sid):
    form    = get_form_with_access(form_id, "reader")
    session = GroupingSession.query.filter_by(id=sid, form_id=form_id).first_or_404()
    state   = _session_state(session, form)
    phones  = _phone_map(form_id)

    rows = []
    for slot in state["slots"]:
        for m in slot["members"]:
            display = m["name"].removeprefix("Exté : ") if m["name"].startswith("Exté : ") else m["name"]
            phone = phones.get(m["name"], "")
            if m["type"] == "non_inscrit":
                phone = ""
            rows.append((slot["name"], display, m["type"], m["department"] or "", phone))

    rows.sort(key=lambda r: r[0])

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Groupe", "Nom", "Type", "Département", "Téléphone"])
    for row in rows:
        writer.writerow(row)

    filename = f"groupes_{form.slug}_{session.name.replace(' ', '_')}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )
