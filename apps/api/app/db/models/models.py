"""
Database models — Full data model per PLAN.md §3.

UUID primary keys, created_at/updated_at everywhere.
pgvector columns for embeddings.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class ConsentKind(str, enum.Enum):
    BODY_MEDIA = "body_media"
    THIRD_PARTY_AI = "third_party_ai"
    ANALYTICS = "analytics"


class MediaKind(str, enum.Enum):
    BODY_IMAGE = "body_image"
    BODY_VIDEO = "body_video"
    WARDROBE_IMAGE = "wardrobe_image"
    WARDROBE_VIDEO = "wardrobe_video"
    DERIVED = "derived"


class MediaStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    REJECTED = "rejected"


class BodySource(str, enum.Enum):
    MANUAL = "manual"
    PHOTO = "photo"
    VIDEO = "video"


class AttrsSource(str, enum.Enum):
    ML = "ml"
    LLM = "llm"
    USER = "user"


class OutfitSlot(str, enum.Enum):
    TOP = "top"
    BOTTOM = "bottom"
    DRESS = "dress"
    LAYER = "layer"
    SHOES = "shoes"
    BAG = "bag"
    ACCESSORY = "accessory"
    ETHNIC_SET = "ethnic_set"


class OutfitEventType(str, enum.Enum):
    IMPRESSION = "impression"
    LIKE = "like"
    DISLIKE = "dislike"
    SAVE = "save"
    SKIP = "skip"
    WEAR = "wear"
    VARIATION = "variation"
    BUY_CLICK = "buy_click"


class OutfitPolicy(str, enum.Enum):
    EXPLOIT = "exploit"
    EXPLORE = "explore"
    RULES = "rules"


class ModelKind(str, enum.Enum):
    RANKER = "ranker"
    ATTR_HEAD = "attr_head"
    BODY_SHAPE = "body_shape"


class ModelStatus(str, enum.Enum):
    SHADOW = "shadow"
    CHAMPION = "champion"
    RETIRED = "retired"


# ──────────────────────────────────────────────
# Mixin for timestamps
# ──────────────────────────────────────────────

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, lazy="selectin")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", lazy="noload")
    consents: Mapped[list["Consent"]] = relationship(back_populates="user", lazy="noload")


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ua_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Consent(TimestampMixin, Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ConsentKind] = mapped_column(Enum(ConsentKind), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="consents")

    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_consent_user_kind"),
    )


class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    age_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_categories: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    fav_colors: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    styles: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    occasions: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    user: Mapped["User"] = relationship(back_populates="profile")


class BodyProfile(TimestampMixin, Base):
    __tablename__ = "body_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    measurements_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    shape: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shape_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ratios: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[BodySource | None] = mapped_column(Enum(BodySource), nullable=True)
    user_corrected_shape: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)


class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind), nullable=False)
    bucket: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[MediaStatus] = mapped_column(Enum(MediaStatus), default=MediaStatus.PENDING)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WardrobeItem(TimestampMixin, Base):
    __tablename__ = "wardrobe_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id"), nullable=True
    )
    cutout_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    colors: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{name, hex, share}]
    pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    material: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sleeve: Mapped[str | None] = mapped_column(String(50), nullable=True)
    neckline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    length: Mapped[str | None] = mapped_column(String(50), nullable=True)
    style_tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    occasions: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    seasons: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    formality: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 lounge - 4 formal
    # embedding: vector(D) — added via pgvector extension, see migration
    attrs_confidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attrs_source: Mapped[AttrsSource | None] = mapped_column(Enum(AttrsSource), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    wear_count: Mapped[int] = mapped_column(Integer, default=0)
    last_worn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ItemLabelCorrection(TimestampMixin, Base):
    __tablename__ = "item_label_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wardrobe_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    predicted: Mapped[str | None] = mapped_column(String(200), nullable=True)
    corrected: Mapped[str] = mapped_column(String(200), nullable=False)


class Outfit(TimestampMixin, Base):
    __tablename__ = "outfits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occasion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    score_rules: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_model: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_final: Mapped[float | None] = mapped_column(Float, nullable=True)
    ranker_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    policy: Mapped[OutfitPolicy | None] = mapped_column(Enum(OutfitPolicy), nullable=True)
    propensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)


class OutfitItem(TimestampMixin, Base):
    __tablename__ = "outfit_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outfit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outfits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot: Mapped[OutfitSlot] = mapped_column(Enum(OutfitSlot), nullable=False)
    wardrobe_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wardrobe_items.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class OutfitEvent(TimestampMixin, Base):
    __tablename__ = "outfit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    outfit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outfits.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[OutfitEventType] = mapped_column(Enum(OutfitEventType), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy: Mapped[OutfitPolicy | None] = mapped_column(Enum(OutfitPolicy), nullable=True)
    propensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_outfit_events_user_ts", "user_id", "ts"),
    )


class UserStyleState(TimestampMixin, Base):
    __tablename__ = "user_style_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    style_dna: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # style_vector: vector(D) — added via pgvector, see migration
    n_events: Mapped[int] = mapped_column(Integer, default=0)


class CatalogProduct(TimestampMixin, Base):
    __tablename__ = "catalog_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    colors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    style_tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    occasions: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    formality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    # embedding: vector(D) — added via pgvector, see migration
    trend_tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_catalog_source_ext_id"),
    )


class WishlistItem(TimestampMixin, Base):
    __tablename__ = "wishlist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_products.id"), nullable=True
    )
    outfit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outfits.id"), nullable=True
    )


class Trend(TimestampMixin, Base):
    __tablename__ = "trends"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    # embedding: vector(D) — added via pgvector, see migration
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelVersion(TimestampMixin, Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[ModelKind] = mapped_column(Enum(ModelKind), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ModelStatus] = mapped_column(Enum(ModelStatus), default=ModelStatus.SHADOW)
    n_train: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
