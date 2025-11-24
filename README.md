
## 1. 프로젝트 구조

```
coaching-bot/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Flask 앱
│   ├── coaching_service.py     # 코칭 로직
│   ├── session_manager.py      # 세션 관리
│   ├── api_client.py           # Upstage API 클라이언트
│   ├── prompts.py              # 프롬프트 관리
│   └── utils.py                # 유틸리티
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── nginx.conf
└── deploy.sh
```

## 2. Flask 애플리케이션 (main.py)

```python
# app/main.py
from flask import Flask, request, jsonify
import logging
import os
from coaching_service import CoachingService
from datetime import datetime

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
coaching_service = CoachingService()

# 요청 통계
request_count = 0
error_count = 0
start_time = datetime.now()

@app.before_request
def log_request():
    """요청 로깅"""
    logger.info(f"Request: {request.method} {request.path} from {request.remote_addr}")

@app.after_request
def log_response(response):
    """응답 로깅"""
    logger.info(f"Response: {response.status_code}")
    return response

@app.route('/health', methods=['GET'])
def health_check():
    """헬스 체크 엔드포인트"""
    uptime = (datetime.now() - start_time).total_seconds()
    return jsonify({
        "status": "healthy",
        "uptime_seconds": uptime,
        "total_requests": request_count,
        "error_count": error_count,
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/stats', methods=['GET'])
def stats():
    """통계 엔드포인트"""
    return jsonify({
        "total_requests": request_count,
        "error_count": error_count,
        "success_rate": (request_count - error_count) / request_count * 100 if request_count > 0 else 0,
        "uptime_seconds": (datetime.now() - start_time).total_seconds()
    }), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """카카오톡 웹훅 엔드포인트"""
    global request_count, error_count
    request_count += 1
    
    try:
        # 요청 데이터 파싱
        data = request.get_json()
        if not data:
            logger.error("No JSON data received")
            error_count += 1
            return jsonify(coaching_service.error_response()), 200
        
        logger.info(f"Received data: {data}")
        
        # 코칭 서비스 처리
        response = coaching_service.process_message(data)
        
        logger.info(f"Sending response: {response}")
        return jsonify(response), 200
        
    except Exception as e:
        error_count += 1
        logger.error(f"Error in webhook: {str(e)}", exc_info=True)
        return jsonify(coaching_service.error_response()), 200

@app.errorhandler(404)
def not_found(error):
    """404 에러 핸들러"""
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    """500 에러 핸들러"""
    logger.error(f"Internal error: {str(error)}", exc_info=True)
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
```

## 3. 코칭 서비스 (coaching_service.py)

