# Arena API with AI Token Tracking

## Overview

The Arena API is a fully implemented quiz/question management system with integrated AI token tracking. It allows users to create, manage, and track interactive question arenas with built-in token usage monitoring for AI-powered features.

## Features

### 1. Arena Management

- **Create arenas** with multiple questions
- **List user arenas** with pagination
- **View arena details** with token usage statistics
- **Update arena** settings (name, visibility)
- **Delete arenas** and cascade question cleanup

### 2. AI Token Tracking

- **Per-question token costs** calculated based on content length
- **Organization-level token quotas** from subscription plans
- **Token usage logging** for auditing
- **Automatic validation** before creating questions
- **Real-time token balance** tracking

### 3. Question Management

- Create multiple questions per arena
- Track AI generation status and costs
- Store options and correct answers
- Time limits and point values

## Database Models

### Arena

```python
id                          # Primary key
title                       # Arena name
is_public                   # Visibility
creator_id                  # User who created it
creator_organization_id     # Associated organization
ai_tokens_used             # Total tokens consumed
ai_tokens_budget           # Optional per-arena limit
created_at / updated_at    # Timestamps
```

### Question

```python
id
arena_id                   # Link to arena
prompt_text               # Question text
time_limit_seconds        # Question timer
point_value              # Points for correct answer
correct_option_index     # Correct answer index
ai_tokens_cost          # Tokens used to generate
is_ai_generated         # Whether AI created this
created_at
```

### ArenaTokenUsageLog

```python
id
arena_id                 # Which arena
tokens_used             # Amount used
operation               # Type of operation
details                 # Additional info
created_at
```

## API Endpoints

### 1. Create Arena

```http
POST /v1/arenas/
Content-Type: application/json

{
  "arena_name": "JavaScript Quiz",
  "category": "Programming",
  "is_public": false,
  "questions": [
    {
      "prompt_text": "What is a closure?",
      "time_limit_seconds": 30,
      "options": ["A", "B", "C", "D"],
      "correct_option_index": 0,
      "point_value": 10,
      "is_ai_generated": true,
      "ai_tokens_cost": 0
    }
  ]
}
```

**Response:** `201 Created`

```json
{
  "id": 1,
  "arena_name": "JavaScript Quiz",
  "category": "Programming",
  "is_public": false,
  "creator_id": 5,
  "creator_organization_id": 1,
  "ai_tokens_used": 125,
  "questions": [...],
  "created_at": "2026-05-27T10:00:00Z"
}
```

**Token Deduction:** Tokens are checked and deducted immediately upon creation

### 2. List User Arenas

```http
GET /v1/arenas/?skip=0&limit=10
Authorization: Bearer {token}
```

**Response:** `200 OK`

```json
[
  {
    "id": 1,
    "arena_name": "JavaScript Quiz",
    "ai_tokens_used": 125,
    ...
  },
  ...
]
```

### 3. Get Arena Details

```http
GET /v1/arenas/{arena_id}
Authorization: Bearer {token}
```

**Response:** `200 OK`

```json
{
  "id": 1,
  "arena_name": "JavaScript Quiz",
  "ai_tokens_used": 125,
  "questions": [...],
  "token_info": {
    "ai_tokens_used": 125,
    "ai_tokens_budget": null,
    "total_questions": 5,
    "ai_generated_questions": 3
  },
  ...
}
```

### 4. Update Arena

```http
PUT /v1/arenas/{arena_id}
Authorization: Bearer {token}
Content-Type: application/json

{
  "arena_name": "Updated Quiz Name",
  "is_public": true
}
```

**Response:** `200 OK`

### 5. Delete Arena

```http
DELETE /v1/arenas/{arena_id}
Authorization: Bearer {token}
```

**Response:** `200 OK`

```json
{
  "message": "Arena deleted successfully"
}
```

### 6. Get Token Usage

```http
GET /v1/arenas/tokens/usage
Authorization: Bearer {token}
```

**Response:** `200 OK`

