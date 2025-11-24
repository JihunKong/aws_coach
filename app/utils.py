"""
Utility functions for the coaching chatbot
"""
import re

# 세션 리셋 키워드 패턴
RESET_PATTERNS = [
    r'다시\s*시작',
    r'처음부터',
    r'새로\s*시작',
    r'리셋',
    r'reset',
    r'restart',
    r'다시\s*해',
    r'새로\s*해',
    r'코칭\s*다시',
    r'처음으로'
]

# 종료 키워드 패턴
END_PATTERNS = [
    r'종료',
    r'끝',
    r'그만',
    r'stop',
    r'exit',
    r'quit',
    r'코칭\s*끝',
    r'마무리',
    r'그만\s*하',
]

# 재개 확인 키워드
CONTINUE_PATTERNS = [
    r'계속',
    r'이어서',
    r'continue',
    r'네',
    r'yes',
    r'좋아',
    r'계속할게'
]

NEW_SESSION_PATTERNS = [
    r'새로',
    r'다시',
    r'새\s*주제',
    r'new',
    r'아니',
    r'no',
    r'다른'
]

# 위기 키워드 패턴
CRISIS_PATTERNS = [
    r'자해', r'자살', r'죽고\s*싶', r'사라지고\s*싶',
    r'폭력', r'학대', r'괴롭힘', r'왕따', r'때리', r'맞아',
    r'혼자', r'외로워', r'아무도\s*없'
]


def check_reset_keywords(message: str) -> bool:
    """사용자 메시지가 리셋 키워드를 포함하는지 확인합니다."""
    message_lower = message.lower().strip()
    for pattern in RESET_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


def check_end_keywords(message: str) -> bool:
    """사용자 메시지가 종료 키워드를 포함하는지 확인합니다."""
    message_lower = message.lower().strip()
    for pattern in END_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


def check_continue_keywords(message: str) -> bool:
    """사용자 메시지가 계속하기 키워드를 포함하는지 확인합니다."""
    message_lower = message.lower().strip()
    for pattern in CONTINUE_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


def check_new_session_keywords(message: str) -> bool:
    """사용자 메시지가 새 세션 키워드를 포함하는지 확인합니다."""
    message_lower = message.lower().strip()
    for pattern in NEW_SESSION_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


def check_crisis_keywords(message: str) -> bool:
    """위기 상황 키워드를 확인합니다."""
    message_lower = message.lower()
    for pattern in CRISIS_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


def get_conversation_summary(conversation_history: list) -> str:
    """대화 내용을 요약합니다."""
    if len(conversation_history) < 2:
        return "방금 대화를 시작했습니다"

    # 최근 5개 메시지에서 주요 내용 추출
    recent_messages = conversation_history[-5:]
    topics = []

    for msg in recent_messages:
        if msg.get('role') == 'user':
            content = msg.get('content', '')[:100]  # 100자까지만
            if content:
                topics.append(content)

    if topics:
        return f"{', '.join(topics[:2])}"  # 최대 2개 토픽만 표시

    return "이전 대화 내용"