```python
# app/coaching_service.py
import logging
from session_manager import SessionManager
from api_client import UpstageAPIClient
from prompts import PromptManager
from utils import (
    check_reset_keywords,
    check_end_keywords,
    detect_user_type,
    get_user_type_prompt,
    check_crisis_keywords
)

logger = logging.getLogger(__name__)

class CoachingService:
    def __init__(self):
        self.session_manager = SessionManager()
        self.api_client = UpstageAPIClient()
        self.prompt_manager = PromptManager()
    
    def process_message(self, data: dict) -> dict:
        """메시지를 처리하고 응답을 생성합니다."""
        try:
            user_request = data.get('userRequest', {})
            user_id = user_request.get('user', {}).get('id', 'unknown')
            user_message = user_request.get('utterance', '')
            
            logger.info(f"Processing message from user {user_id}: {user_message}")
            
            # 세션 조회
            session_data = self.session_manager.get_session(user_id)
            
            # 사용자 유형 확인
            if not session_data.get('user_type_confirmed'):
                return self._handle_user_type_selection(user_id, user_message, session_data)
            
            # 리셋 명령어
            if check_reset_keywords(user_message):
                return self._handle_reset(user_id)
            
            # 종료 명령어
            if check_end_keywords(user_message):
                return self._handle_end(user_id, session_data)
            
            # 위기 키워드 체크
            if check_crisis_keywords(user_message):
                session_data['crisis_detected'] = True
                logger.warning(f"Crisis keywords detected for user {user_id}")
            
            # 코칭 진행
            return self._handle_coaching(user_id, user_message, session_data)
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            return self.error_response()
    
    def _handle_user_type_selection(self, user_id: str, message: str, session_data: dict) -> dict:
        """사용자 유형 선택을 처리합니다."""
        detected_type = detect_user_type(message)
        
        if detected_type:
            session_data['user_type'] = detected_type
            session_data['user_type_confirmed'] = True
            self.session_manager.update_session(session_data)
            
            type_names = {"teacher": "교사", "student": "학생", "general": "일반인"}
            response_text = f"{type_names[detected_type]}으로 등록되었습니다! 편안하게 고민을 나눠주세요. 😊\n\n오늘은 어떤 이야기를 나누고 싶으신가요?"
        
        elif message in ['1', '1️⃣', '교사']:
            session_data['user_type'] = 'teacher'
            session_data['user_type_confirmed'] = True
            self.session_manager.update_session(session_data)
            response_text = "교사로 등록되었습니다! 수업이나 학급 운영 고민을 편하게 나눠주세요. 😊\n\n오늘은 어떤 이야기를 나누고 싶으신가요?"
        
        elif message in ['2', '2️⃣', '학생']:
            session_data['user_type'] = 'student'
            session_data['user_type_confirmed'] = True
            self.session_manager.update_session(session_data)
            response_text = "학생으로 등록되었습니다! 학업, 진로, 친구 관계 고민을 편하게 나눠주세요. 😊\n\n오늘은 어떤 이야기를 나누고 싶나요?"
        
        elif message in ['3', '3️⃣', '일반인', '일반']:
            session_data['user_type'] = 'general'
            session_data['user_type_confirmed'] = True
            self.session_manager.update_session(session_data)
            response_text = "등록되었습니다! 직업, 일상생활 고민을 편하게 나눠주세요. 😊\n\n오늘은 어떤 이야기를 나누고 싶으신가요?"
        
        else:
            response_text = get_user_type_prompt()
        
        return self._create_response(response_text)
    
    def _handle_reset(self, user_id: str) -> dict:
        """세션 리셋을 처리합니다."""
        self.session_manager.reset_session(user_id)
        response_text = get_user_type_prompt()
        return self._create_response(response_text)
    
    def _handle_end(self, user_id: str, session_data: dict) -> dict:
        """세션 종료를 처리합니다."""
        if len(session_data.get('conversation_history', [])) > 0:
            self.session_manager.save_completed_session(session_data)
        
        response_text = "오늘 함께 이야기 나눠줘서 정말 고마워요. 언제든지 다시 이야기 나누고 싶으면 '다시 시작'이라고 말해주세요. 😊"
        return self._create_response(response_text)
    
    def _handle_coaching(self, user_id: str, message: str, session_data: dict) -> dict:
        """코칭 대화를 처리합니다."""
        try:
            # 대화 히스토리에 추가
            session_data['conversation_history'].append({
                "role": "user",
                "content": message
            })
            
            # 현재 단계 정보
            user_type = session_data.get('user_type', 'general')
            current_stage = int(session_data.get('current_stage', 0))
            stage_question_count = int(session_data.get('stage_question_count', 0))
            
            # 프롬프트 생성
            system_prompt = self.prompt_manager.get_stage_prompt(
                user_type,
                current_stage,
                stage_question_count
            )
            
            # API 호출
            coach_response = self.api_client.call_api(
                session_data['conversation_history'],
                system_prompt
            )
            
            # 응답 검증
            if not coach_response or "오류" in coach_response:
                coach_response = self._get_fallback_response(user_type)
            
            # 위기 상황 대응
            if session_data.get('crisis_detected') and stage_question_count % 2 == 0:
                coach_response += "\n\n💙 힘든 마음을 표현해줘서 고마워요. 담임선생님이나 상담선생님, 또는 청소년상담 1388에 연락해보세요."
            
            # 응답 저장
            session_data['conversation_history'].append({
                "role": "assistant",
                "content": coach_response
            })
            
            # 질문 카운트 증가
            session_data['stage_question_count'] = stage_question_count + 1
            
            # 단계 전환 체크
            if self._should_advance_stage(session_data, message):
                session_data = self._advance_stage(session_data, coach_response)
            
            # 세션 업데이트
            self.session_manager.update_session(session_data)
            
            return self._create_response(coach_response)
            
        except Exception as e:
            logger.error(f"Error in coaching: {str(e)}", exc_info=True)
            return self.error_response()
    
    def _should_advance_stage(self, session_data: dict, user_message: str) -> bool:
        """단계 전환 여부를 판단합니다."""
        stage_question_count = int(session_data.get('stage_question_count', 0))
        current_stage = int(session_data.get('current_stage', 0))
        
        user_type = session_data.get('user_type', 'general')
        coaching_stages = self.prompt_manager.get_coaching_stages(user_type)
        
        # 마지막 단계면 전환하지 않음
        if current_stage >= len(coaching_stages) - 1:
            return False
        
        # 단계별 제한
        stage_limits = {"min": 2, "max": 4}
        
        if stage_question_count >= stage_limits["max"]:
            return True
        
        if stage_question_count < stage_limits["min"]:
            return False
        
        # 충실한 답변 체크
        if len(user_message.strip()) > 50:
            return True
        
        return False
    
    def _advance_stage(self, session_data: dict, coach_response: str) -> dict:
        """다음 단계로 전환합니다."""
        current_stage = int(session_data.get('current_stage', 0))
        next_stage = current_stage + 1
        
        user_type = session_data.get('user_type', 'general')
        coaching_stages = self.prompt_manager.get_coaching_stages(user_type)
        
        if next_stage < len(coaching_stages):
            session_data['current_stage'] = next_stage
            session_data['stage_question_count'] = 0
            logger.info(f"Advanced to stage {next_stage}")
        else:
            # 완료
            self.session_manager.save_completed_session(session_data)
            logger.info("All stages completed")
        
        return session_data
    
    def _get_fallback_response(self, user_type: str) -> str:
        """폴백 응답을 반환합니다."""
        fallbacks = {
            "teacher": "죄송합니다. 다시 한번 말씀해주시겠어요?",
            "student": "미안해요. 다시 한번 말해줄래요?",
            "general": "죄송합니다. 다시 말씀해주시겠어요?"
        }
        return fallbacks.get(user_type, "다시 말씀해주시겠어요?")
    
    def _create_response(self, text: str) -> dict:
        """카카오톡 응답 형식을 생성합니다."""
        return {
            "version": "2.0",
            "template": {
                "outputs": [{
                    "simpleText": {
                        "text": text
                    }
                }]
            }
        }
    
    def error_response(self) -> dict:
        """에러 응답을 반환합니다."""
        return self._create_response("죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
```

