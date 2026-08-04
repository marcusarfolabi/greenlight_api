from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrganizationBase(BaseModel):
    name: str
    industry: str
    capped_tokens: int | None = None


class OrganizationCreate(OrganizationBase):
    owner_id: int | None = None
    first_name: str
    last_name: str
    phone_number: str
    role: str


class OrganizationUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    is_verified: bool | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None


class OrganizationResponse(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    is_verified: bool
    created_at: datetime
    updated_at: datetime


# ============ ORGANIZATION SETTINGS SCHEMAS ============


class PayoutRuleCreate(BaseModel):
    position: str = Field(..., description="Position tier (1st, 2nd, 3rd, top_5, etc.)")
    amount: float = Field(..., description="Payout amount in dollars")


class PayoutRuleUpdate(BaseModel):
    position: str | None = None
    amount: float | None = None


class PayoutRuleResponse(PayoutRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime


class StripeConnectStatus(BaseModel):
    connected: bool = False
    stripe_connect_id: str | None = None
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False
    onboarding_complete: bool = False


class StripeOnboardingResponse(BaseModel):
    onboarding_url: str
    stripe_connect_id: str


class OrgBrandingSettings(BaseModel):
    brand_color: str = Field(
        default="#10B981", description="Hex color code for branding"
    )


class OrgVisibilitySettings(BaseModel):
    show_leaderboard: bool = Field(
        default=True, description="Show live leaderboard to players"
    )
    show_final_podium: bool = Field(
        default=True, description="Display top 3 winners with celebrations"
    )
    engagement_overlays: bool = Field(
        default=True, description="Show polls and reactions during game"
    )
    is_public: bool = Field(default=False, description="Make arena resources public")
    timer_enabled: bool = Field(
        default=True, description="Add countdown timer to questions"
    )
    waiting_lobby: bool = Field(
        default=True, description="Hold players in waiting room before start"
    )


class OrgArenaSettings(BaseModel):
    use_ai_for_arenas: bool = Field(
        default=True,
        description="Enable AI-powered arena question generation and token usage",
    )


class OrgPayoutSettings(BaseModel):
    enable_payouts: bool = Field(default=False, description="Enable financial payouts")
    request_payout_details: bool = Field(
        default=True, description="Request payout details from winners"
    )
    payout_method: str = Field(
        default="stripe", description="Payout method (stripe or bank)"
    )
    payout_rules: list[PayoutRuleCreate] = Field(
        default=[], description="Reward tiers and amounts"
    )


class OrgSettingsUpdate(BaseModel):
    """Complete organization settings update schema"""

    branding: OrgBrandingSettings | None = None
    visibility: OrgVisibilitySettings | None = None
    arena: OrgArenaSettings | None = None
    payouts: OrgPayoutSettings | None = None


class WalletTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: int
    type: str
    description: str | None = None
    status: str
    stripe_reference: str | None = None
    created_at: datetime


class WalletSummaryResponse(BaseModel):
    balance: int = Field(..., description="Available balance in cents")
    total_spent: int = Field(..., description="Total spent in cents")
    pending_withheld: int = Field(
        ..., description="Pending or withheld amount in cents"
    )
    currency: str = "usd"
    stripe_connect_id: str | None = None
    offset: int = 0
    limit: int = 10
    has_more: bool = False
    transactions: list[WalletTransactionResponse] = Field(default_factory=list)


class OrgSettingsResponse(BaseModel):
    """Complete organization settings response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    # Branding
    brand_color: str

    # Visibility
    show_leaderboard: bool
    show_final_podium: bool
    engagement_overlays: bool
    is_public: bool
    timer_enabled: bool
    waiting_lobby: bool

    # Arena
    use_ai_for_arenas: bool

    # Payouts
    enable_payouts: bool
    request_payout_details: bool
    payout_method: str
    payout_rules: list[PayoutRuleResponse]


class OrgSettingsSaveResponse(OrgSettingsResponse):
    """Returned after saving settings; may include a Stripe onboarding redirect URL."""


# ===== Wallet Top-up Schemas
class CreateTopUpRequest(BaseModel):
    amount: float = Field(..., description="Top-up amount in dollars")
    currency: str | None = Field(
        None, description="ISO currency code (e.g. 'usd', 'gbp')"
    )


class CreateTopUpResponse(BaseModel):
    client_secret: str
    payment_intent_id: str
    amount: float
    currency: str


class ConfirmTopUpRequest(BaseModel):
    payment_intent_id: str
