"""
Coaching service - Main business logic
"""
import logging
from datetime import datetime
from .session_manager import SessionManager, SESSION_TIME_LIMIT_MINUTES, get_previous_context
from .api_client import UpstageAPIClient
from .prompts import COACHING_STAGES, STAGE_PROMPTS, STAGE_LIMITS, TRANSITION_MESSAGES
from .utils import (
    check_reset_keywords,
    check_end_keywords,
    check_continue_keywords,
    check_new_session_keywords,
    check_crisis_keywords,
    get_conversation_summary
)

logger = logging.getLogger(__name__)


class CoachingService:
    """코칭 서비스 메인 클래스"""

    def __init__(self):
        self.session_manager = SessionManager()
        self.api_client = UpstageAPIClient()

    def process_message(self, data: dict) -> dict:
        """
        KakaoTalk 메시지를 처리하고 응답을 생성합니다.

        Args:
            data: KakaoTalk webhook payload

        Returns:
            KakaoTalk response format dictionary
        """
        try:
            user_request = data.get('userRequest', {})
            if not isinstance(user_request, dict):
                logger.error("userRequest가 dict가 아님")
                return self.error_response()

            user_id = user_request.get('user', {}).get('id', 'unknown')
            user_message = user_request.get('utterance', '')

            logger.info(f"Processing message from user {user_id}: {user_message}")

            session_data = self.session_manager.get_session(user_id)

            # 세션이 완료된 경우 처리
            if session_data.get('session_completed', False):
                return self._handle_completed_session(session_data, user_id, user_message)

            # 재개 확인이 필요한 경우
            if self.session_manager.needs_resume_check(session_data) and not session_data.get('awaiting_resume_response', False):
                return self._handle_resume_check(session_data, user_message)

            # 재개 응답 대기 중인 경우
            if session_data.get('awaiting_resume_response', False):
                return self._handle_resume_response(session_data, user_id, user_message)

            # 일반적인 리셋/종료 키워드 체크
            if check_reset_keywords(user_message):
                session_data = self.session_manager.reset_session(user_id)
                user_message = "안녕하세요, 코칭을 시작하고 싶습니다."
                logger.info("Session reset triggered by user")

            elif check_end_keywords(user_message):
                return self._handle_end_session(session_data)

            # 위기 키워드 체크
            if check_crisis_keywords(user_message):
                session_data['crisis_detected'] = True
                session_data['crisis_timestamp'] = datetime.utcnow().isoformat()
                logger.warning(f"Crisis keywords detected for user {user_id}")

            # 코칭 진행
            return self._handle_coaching(session_data, user_message, user_id)

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            return self.error_response()

    def _handle_resume_check(self, session_data: dict, user_message: str) -> dict:
        """세션 재개 확인을 처리합니다."""
        try:
            # AI를 사용하여 재개 메시지 생성
            coach_response = self._generate_resume_message(session_data)
        except Exception as e:
            logger.error(f"Error generating resume message: {str(e)}", exc_info=True)
            # Fallback 메시지
            coach_response = "안녕하세요! 다시 만나서 반갑습니다. 😊\n\n이어서 이전 대화를 계속 진행하시겠어요? 아니면 새로운 주제로 시작하시겠어요?"

        # 재개 응답 대기 상태로 설정
        session_data['awaiting_resume_response'] = True
        self.session_manager.update_session(session_data)

        return self._create_response(coach_response)

    def _generate_resume_message(self, session_data: dict) -> str:
        """AI를 사용하여 세션 재개 메시지를 생성합니다."""
        conversation_history = session_data.get('conversation_history', [])
        current_stage = int(session_data.get('current_stage', 0))
        stage_name = COACHING_STAGES[current_stage]
        crisis_detected = session_data.get('crisis_detected', False)

        # 대화 이력이 너무 짧으면 간단한 메시지
        if len(conversation_history) < 4:
            return "안녕하세요! 다시 만나서 반갑습니다. 😊\n\n이어서 이전 대화를 계속 진행하시겠어요? 아니면 새로운 주제로 시작하시겠어요?"

        # 최근 대화 이력 추출 (마지막 8-10개 메시지)
        recent_history = conversation_history[-10:]

        # AI 프롬프트 생성
        system_prompt = f"""당신은 청소년 코칭봇입니다. 사용자와의 대화가 1시간 이상 중단되었다가 재개됩니다.

**현재 상황:**
- 코칭 단계: {stage_name} ({current_stage + 1}/{len(COACHING_STAGES)})
- 위기 상황 감지: {'예' if crisis_detected else '아니오'}

**요청사항:**
아래 대화 내역을 분석하여 다음을 포함한 따뜻하고 개인화된 재개 메시지를 작성하세요:

1. 반가운 인사 (이모지 포함)
2. 지난 대화의 핵심 주제와 감정 상태를 자연스럽게 요약
   - 단순히 마지막 문장을 반복하지 말고, 전체 맥락을 이해한 의미 있는 요약
   - 사용자가 이야기했던 어려움, 감정, 고민의 본질을 담아내기
3. 현재 코칭 단계에서 무엇을 다루고 있었는지
4. "이어서 계속 진행하시겠어요? 아니면 새로운 주제로 시작하시겠어요?" 질문

**중요:**
- 진심으로 반기는 느낌을 전달하세요
- 사용자의 용기와 노력을 인정하고 격려하세요
- 자연스럽고 따뜻한 어조를 유지하세요
- 마지막 문장을 그대로 복사하지 말고, 전체 대화의 본질을 파악하세요
{"- 위기 상황이므로 더욱 세심하고 조심스럽게 접근하세요" if crisis_detected else ""}

**출력 형식:**
재개 메시지만 출력하세요. 다른 설명이나 주석은 포함하지 마세요.
"""

        # API 호출
        try:
            coach_response = self.api_client.call_api(
                recent_history,
                system_prompt=system_prompt
            )

            if not coach_response:
                # API가 빈 응답을 반환한 경우 fallback
                return "안녕하세요! 다시 만나서 반갑습니다. 😊\n\n이어서 이전 대화를 계속 진행하시겠어요? 아니면 새로운 주제로 시작하시겠어요?"

            return coach_response

        except Exception as e:
            logger.error(f"Error calling AI API for resume message: {str(e)}")
            raise

    def _handle_resume_response(self, session_data: dict, user_id: str, user_message: str) -> dict:
        """재개 응답을 처리합니다."""
        session_data['awaiting_resume_response'] = False

        if check_new_session_keywords(user_message) or check_reset_keywords(user_message):
            # 새 세션 시작
            session_data = self.session_manager.reset_session(user_id)
            user_message = "안녕하세요, 코칭을 시작하고 싶습니다."
            logger.info("New session started after resume check")
        else:
            # 기존 세션 계속
            logger.info("Continuing previous session")

        return self._handle_coaching(session_data, user_message, user_id)

    def _handle_end_session(self, session_data: dict) -> dict:
        """세션 종료를 처리합니다."""
        # 종료 시 세션 저장
        if len(session_data.get('conversation_history', [])) > 0:
            self.session_manager.save_completed_session(session_data)

        # 종료 응답 생성
        coach_response = "오늘 함께 이야기 나눠줘서 정말 고마워요. 도움이 필요할 때 용기내서 손을 내밀 수 있다는 걸 기억해주세요. 언제든지 다시 이야기 나누고 싶으면 '다시 시작'이라고 말해주세요. 응원할게요! 💪😊"

        return self._create_response(coach_response)

    def _handle_completed_session(self, session_data: dict, user_id: str, user_message: str) -> dict:
        """완료된 세션 이후 메시지를 처리합니다."""
        # '다시 시작' 키워드 체크
        restart_keywords = ['다시 시작', '다시시작', '새로 시작', '새로시작', '처음부터', '리셋', '재시작']
        if any(keyword in user_message for keyword in restart_keywords):
            # 새 세션 시작
            session_data = self.session_manager.reset_session(user_id)
            user_message = "안녕하세요, 코칭을 시작하고 싶습니다."
            logger.info("New session started after completion")
            return self._handle_coaching(session_data, user_message, user_id)
        else:
            # 재시작 안내 메시지
            coach_response = "오늘 대화는 마무리되었어요. 😊\n\n새로운 대화를 시작하고 싶으면 '다시 시작'이라고 말해주세요!"
            return self._create_response(coach_response)

    def _handle_session_completion(self, session_data: dict, user_message: str) -> dict:
        """세션 완료 시 마지막 답변에 공감하고 종료합니다."""
        try:
            # AI로 공감 메시지 생성
            empathy_prompt = """당신은 청소년 코칭봇입니다. 사용자가 마지막 질문에 답변했고, 이제 세션을 마무리해야 합니다.

**요청사항:**
사용자의 마지막 답변에 대해 짧고 따뜻한 공감 메시지를 작성하세요.

**출력 조건:**
1. 2-3문장 이내로 간결하게
2. 사용자의 답변을 인정하고 격려
3. 이모지 1-2개 포함
4. 자연스럽고 따뜻한 어조

**출력 형식:**
공감 메시지만 출력하세요. 다른 질문이나 설명은 포함하지 마세요.

예시:
"힘들 때 도움을 요청하는 것이 중요하다는 걸 깨달았다니 정말 멋져요! 그 용기가 앞으로도 큰 힘이 될 거예요. 💪"
"""

            # 최근 대화 이력 (마지막 2-4개 메시지면 충분)
            recent_history = session_data['conversation_history'][-4:]

            empathy_message = self.api_client.call_api(
                recent_history,
                system_prompt=empathy_prompt
            )

            if not empathy_message:
                # Fallback 공감 메시지
                empathy_message = "소중한 이야기를 나눠줘서 정말 고마워요. 오늘 함께한 시간이 의미 있었기를 바라요. 💙"

            # 종료 안내 메시지
            completion_message = "\n\n🎉 오늘 정말 의미있는 대화를 나눴어요! 도움이 필요할 때 용기내서 말할 수 있는 여러분이 정말 멋져요. 새로운 대화를 시작하고 싶으면 '다시 시작'이라고 말해주세요."

            # 전체 응답 구성
            coach_response = empathy_message + completion_message

            # 코치 응답을 대화 이력에 추가
            session_data['conversation_history'].append({"role": "assistant", "content": coach_response})

            # 세션 완료 플래그 설정
            session_data['session_completed'] = True

            # 완료된 세션 저장
            self.session_manager.save_completed_session(session_data)

            # 세션 업데이트
            self.session_manager.update_session(session_data)

            logger.info("Session completed successfully with empathy message")

            return self._create_response(coach_response)

        except Exception as e:
            logger.error(f"Error in session completion: {str(e)}", exc_info=True)
            # Fallback 종료 메시지
            coach_response = "🎉 오늘 정말 의미있는 대화를 나눴어요! 도움이 필요할 때 용기내서 말할 수 있는 여러분이 정말 멋져요. 새로운 대화를 시작하고 싶으면 '다시 시작'이라고 말해주세요."
            session_data['session_completed'] = True
            self.session_manager.save_completed_session(session_data)
            self.session_manager.update_session(session_data)
            return self._create_response(coach_response)

    def _handle_coaching(self, session_data: dict, user_message: str, user_id: str) -> dict:
        """코칭 대화를 처리합니다."""
        try:
            # 세션에 사용자 메시지 추가
            session_data['conversation_history'].append({"role": "user", "content": user_message})

            # 사용자 응답 대기 플래그 해제 (사용자가 답변했음)
            session_data['awaiting_user_response'] = False

            # 현재 단계 및 질문 카운트 가져오기
            current_stage = int(session_data.get('current_stage', 0))
            stage_question_count = int(session_data.get('stage_question_count', 0))

            # 단계별 시스템 프롬프트 설정
            stage_name = COACHING_STAGES[current_stage]

            # 질문 카운트 증가 (사용자가 N번째 질문에 답변하고 있음)
            stage_question_count += 1
            session_data['stage_question_count'] = stage_question_count

            # 세션 종료 조건 체크 (AI 호출 전에 확인)
            is_last_stage = current_stage >= len(COACHING_STAGES) - 1
            limits = STAGE_LIMITS.get(stage_name, {"min": 2, "max": 3})
            # 마지막 단계에서 최대 질문 수를 초과한 답변이면 종료
            is_over_max_questions = stage_question_count > limits["max"]

            if is_last_stage and is_over_max_questions:
                # 마지막 답변에 대한 공감 후 세션 종료
                return self._handle_session_completion(session_data, user_message)

            # 첫 단계이고 첫 질문인 경우 이전 세션 컨텍스트 추가
            previous_context = ""
            if current_stage == 0 and stage_question_count == 1:
                previous_context = get_previous_context(user_id, self.session_manager)

            # 시스템 프롬프트 생성
            system_prompt = self._generate_system_prompt(
                stage_name,
                current_stage,
                stage_question_count,
                previous_context,
                session_data
            )

            # Upstage Solar Pro2 API 호출
            coach_response = self.api_client.call_api(
                session_data['conversation_history'],
                system_prompt=system_prompt
            )

            if not coach_response:
                # 단계별 기본 질문으로 fallback
                fallback_questions = {
                    0: "오늘 하루는 어땠나요?",
                    1: "그 상황에서 어떤 부분이 가장 힘들었나요?",
                    2: "이 문제를 해결한다면 어떤 변화가 있을까요?",
                    3: "이 문제를 해결하기 위해 어떤 방법을 생각해보셨나요?",
                    4: "첫 번째 실행 단계로 무엇을 해보시겠어요?",
                    5: "오늘 대화를 통해 어떤 점이 도움이 되었나요?"
                }
                coach_response = fallback_questions.get(current_stage, "조금 더 이야기해주실 수 있나요?")

            # 위기 상황일 경우 도움 자원 안내 추가
            if session_data.get('crisis_detected', False) and stage_question_count % 2 == 0:
                coach_response += "\n\n💙 힘든 마음을 표현해줘서 정말 고마워요. 혼자가 아니에요. 담임선생님이나 상담선생님, 또는 청소년상담 1388에 연락해보는 것도 좋은 방법이에요."

            # 시간 제한 안내
            session_duration = self.session_manager.get_session_duration(session_data)
            if session_duration >= SESSION_TIME_LIMIT_MINUTES - 2 and session_duration < SESSION_TIME_LIMIT_MINUTES:
                coach_response += "\n\n⏰ 곧 대화 시간이 마무리됩니다. 오늘 나눈 이야기 중에서 가장 중요한 부분을 생각해보세요."

            # 코치 응답 저장
            session_data['conversation_history'].append({"role": "assistant", "content": coach_response})

            # 주제 선택 단계에서 사용자의 답변을 chosen_topic으로 저장
            if current_stage == 0 and not session_data.get('chosen_topic'):
                # 사용자가 처음으로 답변한 내용을 주제로 저장
                session_data['chosen_topic'] = user_message[:100]  # 최대 100자까지 저장
                logger.info(f"Chosen topic stored: {session_data['chosen_topic']}")

            # 단계 전환 로직
            if self._should_advance_stage(session_data, user_message):
                coach_response = self._advance_stage(session_data, current_stage, coach_response)

            # 사용자 응답 대기 플래그 설정 (봇이 질문을 했고 답변을 기다림)
            session_data['awaiting_user_response'] = True

            # 세션 업데이트
            self.session_manager.update_session(session_data)

            # 디버깅 정보 로깅
            logger.info(f"Current stage: {current_stage} ({COACHING_STAGES[current_stage]})")
            logger.info(f"Question count: {stage_question_count}")
            logger.info(f"Session duration: {session_duration} minutes")
            logger.info(f"Response: {coach_response[:100]}...")

            return self._create_response(coach_response)

        except Exception as e:
            logger.error(f"Error in coaching: {str(e)}", exc_info=True)
            return self.error_response()

    def _generate_system_prompt(self, stage_name: str, current_stage: int,
                                 stage_question_count: int, previous_context: str,
                                 session_data: dict) -> str:
        """시스템 프롬프트를 생성합니다."""
        system_prompt = f"""
{STAGE_PROMPTS[stage_name].format(previous_context=previous_context)}

현재 단계: {stage_name} ({current_stage + 1}/{len(COACHING_STAGES)})
질문 횟수: {stage_question_count + 1}번째

중요한 코칭 원칙:
1. 사용자의 답변을 깊이 파고들지 말고, 단계의 목표에 맞는 새로운 질문으로 전환하세요
2. 같은 주제를 반복해서 묻지 마세요
3. 사용자가 충분히 답했다면 다음 관점의 질문으로 넘어가세요
4. 단계별 목표를 달성하기 위한 핵심 질문을 하세요
5. 사용자의 답변이 짧아도 계속 파고들지 말고 다른 각도의 질문을 하세요

⚠️ 출력 규칙 (반드시 준수):
1. 딱 한 개의 질문만 출력
2. 절대 두 번째 질문 금지
3. 괄호 안에 아무것도 쓰지 마세요
4. 마무리 단계가 아니면 마무리 멘트 금지
5. 현재 단계에 맞는 질문만 하세요

이전 질문과 중복되지 않도록 주의하세요.
"""

        # 선택한 주제 컨텍스트 추가
        chosen_topic = session_data.get('chosen_topic')
        if chosen_topic and current_stage > 0:  # 첫 단계(주제 선택) 이후에만 추가
            system_prompt += f"\n\n사용자가 선택한 주제: {chosen_topic}\n이 주제와 관련하여 질문하고 대화를 이어가세요."

        # 시간 체크 추가
        session_duration = self.session_manager.get_session_duration(session_data)
        if session_duration >= SESSION_TIME_LIMIT_MINUTES:
            system_prompt += f"\n\n세션이 {SESSION_TIME_LIMIT_MINUTES}분을 넘어갔습니다. 대화를 마무리하는 방향으로 진행해주세요."

        return system_prompt

    def _should_advance_stage(self, session_data: dict, user_message: str) -> bool:
        """단계를 전환해야 하는지 판단합니다."""
        stage_question_count = int(session_data.get('stage_question_count', 0))
        current_stage = int(session_data.get('current_stage', 0))
        conversation_history = session_data.get('conversation_history', [])

        # 마지막 단계인 경우 절대 전환하지 않음
        if current_stage >= len(COACHING_STAGES) - 1:
            return False

        # 단계별 질문 수 기준
        stage_name = COACHING_STAGES[current_stage]
        limits = STAGE_LIMITS.get(stage_name, {"min": 2, "max": 3})

        # 최대 질문 수를 넘으면 무조건 전환
        if stage_question_count >= limits["max"]:
            logger.info(f"Stage {stage_name}: max questions ({limits['max']}) reached, advancing")
            return True

        # 최소 질문 수를 충족하지 못하면 계속
        if stage_question_count < limits["min"]:
            return False

        # 최소 질문 수 충족 후, 학생 답변의 충실도 체크
        user_message_length = len(user_message.strip())

        # 짧은 답변(20자 미만)이 연속으로 나오면 단계 전환
        if user_message_length < 20:
            recent_user_messages = [msg['content'] for msg in conversation_history[-4:] if msg['role'] == 'user']
            short_answers = sum(1 for msg in recent_user_messages if len(msg) < 20)
            if short_answers >= 2:
                logger.info(f"Stage {stage_name}: short answers detected, advancing")
                return True

        # 충실한 답변이 나왔으면 전환
        if user_message_length > 50:
            logger.info(f"Stage {stage_name}: detailed answer received, advancing")
            return True

        return False

    def _advance_stage(self, session_data: dict, current_stage: int, coach_response: str) -> str:
        """다음 단계로 전환합니다."""
        next_stage = current_stage + 1

        # 다음 단계가 존재하지 않으면 그대로 반환 (안전장치)
        if next_stage >= len(COACHING_STAGES):
            logger.warning(f"Cannot advance beyond last stage {current_stage}")
            return coach_response

        # 다음 단계로 전환
        session_data['current_stage'] = next_stage
        session_data['stage_question_count'] = 0

        # 단계 전환 시 부드러운 연결 메시지 추가
        next_stage_name = COACHING_STAGES[next_stage]
        if next_stage_name in TRANSITION_MESSAGES:
            coach_response = TRANSITION_MESSAGES[next_stage_name] + "\n\n" + coach_response

        logger.info(f"Stage advanced from {current_stage} to {next_stage}")

        return coach_response

    def _create_response(self, text: str) -> dict:
        """카카오톡 응답 형식을 생성합니다."""
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": text
                        }
                    }
                ]
            }
        }

    def error_response(self) -> dict:
        """에러 응답을 반환합니다."""
        return self._create_response("죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