## 4. 세션 관리자 (session_manager.py)

```python
# app/session_manager.py
import logging
import boto3
from datetime import datetime, timedelta
from botocore.config import Config
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

# AWS 설정
boto_config = Config(
    retries={'max_attempts': 3, 'mode': 'adaptive'},
    max_pool_connections=50
)
dynamodb = boto3.resource('dynamodb', config=boto_config)
sessions_table = dynamodb.Table('chatbot_sessions')
completed_sessions_table = dynamodb.Table('chatbot_completed_sessions')

SESSION_TIMEOUT_HOURS = 24

class SessionManager:
    def __init__(self):
        self.cache = {}
    
    def get_session(self, user_id: str) -> dict:
        """세션을 조회하거나 생성합니다."""
        try:
            response = sessions_table.get_item(Key={'user_id': user_id})
            session_data = response.get('Item', None)
            
            if session_data is None or self.is_session_expired(session_data):
                session_data = self.create_new_session(user_id)
                self.update_session(session_data)
            
            return session_data
            
        except Exception as e:
            logger.error(f"Error getting session: {str(e)}", exc_info=True)
            return self.create_new_session(user_id)
    
    def create_new_session(self, user_id: str) -> dict:
        """새 세션을 생성합니다."""
        return {
            'user_id': user_id,
            'user_type': None,
            'user_type_confirmed': False,
            'current_stage': 0,
            'stage_question_count': 0,
            'conversation_history': [],
            'session_start_time': datetime.utcnow().isoformat(),
            'last_active': datetime.utcnow().isoformat(),
            'crisis_detected': False
        }
    
    def update_session(self, session_data: dict) -> None:
        """세션을 업데이트합니다."""
        try:
            session_data['current_stage'] = int(session_data.get('current_stage', 0))
            session_data['stage_question_count'] = int(session_data.get('stage_question_count', 0))
            session_data['last_active'] = datetime.utcnow().isoformat()
            
            sessions_table.put_item(Item=session_data)
            logger.info(f"Session updated for user {session_data['user_id']}")
            
        except Exception as e:
            logger.error(f"Error updating session: {str(e)}", exc_info=True)
    
    def reset_session(self, user_id: str) -> dict:
        """세션을 리셋합니다."""
        current_session = self.get_session(user_id)
        if current_session and len(current_session.get('conversation_history', [])) > 0:
            self.save_completed_session(current_session)
        
        new_session = self.create_new_session(user_id)
        self.update_session(new_session)
        return new_session
    
    def save_completed_session(self, session_data: dict) -> None:
        """완료된 세션을 저장합니다."""
        try:
            completed_session = {
                'user_id': session_data['user_id'],
                'session_id': f"{session_data['user_id']}_{session_data['session_start_time']}",
                'session_start_time': session_data['session_start_time'],
                'session_end_time': datetime.utcnow().isoformat(),
                'user_type': session_data.get('user_type'),
                'conversation_history': session_data.get('conversation_history', []),
                'crisis_detected': session_data.get('crisis_detected', False)
            }
            
            completed_sessions_table.put_item(Item=completed_session)
            logger.info("Completed session saved")
            
        except Exception as e:
            logger.error(f"Error saving completed session: {str(e)}", exc_info=True)
    
    def is_session_expired(self, session_data: dict) -> bool:
        """세션 만료 여부를 확인합니다."""
        try:
            last_active = datetime.fromisoformat(session_data.get('last_active', ''))
            timeout = datetime.utcnow() - timedelta(hours=SESSION_TIMEOUT_HOURS)
            return last_active < timeout
        except:
            return True
```

