"""
Session management for the coaching chatbot
"""
import logging
import boto3
from datetime import datetime, timedelta
from botocore.config import Config
from boto3.dynamodb.conditions import Key
from .prompts import COACHING_STAGES

logger = logging.getLogger(__name__)

# AWS 설정
boto_config = Config(
    retries={'max_attempts': 3, 'mode': 'adaptive'},
    max_pool_connections=50
)
dynamodb = boto3.resource('dynamodb', config=boto_config)
sessions_table = dynamodb.Table('chatbot_sessions')
completed_sessions_table = dynamodb.Table('chatbot_completed_sessions')

# 세션 만료 시간 설정
SESSION_TIMEOUT_HOURS = 24
RESUME_CHECK_HOURS = 1  # 1시간 이후 재개 확인
SESSION_TIME_LIMIT_MINUTES = 18  # 수업 시간 고려한 제한 시간


class SessionManager:
    """사용자 세션을 관리하는 클래스"""

    def __init__(self):
        self.cache = {}

    def is_session_expired(self, session_data: dict) -> bool:
        """세션이 만료되었는지 확인합니다."""
        try:
            last_active = datetime.fromisoformat(session_data.get('last_active', ''))
            timeout = datetime.utcnow() - timedelta(hours=SESSION_TIMEOUT_HOURS)
            return last_active < timeout
        except (ValueError, TypeError):
            return True

    def needs_resume_check(self, session_data: dict) -> bool:
        """세션 재개 확인이 필요한지 확인합니다."""
        try:
            last_active = datetime.fromisoformat(session_data.get('last_active', ''))
            resume_threshold = datetime.utcnow() - timedelta(hours=RESUME_CHECK_HOURS)
            return last_active < resume_threshold
        except (ValueError, TypeError):
            return False

    def get_session_duration(self, session_data: dict) -> int:
        """세션 진행 시간을 분 단위로 반환합니다."""
        try:
            start_time = datetime.fromisoformat(session_data.get('session_start_time', ''))
            duration = (datetime.utcnow() - start_time).total_seconds() / 60
            return int(duration)
        except:
            return 0

    def get_session(self, user_id: str) -> dict:
        """DynamoDB에서 세션을 조회하거나 기본 세션을 생성합니다."""
        try:
            session = sessions_table.get_item(Key={'user_id': user_id})
            session_data = session.get('Item', None)

            # 세션이 없거나 만료된 경우 새 세션 생성
            if session_data is None or self.is_session_expired(session_data):
                session_data = self.create_new_session(user_id)
                self.update_session(session_data)

            return session_data
        except Exception as e:
            logger.exception("Error getting session", exc_info=e)
            return self.create_new_session(user_id)

    def get_previous_sessions(self, user_id: str, limit: int = 5) -> list:
        """사용자의 이전 완료된 세션들을 조회합니다."""
        try:
            response = completed_sessions_table.query(
                KeyConditionExpression=Key('user_id').eq(user_id),
                ScanIndexForward=False,  # 최신순으로 정렬
                Limit=limit
            )
            return response.get('Items', [])
        except Exception as e:
            logger.error(f"Error getting previous sessions: {str(e)}")
            return []

    def save_completed_session(self, session_data: dict) -> None:
        """완료된 세션을 저장합니다."""
        try:
            # 세션 요약 정보 추출
            summary = self.extract_session_summary(session_data)

            completed_session = {
                'user_id': session_data['user_id'],
                'session_id': f"{session_data['user_id']}_{session_data['session_start_time']}",
                'session_start_time': session_data['session_start_time'],
                'session_end_time': datetime.utcnow().isoformat(),
                'summary': summary,
                'conversation_history': session_data.get('conversation_history', []),
                'crisis_detected': session_data.get('crisis_detected', False),
                'session_completed': True
            }

            completed_sessions_table.put_item(Item=completed_session)
            logger.info("Completed session saved successfully")
        except Exception as e:
            logger.error(f"Error saving completed session: {str(e)}")

    def extract_session_summary(self, session_data: dict) -> dict:
        """도움요청 주제에 맞춘 세션 요약을 추출합니다."""
        conversation_history = session_data.get('conversation_history', [])

        summary = {
            'difficulties': [],      # 어려움
            'help_needs': [],       # 도움 필요 영역
            'barriers': [],         # 도움요청 장벽
            'helpers': [],          # 도움줄 수 있는 사람
            'action_plans': [],     # 실천 계획
            'insights': [],         # 통찰
            'last_stage': COACHING_STAGES[int(session_data.get('current_stage', 0))]
        }

        # 대화 내용에서 주요 정보 추출
        for msg in conversation_history:
            if msg.get('role') == 'user':
                content = msg.get('content', '').lower()

                # 어려움 관련 키워드
                if any(keyword in content for keyword in ['힘들', '어려', '못하', '안되', '걱정']):
                    summary['difficulties'].append(content[:50])

                # 도움 필요 관련
                if any(keyword in content for keyword in ['도움', '필요', '혼자', '같이']):
                    summary['help_needs'].append(content[:50])

                # 도움요청 장벽
                if any(keyword in content for keyword in ['부끄러', '민폐', '싫어', '거절', '무서']):
                    summary['barriers'].append(content[:50])

                # 도움줄 수 있는 사람
                if any(keyword in content for keyword in ['선생님', '부모님', '친구', '상담', '언니', '오빠', '누나', '형']):
                    summary['helpers'].append(content[:50])

                # 실천 계획
                if any(keyword in content for keyword in ['할게', '하겠', '해볼게', '시도']):
                    summary['action_plans'].append(content[:50])

        # 각 카테고리별로 최대 3개만 저장
        for key in summary:
            if isinstance(summary[key], list):
                summary[key] = summary[key][-3:]

        return summary

    def create_new_session(self, user_id: str) -> dict:
        """새 세션을 생성합니다."""
        return {
            'user_id': user_id,
            'current_stage': 0,
            'stage_question_count': 0,
            'conversation_history': [],
            'session_start_time': datetime.utcnow().isoformat(),
            'last_active': datetime.utcnow().isoformat(),
            'awaiting_resume_response': False,
            'awaiting_user_response': False,
            'crisis_detected': False,
            'session_completed': False,
            'chosen_topic': None,
            'topic_description': ''
        }

    def reset_session(self, user_id: str) -> dict:
        """세션을 리셋하고 새 세션을 생성합니다."""
        # 현재 세션을 완료된 세션으로 저장
        current_session = self.get_session(user_id)
        if current_session and len(current_session.get('conversation_history', [])) > 0:
            self.save_completed_session(current_session)

        session_data = self.create_new_session(user_id)
        self.update_session(session_data)
        return session_data

    def update_session(self, session_data: dict) -> None:
        """DynamoDB에 세션 정보를 저장합니다."""
        try:
            # current_stage와 stage_question_count를 int로 보장
            session_data['current_stage'] = int(session_data.get('current_stage', 0))
            session_data['stage_question_count'] = int(session_data.get('stage_question_count', 0))
            session_data['last_active'] = datetime.utcnow().isoformat()

            sessions_table.put_item(Item=session_data)
            logger.info("Session updated successfully")
        except Exception as e:
            logger.exception("Error updating session", exc_info=e)


def get_previous_context(user_id: str, session_manager: SessionManager) -> str:
    """이전 세션 정보를 기반으로 컨텍스트를 생성합니다."""
    previous_sessions = session_manager.get_previous_sessions(user_id, limit=3)

    if not previous_sessions:
        return ""

    context_parts = []

    # 가장 최근 세션 정보
    if previous_sessions:
        latest_session = previous_sessions[0]
        summary = latest_session.get('summary', {})

        if summary.get('difficulties'):
            context_parts.append(f"이전에 이야기했던 어려움: {', '.join(summary['difficulties'])}")

        if summary.get('action_plans'):
            context_parts.append(f"지난번에 계획했던 것: {', '.join(summary['action_plans'])}")

        if summary.get('helpers'):
            context_parts.append(f"도움받을 수 있다고 했던 사람: {', '.join(summary['helpers'])}")

    if context_parts:
        return f"\n[이전 대화 참고]\n" + "\n".join(context_parts) + "\n자연스럽게 이전 대화 내용을 언급하며 시작하세요.\n"

    return ""
