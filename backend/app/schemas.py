"""Request schemas (server-side validation). Responses are plain dicts built by serializers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

Unit = Literal["m", "cm", "ft", "in"]
FarmingType = Literal["HYDROPONIC_NFT", "HYDROPONIC_DWC", "HYDROPONIC_EBB_FLOW", "AEROPONIC", "SOIL_CONTAINER"]
ObstacleKind = Literal["DOOR", "WINDOW", "PILLAR", "FURNITURE", "EQUIPMENT", "FIXED", "RESTRICTED"]


class SignupIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    preferences: dict | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    farming_type: FarmingType = "HYDROPONIC_NFT"
    budget: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    fx_rate_per_usd: float = Field(default=1.0, gt=0)
    electricity_rate: float | None = Field(default=None, ge=0)
    preferred_crop: str | None = None
    crop_categories: list[Literal["VEGETABLE", "HERB", "FRUIT"]] = []
    experience_level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = "BEGINNER"
    automation_level: Literal["MANUAL", "SEMI_AUTOMATED", "AUTOMATED"] = "MANUAL"
    priorities: list[str] = []
    desired_plant_count: int | None = Field(default=None, ge=1, le=100000)
    wizard_step: int | None = Field(default=None, ge=0, le=10)

    @field_validator("currency")
    @classmethod
    def upper(cls, v: str) -> str:
        if not v.isalpha():
            raise ValueError("Currency must be a 3-letter code")
        return v.upper()


class FarmPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None
    farming_type: FarmingType | None = None
    budget: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate_per_usd: float | None = Field(default=None, gt=0)
    electricity_rate: float | None = Field(default=None, ge=0)
    preferred_crop: str | None = None
    crop_categories: list[Literal["VEGETABLE", "HERB", "FRUIT"]] | None = None
    experience_level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] | None = None
    automation_level: Literal["MANUAL", "SEMI_AUTOMATED", "AUTOMATED"] | None = None
    priorities: list[str] | None = None
    desired_plant_count: int | None = Field(default=None, ge=1, le=100000)
    wizard_step: int | None = Field(default=None, ge=0, le=10)


class RoomIn(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Unit = "ft"
    grid_cell: float = Field(default=1.0, gt=0)
    grid_cell_unit: Unit = "ft"
    temperature_c: float | None = Field(default=None, ge=-20, le=60)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    light_source: Literal["GROW_LIGHTS", "SUNLIGHT", "MIXED", "UNKNOWN"] = "GROW_LIGHTS"
    water_access: bool | None = None
    electrical_access: bool | None = None
    market_location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def sane(self):
        from .services.units import to_m
        L, W, H = to_m(self.length, self.unit), to_m(self.width, self.unit), to_m(self.height, self.unit)
        if not (0.5 <= L <= 100 and 0.5 <= W <= 100):
            raise ValueError("Room length and width must each be between 0.5 m and 100 m")
        if not (1.0 <= H <= 20):
            raise ValueError("Room height must be between 1 m and 20 m")
        g = to_m(self.grid_cell, self.grid_cell_unit)
        if not (0.05 <= g <= min(L, W)):
            raise ValueError("Grid cell must be at least 5 cm and no larger than the room's shorter side")
        return self


class ObstacleIn(BaseModel):
    kind: ObstacleKind
    label: str | None = Field(default=None, max_length=80)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    d: float = Field(gt=0)
    height_m: float | None = Field(default=None, gt=0)
    clearance_m: float = Field(default=0.0, ge=0, le=5)
    confirmed: bool = True


class ObstaclePatch(BaseModel):
    kind: ObstacleKind | None = None
    label: str | None = Field(default=None, max_length=80)
    x: float | None = Field(default=None, ge=0)
    y: float | None = Field(default=None, ge=0)
    w: float | None = Field(default=None, gt=0)
    d: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    clearance_m: float | None = Field(default=None, ge=0, le=5)
    confirmed: bool | None = None


class RackConfigIn(BaseModel):
    rack_length_m: float = Field(default=1.2, gt=0.2, le=10)
    rack_depth_m: float = Field(default=0.45, gt=0.1, le=3)
    rack_height_m: float = Field(default=1.8, gt=0.3, le=10)
    levels: int = Field(default=4, ge=1, le=12)
    level_gap_m: float | None = Field(default=None, gt=0.05, le=3)
    plants_per_level: int | None = Field(default=None, ge=1, le=1000)
    plant_spacing_m: float | None = Field(default=None, gt=0.02, le=2)
    orientation: Literal["ANY", "X", "Y"] = "ANY"
    max_racks: int | None = Field(default=None, ge=1, le=500)
    walkway_m: float = Field(default=0.75, gt=0.2, le=5)
    obstacle_clearance_m: float = Field(default=0.15, ge=0, le=3)
    rack_gap_m: float = Field(default=0.05, ge=0, le=3)
    wall_clearance_m: float = Field(default=0.0, ge=0, le=3)
    ceiling_clearance_m: float = Field(default=0.3, ge=0, le=3)
    min_passage_m: float = Field(default=0.6, gt=0.2, le=3)


class RackIn(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    x: float
    y: float
    w: float = Field(gt=0)
    d: float = Field(gt=0)
    rotation: Literal[0, 90] = 0
    access_side: Literal["N", "S", "E", "W"] | None = None


class DesignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rack_config: RackConfigIn = RackConfigIn()
    racks: list[RackIn]
    crop_slug: str | None = None
    strategy: str | None = Field(default=None, max_length=200)
    activate: bool = True


class DesignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    rack_config: RackConfigIn | None = None
    racks: list[RackIn] | None = None
    crop_slug: str | None = None


class ValidateIn(BaseModel):
    rack_config: RackConfigIn | None = None
    racks: list[RackIn]


class CostItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    quantity: float = Field(ge=0)
    unit: str = Field(default="pcs", max_length=20)
    unit_price: float = Field(ge=0)
    cost_type: Literal["ONE_TIME", "MONTHLY"] = "ONE_TIME"
    status: Literal["REQUIRED", "OPTIONAL", "FUTURE"] = "REQUIRED"
    included: bool = True
    notes: str | None = Field(default=None, max_length=255)


class CostItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    quantity: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    included: bool | None = None
    status: Literal["REQUIRED", "OPTIONAL", "FUTURE"] | None = None
    cost_type: Literal["ONE_TIME", "MONTHLY"] | None = None
    notes: str | None = Field(default=None, max_length=255)


class MarketPriceIn(BaseModel):
    crop_slug: str
    price: float = Field(gt=0)
    unit: Literal["kg"] = "kg"
    location: str | None = Field(default=None, max_length=120)
    grade: str | None = Field(default=None, max_length=60)
    observed_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ScenarioChanges(BaseModel):
    rack_count: int | None = Field(default=None, ge=1, le=500)
    rack_length_m: float | None = Field(default=None, gt=0.2, le=10)
    rack_depth_m: float | None = Field(default=None, gt=0.1, le=3)
    rack_height_m: float | None = Field(default=None, gt=0.3, le=10)
    levels: int | None = Field(default=None, ge=1, le=12)
    walkway_m: float | None = Field(default=None, gt=0.2, le=5)
    plant_spacing_m: float | None = Field(default=None, gt=0.02, le=2)
    crop_slug: str | None = None
    budget: float | None = Field(default=None, ge=0)
    farming_type: FarmingType | None = None
    orientation: Literal["ANY", "X", "Y"] | None = None


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_design_id: int | None = None
    changes: ScenarioChanges


class ScenarioPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    changes: ScenarioChanges | None = None


class SimulatorPatch(BaseModel):
    mode: Literal["NORMAL", "WARNING", "ABNORMAL"] | None = None
    interval_s: int | None = Field(default=None, ge=1, le=3600)


class ThresholdIn(BaseModel):
    metric: Literal["temperature_c", "humidity_pct", "ph", "ec_ms_cm", "water_level_pct"]
    warn_min: float | None = None
    warn_max: float | None = None
    crit_min: float | None = None
    crit_max: float | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def order(self):
        if self.crit_min is not None and self.warn_min is not None and self.crit_min > self.warn_min:
            raise ValueError(f"{self.metric}: critical minimum must be ≤ warning minimum")
        if self.crit_max is not None and self.warn_max is not None and self.crit_max < self.warn_max:
            raise ValueError(f"{self.metric}: critical maximum must be ≥ warning maximum")
        return self


class AlertPatch(BaseModel):
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


class SensorIngestIn(BaseModel):
    """Schema a future ESP32/MQTT adapter would send (not used by hardware yet)."""
    temperature_c: float | None = None
    humidity_pct: float | None = None
    ph: float | None = None
    ec_ms_cm: float | None = None
    water_level_pct: float | None = None
    light_ppfd: float | None = None
    pump_on: bool | None = None
    fan_on: bool | None = None
