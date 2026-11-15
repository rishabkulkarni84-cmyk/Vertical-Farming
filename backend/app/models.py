"""SQLAlchemy ORM models. All lengths are stored in METRES; temperatures in °C.

Coordinate system (shared by backend, 2D and 3D views):
  origin (0, 0) = the room's top-left corner in the top-down plan;
  +x runs along the room LENGTH, +y runs along the room WIDTH, +z is up.
  A rectangle is (x, y, w, d): w along x, d along y.
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, text, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke sessions
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    farms: Mapped[list["Farm"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Farm(TimestampMixin, Base):
    __tablename__ = "farms"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | ARCHIVED
    farming_type: Mapped[str] = mapped_column(String(30), default="HYDROPONIC_NFT")
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    fx_rate_per_usd: Mapped[float] = mapped_column(Float, default=1.0)  # user-provided; converts illustrative prices
    electricity_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # per kWh in farm currency, user-provided
    preferred_crop: Mapped[str | None] = mapped_column(String(60), nullable=True)  # crop slug or None = recommend
    crop_categories: Mapped[list] = mapped_column(JSON, default=list)
    experience_level: Mapped[str] = mapped_column(String(20), default="BEGINNER")
    automation_level: Mapped[str] = mapped_column(String(20), default="MANUAL")
    priorities: Mapped[list] = mapped_column(JSON, default=list)
    desired_plant_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    wizard_step: Mapped[int] = mapped_column(Integer, default=0)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # BROWSER_GPS | USER_INPUT
    ai_crop_advice: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))  # last AI crop advice (MODEL output + sources)

    owner: Mapped[User] = relationship(back_populates="farms")
    room: Mapped["Room | None"] = relationship(back_populates="farm", cascade="all, delete-orphan", uselist=False)
    images: Mapped[list["RoomImage"]] = relationship(cascade="all, delete-orphan")
    obstacles: Mapped[list["Obstacle"]] = relationship(cascade="all, delete-orphan", order_by="Obstacle.id")
    designs: Mapped[list["Design"]] = relationship(cascade="all, delete-orphan", order_by="Design.id")


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("length_m > 0 AND width_m > 0 AND height_m > 0", name="ck_room_positive"),
        CheckConstraint("grid_cell_m > 0", name="ck_room_cell_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), unique=True)
    length_m: Mapped[float] = mapped_column(Float)
    width_m: Mapped[float] = mapped_column(Float)
    height_m: Mapped[float] = mapped_column(Float)
    input_unit: Mapped[str] = mapped_column(String(4), default="m")  # unit the user entered values in
    grid_cell_m: Mapped[float] = mapped_column(Float, default=0.3048)
    grid_cell_input: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_cell_unit: Mapped[str] = mapped_column(String(4), default="ft")
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    light_source: Mapped[str] = mapped_column(String(20), default="GROW_LIGHTS")  # GROW_LIGHTS | SUNLIGHT | MIXED | UNKNOWN
    water_access: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    electrical_access: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    market_location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    farm: Mapped[Farm] = relationship(back_populates="room")


class RoomImage(TimestampMixin, Base):
    __tablename__ = "room_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    analysis_status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING | COMPLETE | FAILED
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)


class Obstacle(TimestampMixin, Base):
    __tablename__ = "obstacles"
    __table_args__ = (CheckConstraint("w > 0 AND d > 0", name="ck_obstacle_positive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # DOOR | WINDOW | PILLAR | FURNITURE | EQUIPMENT | FIXED | RESTRICTED
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    d: Mapped[float] = mapped_column(Float)
    height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    clearance_m: Mapped[float] = mapped_column(Float, default=0.0)  # DOOR: swing / access depth into the room
    source: Mapped[str] = mapped_column(String(20), default="USER")  # USER | SUGGESTED
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)


class Design(TimestampMixin, Base):
    __tablename__ = "designs"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    rack_config: Mapped[dict] = mapped_column(JSON, default=dict)
    crop_slug: Mapped[str | None] = mapped_column(String(60), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="GENERATED")  # GENERATED | EDITED | SCENARIO
    strategy: Mapped[str | None] = mapped_column(String(200), nullable=True)
    racks: Mapped[list["RackPlacement"]] = relationship(cascade="all, delete-orphan", order_by="RackPlacement.id")
    cost_items: Mapped[list["CostItem"]] = relationship(cascade="all, delete-orphan", order_by="CostItem.id")


class RackPlacement(Base):
    __tablename__ = "rack_placements"
    id: Mapped[int] = mapped_column(primary_key=True)
    design_id: Mapped[int] = mapped_column(ForeignKey("designs.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(20))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)  # footprint along x after rotation
    d: Mapped[float] = mapped_column(Float)
    rotation: Mapped[int] = mapped_column(Integer, default=0)  # 0 = long axis along x, 90 = along y
    access_side: Mapped[str | None] = mapped_column(String(2), nullable=True)  # N|S|E|W side facing the aisle


class Crop(Base):
    __tablename__ = "crops"
    slug: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)  # requirements; unknown values are null
    provenance: Mapped[str] = mapped_column(Text)
    last_reviewed: Mapped[str] = mapped_column(String(10))


class CostItem(TimestampMixin, Base):
    __tablename__ = "cost_items"
    __table_args__ = (CheckConstraint("quantity >= 0 AND unit_price >= 0", name="ck_cost_nonneg"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    design_id: Mapped[int] = mapped_column(ForeignKey("designs.id", ondelete="CASCADE"), index=True)
    key: Mapped[str | None] = mapped_column(String(40), nullable=True)  # stable key for auto-generated lines
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    unit_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    price_source: Mapped[str] = mapped_column(String(20), default="ILLUSTRATIVE")  # ILLUSTRATIVE | USER_INPUT | EXTERNAL_DATA
    source_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cost_type: Mapped[str] = mapped_column(String(10), default="ONE_TIME")  # ONE_TIME | MONTHLY
    status: Mapped[str] = mapped_column(String(10), default="REQUIRED")  # REQUIRED | OPTIONAL | FUTURE
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    quantity_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # user edited quantity; don't auto-recompute
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)


class MarketPrice(TimestampMixin, Base):
    __tablename__ = "market_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    crop_slug: Mapped[str] = mapped_column(String(60))
    price: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="kg")
    currency: Mapped[str] = mapped_column(String(3))
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="USER_INPUT")
    observed_on: Mapped[str | None] = mapped_column(String(10), nullable=True)


class Scenario(TimestampMixin, Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    base_design_id: Mapped[int | None] = mapped_column(ForeignKey("designs.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    applied_design_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SimulatorState(TimestampMixin, Base):
    __tablename__ = "simulator_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="STOPPED")  # RUNNING | PAUSED | STOPPED
    mode: Mapped[str] = mapped_column(String(10), default="NORMAL")  # NORMAL | WARNING | ABNORMAL
    interval_s: Mapped[int] = mapped_column(Integer, default=5)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # last values for smooth random walk


class SensorRecord(Base):
    __tablename__ = "sensor_records"
    __table_args__ = (Index("ix_sensor_farm_ts", "farm_id", "ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str] = mapped_column(String(12))  # SIMULATED | DEVICE
    device_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    ec_ms_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    tds_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_level_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    light_ppfd: Mapped[float | None] = mapped_column(Float, nullable=True)
    pump_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fan_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    energy_wh: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_l: Mapped[float | None] = mapped_column(Float, nullable=True)


class Threshold(Base):
    __tablename__ = "thresholds"
    __table_args__ = (UniqueConstraint("farm_id", "metric", name="uq_threshold_metric"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(30))
    warn_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    warn_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    crit_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    crit_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    basis: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_farm_created", "farm_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"))
    record_id: Mapped[int | None] = mapped_column(ForeignKey("sensor_records.id", ondelete="SET NULL"), nullable=True)
    metric: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))  # WARNING | CRITICAL
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(String(300))
    suggestion: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(14), default="OPEN")  # OPEN | ACKNOWLEDGED | RESOLVED
    source_type: Mapped[str] = mapped_column(String(14), default="RULE")
    data_source: Mapped[str] = mapped_column(String(12), default="SIMULATED")


class Insight(TimestampMixin, Base):
    __tablename__ = "insights"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))  # HIGH | MEDIUM | LOW
    title: Mapped[str] = mapped_column(String(160))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(14))  # RULE | MODEL | USER_INPUT | EXTERNAL_DATA
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiSetting(TimestampMixin, Base):
    """Per-user AI provider configuration. The key stays on the server and is never returned to the browser."""
    __tablename__ = "ai_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(20))  # gemini | anthropic | openai
    api_key: Mapped[str] = mapped_column(String(400))
    model: Mapped[str] = mapped_column(String(120))
    web_search: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
