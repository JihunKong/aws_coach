import json
import boto3
import logging
from datetime import datetime, timedelta
import os
import urllib3
import csv
import io
import random
import asyncio
import aioboto3
from functools import lru_cache
from botocore.config import Config

# 로깅 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS 설정 최적화
boto_config = Config(
    retries = dict(
        max_attempts = 3,
        mode = 'adaptive'
    ),
    max_pool_connections = 50
)

# 클라이언트 설정
http = urllib3.PoolManager(maxsize=50, retries=urllib3.Retry(3), timeout=5.0)
s3 = boto3.client('s3', config=boto_config)
dynamodb = boto3.resource('dynamodb', config=boto_config)
sessions_table = dynamodb.Table('chatbot_sessions')

# 캐시 설정
CACHE_TTL = 3600  # 1시간

@lru_cache(maxsize=100)
def get_openai_headers():
    """OpenAI API 헤더 캐싱"""
    return {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.environ.get("OPENAI_API_KEY")}'
    }

@lru_cache(maxsize=1, ttl=CACHE_TTL)
async def load_coaching_questions():
    """코칭 질문 데이터 캐싱된 로드"""
    try:
        async with aioboto3.client('s3', config=boto_config) as s3_client:
            response = await s3_client.get_object(
                Bucket='coaching-chatbot-data',
                Key='coach.csv'
            )
            csv_content = await response['Body'].read()
            csv_content = csv_content.decode('utf-8')
            questions = {}
            reader = csv.DictReader(io.StringIO(csv_content))
            
            for row in reader:
                stage = row['step'].split('(')[0] if '(' in row['step'] else row['step']
                if stage not in questions:
                    questions[stage] = {
                        'primary_questions': [],
                        'follow_up_questions': [],
                        'transitions': []
                    }
                
                for key, value in row.items():
                    if key.startswith('Question') and value:
                        if 'follow up' in key.lower():
                            questions[stage]['follow_up_questions'].append(value)
                        else:
                            questions[stage]['primary_questions'].append(value)
                    elif key == 'Transition' and value:
                        questions[stage]['transitions'].append(value)
            
            return questions
    except Exception as e:
        logger.error(f"Error loading coaching questions: {str(e)}", exc_info=True)
        return {}

async def analyze_user_response(user_message, conversation_history):
    """비동기 사용자 응답 분석"""
    try:
        headers = get_openai_headers()
        recent_history = conversation_history[-4:] if conversation_history else []
        history_text = "\n".join(recent_history)
        
        analysis_prompt = f"""대화 맥락을 고려하여 사용자의 응답을 분석해주세요...
        [이전 프롬프트와 동일]"""

        data = {
            'model': 'gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': analysis_prompt}
            ],
            'temperature': 0.7,
            'max_tokens': 300
        }

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: http.request(
                'POST',
                'https://api.openai.com/v1/chat/completions',
                body=json.dumps(data).encode('utf-8'),
                headers=headers
            )
        )
        
        analysis_result = json.loads(response.data.decode('utf-8'))['choices'][0]['message']['content']
        return json.loads(analysis_result)
    except Exception as e:
        logger.error(f"Error analyzing user response: {str(e)}", exc_info=True)
        return {
            'response_depth': 'medium',
            'emotional_state': 'neutral',
            'needs_follow_up': True,
            'suggested_focus': 'general',
            'stage_progress': 'middle',
            'key_themes': ['general']
        }

class SessionManager:
    """세션 관리 최적화 클래스"""
    def __init__(self):
        self.cache = {}
    
    async def get_session(self, user_id):
        """캐시된 세션 데이터 조회"""
        if user_id in self.cache:
            session_data = self.cache[user_id]
            if datetime.now() < session_data['cache_expires']:
                return session_data
        
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sessions_table.get_item(Key={'user_id': user_id})
            )
            
            current_time = datetime.now()
            default_analysis = {
                'response_depth': 'medium',
                'emotional_state': 'neutral',
                'needs_follow_up': True,
                'suggested_focus': 'general',
                'stage_progress': 'early',
                'key_themes': ['general']
            }
            
            if 'Item' not in response:
                session_data = {
                    'user_id': user_id,
                    'current_stage': 'Trust',
                    'conversation_history': [],
                    'used_questions': [],
                    'action_items': [],
                    'last_analysis': json.dumps(default_analysis),
                    'last_interaction': current_time.isoformat(),
                    'ttl': int((current_time + timedelta(days=7)).timestamp())
                }
                await self.update_session(session_data)
            else:
                session_data = response['Item']
            
            session_data['cache_expires'] = current_time + timedelta(minutes=5)
            self.cache[user_id] = session_data
            return session_data
            
        except Exception as e:
            logger.error(f"Error getting session data: {str(e)}", exc_info=True)
            return {
                'user_id': user_id,
                'current_stage': 'Trust',
                'conversation_history': [],
                'used_questions': [],
                'action_items': [],
                'last_analysis': json.dumps(default_analysis)
            }
    
    async def update_session(self, session_data):
        """세션 데이터 비동기 업데이트"""
        try:
            user_id = session_data['user_id']
            session_data['last_interaction'] = datetime.now().isoformat()
            
            # 캐시 업데이트
            self.cache[user_id] = session_data
            session_data['cache_expires'] = datetime.now() + timedelta(minutes=5)
            
            # DynamoDB 업데이트
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sessions_table.put_item(Item=session_data)
            )
        except Exception as e:
            logger.error(f"Error updating session data: {str(e)}", exc_info=True)
            raise

async def lambda_handler(event, context):
    """비동기 Lambda 핸들러"""
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        try:
            body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event.get('body', {})
        except json.JSONDecodeError:
            body = {}
            
        logger.info(f"Parsed body: {json.dumps(body)}")
        
        if 'test' in event:
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Test event received successfully'})
            }
            
        if 'userRequest' not in body:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid request format: userRequest not found'})
            }
            
        user_id = body['userRequest']['user']['id']
        user_message = body['userRequest']['utterance']

        # 세션 매니저 초기화
        session_manager = SessionManager()
        
        # 비동기 작업 동시 실행
        session_data, coaching_questions = await asyncio.gather(
            session_manager.get_session(user_id),
            load_coaching_questions()
        )

        # 사용자 응답 분석 (비동기)
        analysis_result = await analyze_user_response(
            user_message, 
            session_data.get('conversation_history', [])
        )
        
        # 나머지 로직은 이전과 동일하게 유지하되 비동기로 처리
        # [이전 코드와 동일한 로직]
        
        await session_manager.update_session(session_data)

        response_body = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": coach_response
                        }
                    }
                ]
            }
        }

        return {
            'statusCode': 200,
            'body': json.dumps(response_body, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json'
            }
        }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        error_response = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "죄송합니다. 일시적인 오류가 발생했습니다. 다시 시도해주세요."
                        }
                    }
                ]
            }
        }
        return {
            'statusCode': 200,
            'body': json.dumps(error_response, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json'
            }
        }