## 5. API 클라이언트 (api_client.py)

```python
# app/api_client.py
import logging
import os
import json
import re
import urllib3
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# HTTP 클라이언트 설정
http = urllib3.PoolManager(
    maxsize=50,
    retries=Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"]
    ),
    timeout=25.0
)

class UpstageAPIClient:
    def __init__(self):
        self.api_url = "https://api.upstage.ai/v1/chat/completions"
        self.api_key = os.environ.get("UPSTAGE_API_KEY")
        
        if not self.api_key:
            logger.error("UPSTAGE_API_KEY not set")
    
    def call_api(self, messages: list, system_prompt: str = None, retry_count: int = 0, max_retries: int = 2) -> str:
        """Upstage API를 호출합니다."""
        if not self.api_key:
            return "API 키가 설정되지 않았습니다."
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 최근 대화만 포함
        recent_messages = messages[-6:] if len(messages) > 6 else messages
        
        formatted_messages = []
        
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        
        for m in recent_messages:
            if isinstance(m, dict) and "role" in m and "content" in m:
                formatted_messages.append({"role": m["role"], "content": m["content"]})
        
        payload = {
            "model": "solar-pro2",
            "messages": formatted_messages,
            "max_tokens": 150,
            "temperature": 0.8,
            "stream": False
        }
        
        try:
            encoded = json.dumps(payload).encode("utf-8")
            response = http.request(
                "POST",
                self.api_url,
                body=encoded,
                headers=headers,
                timeout=25.0
            )
            
            if response.status != 200:
                logger.error(f"API error: {response.status}")
                if retry_count < max_retries:
                    import time
                    time.sleep(1)
                    return self.call_api(messages, system_prompt, retry_count + 1, max_retries)
                return None
            
            result = json.loads(response.data.decode("utf-8"))
            
            if "choices" in result and len(result["choices"]) > 0:
                response_text = result["choices"][0]["message"]["content"]
                
                # 첫 번째 질문만 추출
                if '?' in response_text:
                    response_text = response_text.split('?')[0] + '?'
                
                # 정제
                response_text = re.sub(r'\([^)]*\)', '', response_text)
                response_text = re.sub(r'\*[^*]*\*', '', response_text)
                response_text = re.sub(r'[😊💪🎉💙⏰🚫⚠️]+', '', response_text)
                
                lines = response_text.strip().split('\n')
                if lines:
                    response_text = lines[0].strip()
                
                return response_text if response_text else None
            
            return None
            
        except urllib3.exceptions.TimeoutError:
            logger.error("API timeout")
            if retry_count < max_retries:
                return self.call_api(messages, system_prompt, retry_count + 1, max_retries)
            return None
            
        except Exception as e:
            logger.error(f"API error: {str(e)}", exc_info=True)
            return None
```

## 6. 프롬프트 관리자 (prompts.py)

