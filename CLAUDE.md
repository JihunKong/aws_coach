# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AWS Lambda-based coaching chatbot for KakaoTalk that uses AI (Claude/OpenAI) to provide educational coaching through structured conversation stages. The bot manages multi-turn conversations with session state stored in DynamoDB and follows a progressive coaching framework (Trust → Discover → Design → Success).

## Architecture

### Core Components

**Lambda Functions:**
- `lambda_funtion.py` - Main async Lambda handler with OpenAI integration and CSV-based coaching questions
- `lambda_callback` - Claude-based handler with structured coaching stages and session summarization
- `lambda_test1` - Async version with aiohttp for improved performance
- `lambda_11.24.latest` - Latest production version

**AWS Services:**
- DynamoDB tables: `chatbot_sessions` (active sessions), `chatbot_completed_sessions` (historical data)
- S3 bucket: `coaching-chatbot-data` (stores coach.csv with coaching questions)

**API Integration:**
- Anthropic Claude API (claude-3-5-haiku-20241022, claude-3-opus-20240229)
- OpenAI API (gpt-4o-mini)
- Upstage API (solar-pro2 model)
- KakaoTalk webhook format (version 2.0)

### Coaching Framework

The system implements a 4-stage coaching model:

1. **Trust** - Building rapport, understanding current situation, setting expectations
2. **Discover** - Deep exploration, root cause analysis, identifying resources and obstacles
3. **Design** - Action planning, strategy development, setting success metrics
4. **Success** - Progress review, celebrating achievements, planning next steps

Each stage has defined objectives and transition criteria evaluated by AI analysis.

### Session Management

**SessionManager class** handles:
- In-memory caching with 5-minute TTL to reduce DynamoDB calls
- Session expiration (7-day TTL)
- Conversation history (maintains last 20 exchanges)
- Progress tracking across coaching stages
- Session summarization every 5 messages
- Significant change detection (themes, emotional state, insights)

**Session Data Structure:**
```python
{
    'user_id': str,
    'current_stage': 'Trust' | 'Discover' | 'Design' | 'Success',
    'conversation_history': list,
    'coaching_goals': list,
    'action_items': list,
    'session_summary': dict,  # AI-generated summary every 5 messages
    'summary_history': list,  # Last 5 summaries
    'last_interaction': ISO timestamp,
    'ttl': int  # Unix timestamp for DynamoDB expiration
}
```

### User Type System

The Flask-based README.md describes a planned multi-user-type system:
- **Teacher** - Classroom management and teaching challenges
- **Student** - Academic, career, and relationship concerns
- **General** - Work and daily life coaching

The Lambda implementations use a stage-based approach without explicit user typing.

## Development Commands

### Testing Lambda Functions

```bash
# Test with sample KakaoTalk webhook payload
python lambda_funtion.py
```

### AWS Deployment

```bash
# Package dependencies
pip install -r requirements.txt -t package/
cd package && zip -r ../lambda_package.zip . && cd ..
zip -g lambda_package.zip lambda_funtion.py

# Deploy via AWS CLI
aws lambda update-function-code \
  --function-name coaching-chatbot \
  --zip-file fileb://lambda_package.zip
```

### Environment Variables Required

```bash
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key
UPSTAGE_API_KEY=your_key
AWS_REGION=ap-northeast-2
```

## Key Implementation Details

### Response Generation Flow

1. Extract user message from KakaoTalk webhook
2. Retrieve/create session from DynamoDB (with cache)
3. Generate coaching prompt based on current stage and session context
4. Call AI API with structured prompt
5. Parse JSON response containing analysis, coaching message, and metadata
6. Check if stage transition criteria are met
7. Update session state in DynamoDB
8. Return KakaoTalk-formatted response

### Async Optimization Patterns

`lambda_test1` demonstrates async patterns:
- `aiohttp.ClientSession` for non-blocking API calls
- `asyncio.gather()` for concurrent operations
- `asyncio.get_event_loop().run_in_executor()` for blocking DynamoDB calls

### Prompt Engineering Structure

AI prompts include:
- Current coaching stage purpose and objectives
- Session summary (key themes, insights, emotional state)
- Recent conversation history (last 3-5 exchanges)
- User's current message
- Expected JSON response format with analysis and coaching message

### Error Handling

- Fallback responses for each coaching stage when API fails
- Retry logic with exponential backoff (3 attempts)
- Default session creation on DynamoDB errors
- Graceful JSON parsing with fallback to plain text
- Always returns 200 status to KakaoTalk (errors sent as text messages)

### CSV Question Loading

`lambda_funtion.py` loads coaching questions from S3:
- CSV structure: step, Question1, Question2, follow-up questions, Transition
- LRU caching with 1-hour TTL to minimize S3 reads
- Organized by coaching stage with primary/follow-up/transition questions

## Testing Notes

- Use KakaoTalk webhook test events with `userRequest.utterance` field
- Session data persists across conversations via `user_id`
- DynamoDB TTL automatically cleans up old sessions after 7 days
- Test events can include `"test": true` flag for health checks

## Performance Considerations

- Session caching reduces DynamoDB read costs significantly
- Connection pooling (max 50 connections) for HTTP clients
- Adaptive retry mode for AWS SDK calls
- Conversation history limited to last 20 exchanges to control prompt size
- API timeout set to 25 seconds to stay within Lambda limits
- Async operations reduce cold start impact in test1 version
