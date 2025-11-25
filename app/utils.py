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

# 종료 키워드 패턴 (문맥 고려)
END_PATTERNS = [
    r'종료',
    r'코칭\s*끝',
    r'stop',
    r'exit',
    r'quit',
    # 문맥을 포함한 패턴들
    r'끝\s*(?:낼게|낼래|내고|내요|내겠)',           # "끝낼게요", "끝내고 싶어요"
    r'그만\s*(?:할게|할래|해요|하겠|둘게|둘래)',     # "그만할게요", "그만둘래요"
    r'마무리\s*(?:할게|할래|해요|하겠)',            # "마무리할게요"
    r'(?:대화|코칭|얘기)\s*(?:끝|그만|마무리)',     # "대화 끝", "코칭 그만"
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
    r'혼자\s*(?:인\s*것\s*같|라고\s*느껴|남겨|버려)', r'외로워', r'아무도\s*없'
]

# 감정 패턴 (감정 인정 강화용)
EMOTION_PATTERNS = {
    'sadness': [r'슬퍼', r'슬프', r'우울', r'속상', r'힘들', r'지쳐'],
    'anxiety': [r'불안', r'걱정', r'두려', r'무서', r'긴장'],
    'frustration': [r'답답', r'막막', r'모르겠', r'어떻게'],
    'anger': [r'화나', r'짜증', r'억울', r'열받'],
    'positive': [r'기쁘', r'좋아', r'행복', r'설레', r'감사']
}

# 사람 언급 패턴 (맥락 연결용)
PEOPLE_PATTERNS = [
    r'(엄마|아빠|부모님|선생님|친구|언니|오빠|누나|형|동생|할머니|할아버지|남자친구|여자친구|선배|후배|반장|담임)'
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


def detect_emotions(message: str) -> list:
    """사용자 메시지에서 감정을 감지합니다."""
    detected = []
    for emotion, patterns in EMOTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message):
                detected.append(emotion)
                break
    return detected


def extract_mentioned_people(message: str) -> list:
    """메시지에서 언급된 사람들을 추출합니다."""
    people = []
    for pattern in PEOPLE_PATTERNS:
        matches = re.findall(pattern, message)
        people.extend(matches)
    return list(set(people))


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