```python
# app/prompts.py
# 기존 Lambda의 프롬프트 정의들을 그대로 옮겨옵니다

TEACHER_COACHING_STAGES = [
    "신뢰 형성", "교육 현장 탐색", "교육 목표 설정",
    "교수법 탐색", "실행 계획", "성찰 및 마무리"
]

STUDENT_COACHING_STAGES = [
    "신뢰 형성", "학교생활 탐색", "목표 설정",
    "해결방안 탐색", "실행 계획", "정리 및 마무리"
]

GENERAL_COACHING_STAGES = [
    "신뢰 형성", "현실 탐색", "목표 설정",
    "대안 탐색", "실행 계획", "정리 및 마무리"
]

# 각 유형별 상세 프롬프트...
# (이전에 제공한 프롬프트들을 여기에 추가)

class PromptManager:
    def get_coaching_stages(self, user_type: str) -> list:
        """유형별 코칭 단계를 반환합니다."""
        stages_map = {
            "teacher": TEACHER_COACHING_STAGES,
            "student": STUDENT_COACHING_STAGES,
            "general": GENERAL_COACHING_STAGES
        }
        return stages_map.get(user_type, GENERAL_COACHING_STAGES)
    
    def get_stage_prompt(self, user_type: str, stage_index: int, question_count: int) -> str:
        """단계별 프롬프트를 반환합니다."""
        stages = self.get_coaching_stages(user_type)
        stage_name = stages[stage_index]
        
        # 유형별 프롬프트 딕셔너리에서 가져오기
        # (구현 생략 - 이전 코드 참조)
        
        return f"현재 단계: {stage_name}\n질문 {question_count + 1}번째"
```

## 7. 유틸리티 (utils.py)

```python
# app/utils.py
import re

RESET_PATTERNS = [r'다시\s*시작', r'처음부터', r'새로\s*시작', r'리셋', r'reset']
END_PATTERNS = [r'종료', r'끝', r'그만', r'stop', r'exit']
CRISIS_PATTERNS = [r'자해', r'자살', r'죽고\s*싶', r'폭력', r'학대']

USER_TYPE_KEYWORDS = {
    "teacher": [r'교사', r'선생님', r'교직', r'수업'],
    "student": [r'학생', r'고등학교', r'중학교'],
    "general": [r'직장', r'회사', r'사회인']
}

def check_reset_keywords(message: str) -> bool:
    """리셋 키워드 확인"""
    message_lower = message.lower().strip()
    return any(re.search(pattern, message_lower) for pattern in RESET_PATTERNS)

def check_end_keywords(message: str) -> bool:
    """종료 키워드 확인"""
    message_lower = message.lower().strip()
    return any(re.search(pattern, message_lower) for pattern in END_PATTERNS)

def check_crisis_keywords(message: str) -> bool:
    """위기 키워드 확인"""
    message_lower = message.lower()
    return any(re.search(pattern, message_lower) for pattern in CRISIS_PATTERNS)

def detect_user_type(message: str) -> str:
    """사용자 유형 감지"""
    message_lower = message.lower()
    for user_type, keywords in USER_TYPE_KEYWORDS.items():
        for pattern in keywords:
            if re.search(pattern, message_lower):
                return user_type
    return None

def get_user_type_prompt() -> str:
    """사용자 유형 선택 프롬프트"""
    return """안녕하세요! 코칭 챗봇입니다. 😊

더 나은 상담을 위해 여러분에 대해 알고 싶어요.

1️⃣ 교사 (수업, 학급 운영 고민)
2️⃣ 학생 (학업, 진로, 친구 관계 고민)
3️⃣ 일반인 (직업, 일상생활 고민)

번호나 해당 단어를 입력해주세요!"""
```

## 8. Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 복사
COPY app/ ./app/

# 환경 변수
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.main

# 헬스 체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

EXPOSE 5000

# Gunicorn으로 실행
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.main:app"]
```

## 9. docker-compose.yml

```yaml
version: '3.8'

services:
  coaching-bot:
    build: .
    container_name: coaching-bot
    ports:
      - "5000:5000"
    environment:
      - UPSTAGE_API_KEY=${UPSTAGE_API_KEY}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - AWS_DEFAULT_REGION=ap-northeast-2
      - PORT=5000
      - DEBUG=False
    restart: unless-stopped
    volumes:
      - ./logs:/app/logs
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - coaching-network

  # Nginx (선택사항 - SSL 및 리버스 프록시)
  nginx:
    image: nginx:alpine
    container_name: coaching-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - coaching-bot
    restart: unless-stopped
    networks:
      - coaching-network

networks:
  coaching-network:
    driver: bridge
