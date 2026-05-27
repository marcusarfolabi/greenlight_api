# Conditional AI Token Usage

## Overview

The Greenlight platform supports **conditional AI token usage** at the organization level. Organizations can enable or disable AI-powered arena features independently, allowing flexibility in token consumption.

## Feature

### `use_ai_for_arenas` Setting

Located in **Organization Model** and **Settings API**:

```python
# In Organization model
use_ai_for_arenas: Mapped[bool] = mapped_column(default=True)
```

**Default:** `True` (AI features enabled)

## How It Works

### 1. When AI is **ENABLED** (`use_ai_for_arenas = True`)

- ✅ Token costs calculated for each question
- ✅ Organization token balance checked before arena creation
- ✅ Tokens deducted from organization quota
- ✅ Token usage logged for auditing
- ⚠️ Returns `402 Payment Required` if insufficient tokens

### 2. When AI is **DISABLED** (`use_ai_for_arenas = False`)

- ✅ Arenas can still be created
- ✅ Questions can be added manually
- ❌ **NO tokens deducted** from quota
- ❌ Token checks are skipped
- ✅ No payment errors for token limits

## API Endpoints

### Update Organization Settings

Update the `use_ai_for_arenas` setting via organization settings endpoint:

```http
PUT /v1/organizations/settings
Authorization: Bearer {token}
Content-Type: application/json

{
  "arena": {
    "use_ai_for_arenas": false
  }
}
```

**Request Body:**

```json
{
  "arena": {
    "use_ai_for_arenas": true/false
  }
}
```

**Response:** `200 OK`

```json
{
  "id": 1,
  "use_ai_for_arenas": false,
  "enable_payouts": true,
  ...
}
```

### Get Organization Settings

```http
GET /v1/organizations/settings
Authorization: Bearer {token}
```

**Response:** `200 OK`

```json
{
  "id": 1,
  "use_ai_for_arenas": false,
  "show_leaderboard": true,
  "timer_enabled": true,
  ...
}
```

## Arena Creation Logic

### Token Calculation Flow

```
CREATE ARENA REQUEST
    ↓
[Check if org.use_ai_for_arenas == True]
    ↓
    ├─→ TRUE:  Calculate token cost for each question
    │           ↓
    │          Check token availability
    │           ↓
    │          If insufficient: Return 402 Payment Required
    │           ↓
    │          Deduct tokens from org quota
    │           ↓
    │          Log token usage
    │
    └─→ FALSE: Skip all token calculations
                ↓
               Create arena with NO token deductions
```

### Code Example

```python
# In create_arena endpoint
org = user.owned_organization

if org.use_ai_for_arenas:
    # Calculate tokens needed
    total_tokens_needed = sum(
        TokenService.calculate_question_cost(...)
        for q in data.questions
    )

    # Check availability
    can_use, error = TokenService.can_use_tokens(db, org_id, total_tokens_needed)
    if not can_use:
        raise HTTPException(402, error)
else:
    # Skip all token checks - AI is disabled
    total_tokens_needed = 0
```

## Use Cases

### Scenario 1: Organization with AI Enabled (Default)

- **Setting:** `use_ai_for_arenas = true`
- **Behavior:** Full token tracking and enforcement
- **Token Cost:** ~100-200 tokens per question
- **Best For:** Organizations using AI question generation

### Scenario 2: Organization with AI Disabled

- **Setting:** `use_ai_for_arenas = false`
- **Behavior:** Manual question creation without token costs
- **Token Cost:** 0 tokens
- **Best For:** Organizations using manually-written questions or on Free plan

### Scenario 3: Switching Between States

```
Organization starts with AI enabled
    ↓
Creates 10 arenas (uses 1,500 tokens)
    ↓
Disables AI via settings
    ↓
Creates 5 more arenas (uses 0 tokens)
    ↓
Remaining token balance unchanged
```

## Database Schema

```sql
-- organizations table
CREATE TABLE organizations (
    id INT PRIMARY KEY,
    use_ai_for_arenas BOOLEAN DEFAULT TRUE,
    ...
);

-- Arena creation still tracked
CREATE TABLE arenas (
    id INT PRIMARY KEY,
    creator_organization_id INT,
    ai_tokens_used INT DEFAULT 0,  -- 0 if AI disabled
    ...
);
```

## Response Examples

### Arena Creation - AI Enabled

```bash
curl -X POST http://localhost:8000/v1/arenas/ \
  -H "Authorization: Bearer token" \
  -H "Content-Type: application/json" \
  -d '{
    "arena_name": "Quiz",
    "questions": [...]
  }'
```

**Response:** `201 Created`

```json
{
  "id": 5,
  "ai_tokens_used": 150,
  "arena_name": "Quiz",
  ...
}
```

### Arena Creation - AI Disabled

```bash
# Same request, but org has use_ai_for_arenas = false
```

**Response:** `201 Created`

```json
{
  "id": 6,
  "ai_tokens_used": 0,  // No tokens deducted
  "arena_name": "Quiz",
  ...
}
```

### Insufficient Tokens (AI Enabled)

```bash
curl -X POST http://localhost:8000/v1/arenas/ \
  -H "Authorization: Bearer token" \
  -H "Content-Type: application/json" \
  -d '{
    "arena_name": "Quiz with many questions",
    "questions": [... 100 questions requiring 5000 tokens]
  }'
```

**Response:** `402 Payment Required`

```json
{
  "detail": "Insufficient tokens. Required: 5000, Available: 2500"
}
```

## Settings Schema

### Organization Settings Update Schema

```python
class OrgArenaSettings(BaseModel):
    use_ai_for_arenas: bool = Field(
        default=True,
        description="Enable AI-powered arena question generation"
    )

class OrgSettingsUpdate(BaseModel):
    arena: Optional[OrgArenaSettings] = None
    # ... other settings
```

## Logging

Token operations are logged differently based on AI setting:

**AI Enabled:**

```
INFO: Arena 5 created by user 10, consumed 150 tokens
```

**AI Disabled:**

```
INFO: Arena 6 created by user 10 (AI usage disabled for organization)
```

## Migration Path

### For Existing Organizations

1. Organizations default to `use_ai_for_arenas = True`
2. All existing token tracking continues
3. Organizations can opt-out via settings

### For New Organizations

1. Check subscription plan
2. Set `use_ai_for_arenas = True` (default)
3. Token quota based on subscription

## Future Enhancements

1. **Per-Arena AI Toggle** - Allow some arenas to use AI, others not
2. **AI Token Marketplace** - Buy/sell unused tokens
3. **Usage Analytics** - Detailed breakdown of AI vs manual questions
4. **Smart Defaults** - Auto-disable AI when tokens run low
5. **Free Trial** - Limited AI tokens for Free plan users

## Troubleshooting

### Issue: Cannot create arena, getting 402 error

**Solution 1:** Check token balance

```bash
curl http://localhost:8000/v1/arenas/tokens/usage \
  -H "Authorization: Bearer token"
```

**Solution 2:** Disable AI if not needed

```bash
curl -X PUT http://localhost:8000/v1/organizations/settings \
  -H "Authorization: Bearer token" \
  -d '{"arena": {"use_ai_for_arenas": false}}'
```

### Issue: Want to disable AI for manual questions

**Solution:**

```bash
PUT /v1/organizations/settings
{
  "arena": {"use_ai_for_arenas": false}
}
```

All subsequent arena creations will not deduct tokens.

### Issue: Re-enable AI after disabling

**Solution:**

```bash
PUT /v1/organizations/settings
{
  "arena": {"use_ai_for_arenas": true}
}
```

Token checks resume for new arenas.