```json
{
  "total_tokens": 10000,
  "used_tokens": 1250,
  "remaining_tokens": 8750,
  "plan_name": "Standard",
  "plan_type": "standard",
  "has_tokens": true
}
```

## Token Calculation

### Cost Formula

```
base_cost = 50 tokens
prompt_cost = max(1, prompt_length / 100)
options_cost = num_options * 10

total_cost = base_cost + prompt_cost + options_cost
```

### Examples

- Simple 5-option question (100 chars): ~100 tokens
- Complex question (500 chars): ~150 tokens
- Long prompt (1000 chars): ~200 tokens

## Error Handling

### Insufficient Tokens

```http
POST /v1/arenas/
```

**Response:** `402 Payment Required`

```json
{
  "detail": "Insufficient tokens. Required: 500, Available: 250"
}
```

### No Organization

```http
POST /v1/arenas/
```

**Response:** `400 Bad Request`

```json
{
  "detail": "User must have an organization to create arenas"
}
```

### Unauthorized Access

```http
GET /v1/arenas/{someone_else_arena_id}
```

**Response:** `403 Forbidden`

```json
{
  "detail": "Not authorized to view this arena"
}
```

### Not Found

```http
GET /v1/arenas/999
```

**Response:** `404 Not Found`

```json
{
  "detail": "Arena not found"
}
```

## Integration Points

### With Subscriptions

- Token limits determined by subscription plan
- Free plan: 500 tokens/month
- Standard plan: 10,000 tokens/month
- Pro plan: 100,000 tokens/month

### With Users

- Each arena linked to creator user
- Each arena linked to creator's organization
- Token usage aggregated per organization

### With AI Services

- Questions marked as `is_ai_generated`
- Token cost pre-calculated
- Integration point for OpenAI/Claude API calls

## Service Methods

### TokenService.get_organization_tokens()

```python
token_info = TokenService.get_organization_tokens(db, org_id)
# Returns: {
#   'total_tokens': 10000,
#   'used_tokens': 1250,
#   'remaining_tokens': 8750,
#   'plan_name': 'Standard',
#   'has_tokens': True
# }
```

### TokenService.can_use_tokens()

```python
can_use, error = TokenService.can_use_tokens(db, org_id, 500)
# Returns: (True, None) or (False, "error message")
```

### TokenService.calculate_question_cost()

```python
cost = TokenService.calculate_question_cost(
  prompt_length=500,
  num_options=4,
  use_ai_generation=True
)
# Returns: 150
```

### TokenService.log_token_usage()

```python
TokenService.log_token_usage(
  db, arena_id, tokens_used=150, operation="question_generation"
)
```

## Database Queries

### Get all arenas for an organization

```python
arenas = db.query(Arena).filter(
  Arena.creator_organization_id == org_id
).all()
```

### Get token usage history

```python
logs = db.query(ArenaTokenUsageLog).filter(
  ArenaTokenUsageLog.arena_id == arena_id
).order_by(ArenaTokenUsageLog.created_at.desc()).all()
```

### Calculate total tokens used by organization

```python
total = db.query(Arena).filter(
  Arena.creator_organization_id == org_id
).with_entities(
  db.func.sum(Arena.ai_tokens_used)
).scalar() or 0
```

## Future Enhancements

1. **Token Refund Mechanism** - Allow refunding tokens for deleted questions
2. **Batch Operations** - Create multiple arenas in one call
3. **Token Top-up** - Purchase additional tokens
4. **Usage Analytics** - Detailed token usage reports
5. **Question Templates** - Predefined questions without token cost
6. **AI Integration** - Automatic question generation via OpenAI
7. **Export/Import** - Backup arenas with token preservation
8. **Notifications** - Alert when approaching token limit

## Testing

```bash
# Create arena with token checking
curl -X POST http://localhost:8000/v1/arenas/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d @arena_payload.json

# Check token usage
curl http://localhost:8000/v1/arenas/tokens/usage \
  -H "Authorization: Bearer {token}"

# List user's arenas
curl http://localhost:8000/v1/arenas/ \
  -H "Authorization: Bearer {token}"
```
