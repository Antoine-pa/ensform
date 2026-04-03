"""Modèles SQLAlchemy pour ENSForm."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from flask_login import UserMixin

from extensions import db


# ── Types de questions ────────────────────────────────────────────────────────

QUESTION_TYPES = [
    ("text",      "Texte court"),
    ("textarea",  "Texte long"),
    ("number",    "Nombre"),
    ("email",     "Email"),
    ("date",      "Date"),
    ("select",    "Liste déroulante (recherche)"),
    ("radio",     "Choix unique"),
    ("checkbox",  "Choix multiple"),
    ("groupe",    "Groupes – Préférences"),
]
QTYPES_DICT = dict(QUESTION_TYPES)

_QTYPE_ICONS = {
    "text":     "input-cursor-text",
    "textarea": "text-left",
    "number":   "hash",
    "email":    "envelope",
    "date":     "calendar3",
    "select":   "search",
    "radio":    "record-circle",
    "checkbox": "check2-square",
    "groupe":   "people",
}


def qtype_icon(qtype: str) -> str:
    return _QTYPE_ICONS.get(qtype, "question-circle")


# ── Utilisateur admin ─────────────────────────────────────────────────────────

class AdminUser(UserMixin, db.Model):
    """Compte administrateur avec email vérifié et mot de passe haché (bcrypt)."""
    __tablename__ = "admin_users"

    id                = db.Column(db.Integer, primary_key=True)
    email             = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash     = db.Column(db.String(255), nullable=False)
    is_verified       = db.Column(db.Boolean, default=False, nullable=False)
    created_at        = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at     = db.Column(db.DateTime, nullable=True)

    verify_code_hash  = db.Column(db.String(255), nullable=True)
    verify_expires_at = db.Column(db.DateTime, nullable=True)
    verify_sent_at    = db.Column(db.DateTime, nullable=True)

    failed_attempts   = db.Column(db.Integer, default=0, nullable=False)
    locked_until      = db.Column(db.DateTime, nullable=True)

    @property
    def is_active(self):
        """Flask-Login : un compte non vérifié est inactif → is_authenticated=False."""
        return self.is_verified

    def set_password(self, plaintext: str) -> None:
        self.password_hash = bcrypt.hashpw(
            plaintext.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

    def check_password(self, plaintext: str) -> bool:
        return bcrypt.checkpw(
            plaintext.encode("utf-8"), self.password_hash.encode("utf-8")
        )

    def set_verify_code(self) -> str:
        """Génère un code à 6 chiffres, stocke son hash SHA-256, retourne le code clair."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.verify_code_hash  = hashlib.sha256(code.encode()).hexdigest()
        self.verify_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        self.verify_sent_at    = datetime.now(timezone.utc)
        return code

    def check_verify_code(self, code: str) -> bool:
        if not self.verify_code_hash or not self.verify_expires_at:
            return False
        now = datetime.now(timezone.utc)
        exp = self.verify_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now > exp:
            return False
        return secrets.compare_digest(
            self.verify_code_hash,
            hashlib.sha256(code.encode()).hexdigest(),
        )

    def is_locked(self) -> bool:
        if not self.locked_until:
            return False
        lu = self.locked_until
        if lu.tzinfo is None:
            lu = lu.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < lu

    def record_failed_login(self) -> None:
        self.failed_attempts += 1
        if self.failed_attempts >= 15:
            self.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
        elif self.failed_attempts >= 10:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        elif self.failed_attempts >= 5:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=1)

    def record_success_login(self) -> None:
        self.failed_attempts = 0
        self.locked_until    = None
        self.last_login_at   = datetime.now(timezone.utc)


# ── Formulaire ────────────────────────────────────────────────────────────────

class Form(db.Model):
    __tablename__ = "forms"

    id             = db.Column(db.Integer, primary_key=True)
    title          = db.Column(db.String(200), nullable=False)
    description    = db.Column(db.Text, default="")
    slug           = db.Column(db.String(200), nullable=False)
    public_id      = db.Column(db.String(10), unique=True, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow)
    is_published   = db.Column(db.Boolean, default=False)
    allow_multiple = db.Column(db.Boolean, default=True)
    owner_id       = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=True)
    owner          = db.relationship("AdminUser", backref="forms")

    questions    = db.relationship(
        "Question", back_populates="form",
        cascade="all, delete-orphan",
        order_by="Question.order", lazy=True,
    )
    responses    = db.relationship(
        "Response", back_populates="form",
        cascade="all, delete-orphan", lazy=True,
    )
    participants = db.relationship(
        "GroupParticipant", back_populates="form",
        cascade="all, delete-orphan", lazy=True,
    )

    @property
    def response_count(self):
        return len(self.responses)

    @property
    def has_groupe(self):
        return any(q.qtype == "groupe" for q in self.questions)


# ── Question ──────────────────────────────────────────────────────────────────

