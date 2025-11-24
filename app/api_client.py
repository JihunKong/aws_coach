"""
API client for Upstage Solar Pro2
"""
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
        total=1,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"]
    ),
    timeout=urllib3.Timeout(connect=3.0, read=8.0)
)


class UpstageAPIClient:
    """Upstage Solar Pro2 API 클라이언트"""

    def __init__(self):
        self.api_url = "https://api.upstage.ai/v1/chat/completions"
        self.api_key = os.environ.get("UPSTAGE_API_KEY")

        if not self.api_key:
            logger.error("UPSTAGE_API_KEY environment variable not set")

    def call_api(self, messages, system_prompt=None):
        """Upstage Solar Pro2 API를 호출합니다."""
        if not self.api_key:
            logger.error("UPSTAGE_API_KEY not configured")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 최근 대화만 포함 (컨텍스트 제한)
        recent_messages = messages[-6:] if len(messages) > 6 else messages

        # 메시지 형식 변환
        formatted_messages = []

        # 시스템 프롬프트 추가 (메타 표현 금지 강화)
        if system_prompt:
            enhanced_prompt = f"""
{system_prompt}

🚫 절대 금지사항:
1. 한 번에 반드시 딱 하나의 질문만 출력하고 즉시 종료
2. 학생의 이전 답변을 다시 묻거나 구체화 요청 금지
3. "(학생의 답변을 기다립니다)" 같은 괄호 표현 절대 금지
4. 이모지는 사용하지 마세요
5. 단계의 목표에 맞는 새로운 관점의 질문을 하세요

출력 예시:
좋은 예: "요즘 가장 힘든 일은 무엇인가요?"
나쁜 예: "그 부분에 대해 좀 더 자세히 말해주실래요?"
나쁜 예: "아까 말씀하신 그 문제가 구체적으로 어떤 건가요?"

한 개의 새로운 질문만 출력하고 종료하세요."""
            formatted_messages.append({"role": "system", "content": enhanced_prompt})

        # 대화 히스토리 추가 (최근 것만)
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
                timeout=urllib3.Timeout(connect=3.0, read=8.0)
            )

            if response.status != 200:
                logger.error(f"Upstage API returned status {response.status}: {response.data.decode('utf-8')}")
                return None

            result = json.loads(response.data.decode("utf-8"))

            # 응답 추출 및 정제
            if "choices" in result and len(result["choices"]) > 0:
                response_text = result["choices"][0]["message"]["content"]

                # 첫 번째 질문만 추출 (물음표 기준)
                if '?' in response_text:
                    # 첫 번째 물음표까지만 자르기
                    first_question = response_text.split('?')[0] + '?'
                    response_text = first_question

                # 메타 표현 제거
                response_text = re.sub(r'\([^)]*\)', '', response_text)  # 모든 괄호 내용 제거
                response_text = re.sub(r'\*[^*]*\*', '', response_text)  # * 표현 제거

                # 이모지 제거
                response_text = re.sub(r'[😊💪🎉💙⏰🚫⚠️]+', '', response_text)

                # 여러 줄인 경우 첫 줄만
                lines = response_text.strip().split('\n')
                if lines:
                    response_text = lines[0].strip()

                return response_text
            else:
                logger.error(f"Unexpected response format from Upstage API: {result}")
                return None

        except Exception as e:
            logger.error(f"Error calling Upstage Solar API: {str(e)}")
            return None