```

## 10. requirements.txt

```txt
Flask==3.0.0
gunicorn==21.2.0
boto3==1.34.0
urllib3==2.1.0
python-dotenv==1.0.0
```

## 11. Nginx 설정 (nginx.conf)

```nginx
events {
    worker_connections 1024;
}

http {
    upstream coaching-bot {
        server coaching-bot:5000;
    }

    server {
        listen 80;
        server_name your-domain.com;

        # HTTP to HTTPS redirect (SSL 설정 시)
        # return 301 https://$server_name$request_uri;

        location / {
            proxy_pass http://coaching-bot;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # 타임아웃 설정
            proxy_connect_timeout 75s;
            proxy_send_timeout 120s;
            proxy_read_timeout 120s;
        }

        location /health {
            proxy_pass http://coaching-bot/health;
            access_log off;
        }
    }

    # SSL 설정 (Let's Encrypt 사용 시)
    # server {
    #     listen 443 ssl http2;
    #     server_name your-domain.com;
    #
    #     ssl_certificate /etc/nginx/ssl/fullchain.pem;
    #     ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    #
    #     location / {
    #         proxy_pass http://coaching-bot;
    #         proxy_set_header Host $host;
    #         proxy_set_header X-Real-IP $remote_addr;
    #         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    #         proxy_set_header X-Forwarded-Proto $scheme;
    #     }
    # }
}
```

## 12. 환경 변수 (.env.example)

```bash
# .env.example
UPSTAGE_API_KEY=your_upstage_api_key_here
AWS_ACCESS_KEY_ID=your_aws_access_key_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_here
AWS_DEFAULT_REGION=ap-northeast-2
PORT=5000
DEBUG=False
```

## 13. 배포 스크립트 (deploy.sh)

```bash
#!/bin/bash

# deploy.sh
set -e

echo "🚀 Starting deployment..."

# 최신 코드 가져오기
echo "📥 Pulling latest code..."
git pull origin main

# 환경 변수 확인
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    exit 1
fi

# Docker 이미지 빌드
echo "🔨 Building Docker image..."
docker-compose build --no-cache

# 기존 컨테이너 중지
echo "🛑 Stopping old containers..."
docker-compose down

# 새 컨테이너 시작
echo "▶️  Starting new containers..."
docker-compose up -d

# 헬스 체크
echo "🏥 Checking health..."
sleep 5
for i in {1..10}; do
    if curl -f http://localhost:5000/health; then
        echo "✅ Deployment successful!"
        docker-compose logs --tail=50
        exit 0
    fi
    echo "Waiting for service to be ready... ($i/10)"
    sleep 3
done

echo "❌ Health check failed!"
docker-compose logs
exit 1
```

## 14. EC2 설정 가이드

### EC2 인스턴스 설정

```bash
# 1. EC2 인스턴스 접속
ssh -i your-key.pem ubuntu@your-ec2-ip

# 2. 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 3. Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# 4. Docker Compose 설치
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 5. 프로젝트 클론
git clone your-repo-url coaching-bot
cd coaching-bot

# 6. 환경 변수 설정
cp .env.example .env
nano .env  # 실제 값 입력

# 7. 배포
chmod +x deploy.sh
./deploy.sh
```

### 보안 그룹 설정

```
Inbound Rules:
- Type: HTTP, Port: 80, Source: 0.0.0.0/0
- Type: HTTPS, Port: 443, Source: 0.0.0.0/0
- Type: SSH, Port: 22, Source: Your IP
```

### 카카오톡 웹훅 설정

```
웹훅 URL: http://your-ec2-ip/webhook
또는
웹훅 URL: https://your-domain.com/webhook (SSL 설정 시)
```

## 15. 모니터링 및 로깅

```bash
# 로그 확인
docker-compose logs -f

# 특정 서비스 로그
docker-compose logs -f coaching-bot

# 컨테이너 상태 확인
docker-compose ps

# 리소스 사용량
docker stats

# 헬스 체크
curl http://localhost:5000/health

# 통계 확인
curl http://localhost:5000/stats
```

## 16. 자동 재시작 설정

```bash
# Systemd 서비스 생성
sudo nano /etc/systemd/system/coaching-bot.service
```

```ini
[Unit]
Description=Coaching Bot Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/coaching-bot
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
# 서비스 활성화
sudo systemctl enable coaching-bot
sudo systemctl start coaching-bot
sudo systemctl status coaching-bot
```