class Question(db.Model):
    __tablename__ = "questions"

    id          = db.Column(db.Integer, primary_key=True)
    form_id     = db.Column(db.Integer, db.ForeignKey("forms.id"), nullable=False)
    order       = db.Column(db.Integer, default=0)
    qtype       = db.Column(db.String(50), nullable=False, default="text")
    label       = db.Column(db.String(500), nullable=False, default="Nouvelle question")
    description = db.Column(db.Text, default="")
    required    = db.Column(db.Boolean, default=False)
    _options    = db.Column("options", db.Text, default="[]")
    _config     = db.Column("config",  db.Text, default="{}")

    form    = db.relationship("Form", back_populates="questions")
    answers = db.relationship(
        "Answer", back_populates="question",
        cascade="all, delete-orphan", lazy=True,
    )

    @property
    def options(self):
        try:
            return json.loads(self._options or "[]")
        except Exception:
            return []

    @options.setter
    def options(self, value):
        self._options = json.dumps(value or [])

    @property
    def config(self):
        try:
            return json.loads(self._config or "{}")
        except Exception:
            return {}

    @config.setter
    def config(self, value):
        self._config = json.dumps(value or {})

    @property
    def type_label(self):
        return QTYPES_DICT.get(self.qtype, self.qtype)

    def to_dict(self):
        return {
            "id":          self.id,
            "order":       self.order,
            "qtype":       self.qtype,
            "type_label":  self.type_label,
            "label":       self.label,
            "description": self.description,
            "required":    self.required,
            "options":     self.options,
            "config":      self.config,
        }


# ── Réponse / Answer ─────────────────────────────────────────────────────────

class Response(db.Model):
    __tablename__ = "responses"

    id              = db.Column(db.Integer, primary_key=True)
    form_id         = db.Column(db.Integer, db.ForeignKey("forms.id"), nullable=False)
    submitted_at    = db.Column(db.DateTime, default=datetime.utcnow)
    fingerprint     = db.Column(db.String(64), index=True)
    respondent_name = db.Column(db.String(200))

    form    = db.relationship("Form", back_populates="responses")
    answers = db.relationship(
        "Answer", back_populates="response",
        cascade="all, delete-orphan", lazy=True,
    )


class Answer(db.Model):
    __tablename__ = "answers"

    id          = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey("responses.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    value       = db.Column(db.Text, default="")

    response = db.relationship("Response", back_populates="answers")
    question = db.relationship("Question", back_populates="answers")


# ── Groupe (participants, départements) ───────────────────────────────────────

class GroupParticipant(db.Model):
    __tablename__ = "group_participants"

    id         = db.Column(db.Integer, primary_key=True)
    form_id    = db.Column(db.Integer, db.ForeignKey("forms.id"), nullable=False)
    name       = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(200), nullable=True)

    form = db.relationship("Form", back_populates="participants")

    __table_args__ = (
        db.UniqueConstraint("form_id", "name", name="uq_group_participant"),
    )


class GroupDepartment(db.Model):
    """Couleur associée à chaque département pour un formulaire."""
    __tablename__ = "group_departments"

    id      = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("forms.id"), nullable=False)
    name    = db.Column(db.String(200), nullable=False)
    color   = db.Column(db.String(20),  nullable=False, default="#ffffff")

    __table_args__ = (
        db.UniqueConstraint("form_id", "name", name="uq_group_department"),
    )


# ── Partage ───────────────────────────────────────────────────────────────────

class FormShare(db.Model):
    """Partage d'un formulaire avec un autre utilisateur (lecteur ou éditeur).
    Si user_id est NULL, le partage est en attente (invitation par email)."""
    __tablename__ = "form_shares"

    id         = db.Column(db.Integer, primary_key=True)
    form_id    = db.Column(db.Integer, db.ForeignKey("forms.id", ondelete="CASCADE"), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=True)
    email      = db.Column(db.String(255), nullable=False)
    role       = db.Column(db.String(20), nullable=False, default="reader")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    form = db.relationship("Form", backref="shares")
    user = db.relationship("AdminUser")


# ── Constructeur de groupes ───────────────────────────────────────────────────

class GroupingSession(db.Model):
    """Session de construction de groupes liée à un formulaire."""
    __tablename__ = "grouping_sessions"

    id         = db.Column(db.Integer, primary_key=True)
    form_id    = db.Column(db.Integer, db.ForeignKey("forms.id", ondelete="CASCADE"), nullable=False)
    name       = db.Column(db.String(200), default="Session 1")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    form        = db.relationship("Form")
    slots       = db.relationship("GroupingSlot", backref="session",
                                  cascade="all, delete-orphan",
                                  order_by="GroupingSlot.display_order")
    assignments = db.relationship("GroupingAssignment", backref="session",
                                  cascade="all, delete-orphan")


class GroupingSlot(db.Model):
    """Un groupe (emplacement) dans une session de grouping."""
    __tablename__ = "grouping_slots"

    id            = db.Column(db.Integer, primary_key=True)
    session_id    = db.Column(db.Integer, db.ForeignKey("grouping_sessions.id", ondelete="CASCADE"), nullable=False)
    name          = db.Column(db.String(200), nullable=False)
    capacity      = db.Column(db.Integer, nullable=False, default=8)
    display_order = db.Column(db.Integer, default=0)


class GroupingAssignment(db.Model):
    """Affectation d'une personne à un slot (null = non affecté)."""
    __tablename__ = "grouping_assignments"

    id            = db.Column(db.Integer, primary_key=True)
    session_id    = db.Column(db.Integer, db.ForeignKey("grouping_sessions.id", ondelete="CASCADE"), nullable=False)
    slot_id       = db.Column(db.Integer, db.ForeignKey("grouping_slots.id", ondelete="SET NULL"), nullable=True)
    person_name   = db.Column(db.String(200), nullable=False)
    person_type   = db.Column(db.String(20), nullable=False, default="participant")
    cluster_id    = db.Column(db.Integer, nullable=True)
    display_order = db.Column(db.Integer, default=0)
    department    = db.Column(db.String(200), nullable=True)
    color         = db.Column(db.String(20), default="#ffffff")

    slot = db.relationship("GroupingSlot")

    __table_args__ = (
        db.UniqueConstraint("session_id", "person_name", name="uq_grouping_assignment"),
    )
