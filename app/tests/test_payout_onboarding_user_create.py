from app.schemas.user import UserCreate


def test_user_create_accepts_password_and_string_org_id():
    payload = UserCreate(
        username="payout-user",
        email="payout@example.com",
        password="StrongPass123!",
        first_name="Payout",
        phone_number="+1234567890",
        role="user",
        is_active=False,
        organization_id="42",
        accepted_terms=True,
    )

    assert payload.password == "StrongPass123!"
    assert payload.organization_id == "42"
