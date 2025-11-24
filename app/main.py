"""
Flask application - Main entry point
"""
import logging
import os
import json
from flask import Flask, request, jsonify
from datetime import datetime
from .coaching_service import CoachingService

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask 앱 생성
app = Flask(__name__)

# 코칭 서비스 초기화
coaching_service = CoachingService()

# 통계 변수
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
    """
    헬스 체크 엔드포인트

    Returns:
        JSON response with health status
    """
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
    """
    통계 엔드포인트

    Returns:
        JSON response with statistics
    """
    return jsonify({
        "total_requests": request_count,
        "error_count": error_count,
        "success_rate": (request_count - error_count) / request_count * 100 if request_count > 0 else 0,
        "uptime_seconds": (datetime.now() - start_time).total_seconds()
    }), 200


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    카카오톡 웹훅 엔드포인트

    KakaoTalk에서 POST 요청으로 사용자 메시지를 받아서 처리합니다.

    Returns:
        JSON response in KakaoTalk format
    """
    global request_count, error_count
    request_count += 1

    try:
        # 요청 데이터 파싱
        data = request.get_json()
        if not data:
            logger.error("No JSON data received")
            error_count += 1
            return jsonify(coaching_service.error_response()), 200

        logger.info(f"Received data: {json.dumps(data, ensure_ascii=False)}")

        # 코칭 서비스 처리
        response = coaching_service.process_message(data)

        logger.info(f"Sending response: {json.dumps(response, ensure_ascii=False)[:200]}...")
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
