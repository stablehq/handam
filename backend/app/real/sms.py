"""
Real SMS Provider - 알리고(Aligo) SMS API 연동
API 문서: https://smartsms.aligo.in/admin/api/spec.html
"""
from typing import Dict, Any, List
from datetime import datetime
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

ALIGO_SEND_URL = "https://apis.aligo.in/send/"
ALIGO_SEND_MASS_URL = "https://apis.aligo.in/send_mass/"
ALIGO_REMAIN_URL = "https://apis.aligo.in/remain/"

# SMS: 90바이트 이하, LMS: 90바이트 초과
SMS_BYTE_LIMIT = 90
# 알리고 /send/ 엔드포인트 LMS 바이트 제한 (EUC-KR 기준)
# 초과 시 /send_mass/ (cnt=1)로 폴백
LMS_BYTE_LIMIT = 2000


def _detect_msg_type(message: str) -> str:
    """메시지 바이트 길이로 SMS/LMS 자동 판단 (EUC-KR 기준)"""
    try:
        byte_len = len(message.encode("euc-kr"))
    except UnicodeEncodeError:
        # EUC-KR 인코딩 불가 문자 포함 시 UTF-8 바이트 기준으로 fallback
        byte_len = len(message.encode("utf-8"))
    return "SMS" if byte_len <= SMS_BYTE_LIMIT else "LMS"


def _build_auth_params() -> Dict[str, str]:
    """알리고 인증 파라미터 반환"""
    return {
        "key": settings.ALIGO_API_KEY,
        "user_id": settings.ALIGO_USER_ID,
    }


class RealSMSProvider:
    """알리고 SMS API를 사용하는 실제 SMS 발송 프로바이더"""

    def __init__(self, api_key: str = "", user_id: str = "", sender: str = "", testmode: bool = True):
        self.api_key = api_key or settings.ALIGO_API_KEY
        self.user_id = user_id or settings.ALIGO_USER_ID
        self.sender = sender or settings.ALIGO_SENDER
        self.testmode = testmode if testmode is not None else True
        testmode_label = "testmode=Y (실제 미발송)" if self.testmode else "testmode=N (실제 발송)"
        logger.info(f"[RealSMSProvider] 초기화 완료 — sender={self.sender}, {testmode_label}")

    # ------------------------------------------------------------------
    # Public interface (SMSProvider Protocol)
    # ------------------------------------------------------------------

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        """단건 SMS/LMS 발송 (알리고 /send/ 엔드포인트)

        Args:
            to: 수신 번호 (예: "01012345678")
            message: 발송 내용
            **kwargs:
                msg_type (str): "SMS" | "LMS" — 미지정 시 바이트 길이로 자동 판단
                title (str): LMS 제목 (LMS일 때만 사용)
                testmode_yn (str): "Y" | "N" — 미지정 시 self.testmode (tenant.aligo_testmode) 사용

        Returns:
            SMSProvider Protocol 표준 반환값
        """
        timestamp = datetime.now().isoformat()
        message_id = f"real_{int(datetime.now().timestamp())}"

        msg_type = kwargs.get("msg_type") or _detect_msg_type(message)
        testmode_yn = kwargs.get("testmode_yn", "Y" if self.testmode else "N")
        title = kwargs.get("title", "")

        # LMS 바이트 제한 초과 시 /send_mass/ (cnt=1)로 폴백
        if msg_type == "LMS":
            try:
                euc_byte_len = len(message.encode("euc-kr"))
            except UnicodeEncodeError:
                euc_byte_len = len(message.encode("utf-8"))
            if euc_byte_len > LMS_BYTE_LIMIT:
                logger.info(
                    f"[Aligo] LMS 바이트 초과 ({euc_byte_len} > {LMS_BYTE_LIMIT}), "
                    f"/send_mass/ 폴백 — to={to}"
                )
                return await self._send_single_via_mass(
                    to=to, message=message, msg_type=msg_type,
                    testmode_yn=testmode_yn, title=title, timestamp=timestamp,
                    fallback_message_id=message_id,
                )

        params: Dict[str, str] = {
            **_build_auth_params(),
            "sender": self.sender,
            "receiver": to,
            "msg": message,
            "msg_type": msg_type,
            "testmode_yn": testmode_yn,
        }
        if msg_type == "LMS" and title:
            params["title"] = title

        logger.info(
            f"[Aligo] 단건 발송 — to={to}, msg_type={msg_type}, "
            f"testmode={testmode_yn}, bytes={len(message.encode('utf-8', errors='replace'))}"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ALIGO_SEND_URL,
                    data=params,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()

            logger.info(f"[Aligo] 단건 응답: {result}")

            success = str(result.get("result_code")) == "1"
            if not success:
                logger.warning(f"[Aligo] 발송 실패: result_code={result.get('result_code')}, message={result.get('message')}")

            return {
                "success": success,
                "message_id": str(result.get("msg_id", message_id)),
                "to": to,
                "message": message,
                "timestamp": timestamp,
                "provider": "real",
                "error": None if success else result.get("message", "알 수 없는 오류"),
                "raw": result,
            }

        except httpx.HTTPError as e:
            logger.error(f"[Aligo] HTTP 오류 (단건 발송): {e}")
            return {
                "success": False,
                "message_id": message_id,
                "to": to,
                "message": message,
                "timestamp": timestamp,
                "provider": "real",
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"[Aligo] 예외 (단건 발송): {e}")
            return {
                "success": False,
                "message_id": message_id,
                "to": to,
                "message": message,
                "timestamp": timestamp,
                "provider": "real",
                "error": str(e),
            }

    async def send_bulk(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """대량 SMS/LMS 발송 (알리고 /send_mass/ 엔드포인트)

        500건 초과 시 자동으로 배치 분할하여 순차 발송.

        Args:
            messages: [{"to": "01012345678", "message": "내용"}, ...] 리스트
            **kwargs:
                msg_type (str): "SMS" | "LMS" — 미지정 시 각 메시지별 자동 판단
                title (str): LMS 제목
                testmode_yn (str): "Y" | "N"

        Returns:
            SMSProvider Protocol 표준 반환값
        """
        timestamp = datetime.now().isoformat()
        total = len(messages)

        if not messages:
            logger.warning("[Aligo] 대량 발송: 메시지 없음")
            return {
                "success": False,
                "total": 0,
                "sent": 0,
                "failed": 0,
                "timestamp": timestamp,
                "provider": "real",
                "error": "발송할 메시지가 없습니다.",
            }

        testmode_yn = kwargs.get("testmode_yn", "Y" if self.testmode else "N")
        title = kwargs.get("title", "")

        # 500건 단위로 배치 분할
        batch_size = 500
        batches = [messages[i:i + batch_size] for i in range(0, total, batch_size)]
        logger.info(f"[Aligo] 대량 발송 시작 — 총 {total}건, {len(batches)}배치, testmode={testmode_yn}")

        total_sent = 0
        total_failed = 0
        batch_errors: List[str] = []

        for batch_idx, batch in enumerate(batches, start=1):
            result = await self._send_mass_batch(batch, testmode_yn=testmode_yn, title=title, **kwargs)
            if result.get("success"):
                total_sent += result.get("success_cnt", len(batch))
                logger.info(f"[Aligo] 배치 {batch_idx}/{len(batches)} 완료 — {result.get('success_cnt')}건 성공")
            else:
                total_failed += len(batch)
                error_msg = result.get("error", "알 수 없는 오류")
                batch_errors.append(f"배치{batch_idx}: {error_msg}")
                logger.error(f"[Aligo] 배치 {batch_idx}/{len(batches)} 실패 — {error_msg}")

        overall_success = total_failed == 0
        return {
            "success": overall_success,
            "total": total,
            "sent": total_sent,
            "failed": total_failed,
            "timestamp": timestamp,
            "provider": "real",
            "error": "; ".join(batch_errors) if batch_errors else None,
        }

    async def get_remain(self) -> Dict[str, Any]:
        """알리고 잔여건수 조회 (/remain/ 엔드포인트)

        Returns:
            {"success": bool, "SMS_CNT": int, "LMS_CNT": int, "MMS_CNT": int, "error": str|None}
        """
        params = _build_auth_params()
        logger.info("[Aligo] 잔여건수 조회")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(ALIGO_REMAIN_URL, data=params, timeout=10.0)
                response.raise_for_status()
                result = response.json()

            logger.info(f"[Aligo] 잔여건수: SMS={result.get('SMS_CNT')}, LMS={result.get('LMS_CNT')}, MMS={result.get('MMS_CNT')}")
            success = str(result.get("result_code")) == "1"
            return {
                "success": success,
                "SMS_CNT": result.get("SMS_CNT", 0),
                "LMS_CNT": result.get("LMS_CNT", 0),
                "MMS_CNT": result.get("MMS_CNT", 0),
                "error": None if success else result.get("message"),
                "raw": result,
            }

        except Exception as e:
            logger.error(f"[Aligo] 잔여건수 조회 오류: {e}")
            return {"success": False, "SMS_CNT": 0, "LMS_CNT": 0, "MMS_CNT": 0, "error": str(e)}

    async def simulate_receive(self, from_: str, to: str, message: str) -> Dict[str, Any]:
        """SMS 수신 시뮬레이션 (테스트/데모 전용, production에서는 webhook 사용)"""
        timestamp = datetime.now().isoformat()
        message_id = f"real_received_{int(datetime.now().timestamp())}"

        logger.info(f"[SIMULATED SMS RECEIVED] From: {from_}, To: {to}, Message: {message}")

        return {
            "success": True,
            "message_id": message_id,
            "from_": from_,
            "to": to,
            "message": message,
            "timestamp": timestamp,
            "provider": "real",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _send_single_via_mass(
        self,
        to: str,
        message: str,
        msg_type: str,
        testmode_yn: str,
        title: str,
        timestamp: str,
        fallback_message_id: str,
    ) -> Dict[str, Any]:
        """/send/ LMS 바이트 제한 초과 시 /send_mass/ (cnt=1)로 단건 발송"""
        result = await self._send_mass_batch(
            batch=[{"to": to, "message": message}],
            testmode_yn=testmode_yn,
            title=title,
            msg_type=msg_type,
        )

        success = result.get("success", False)
        return {
            "success": success,
            "message_id": str(result.get("raw", {}).get("msg_id", fallback_message_id)),
            "to": to,
            "message": message,
            "timestamp": timestamp,
            "provider": "real",
            "error": None if success else result.get("error", "알 수 없는 오류"),
            "raw": result.get("raw"),
        }

    async def _send_mass_batch(
        self,
        batch: List[Dict[str, str]],
        testmode_yn: str = "Y",
        title: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """단일 배치(최대 500건)를 /send_mass/ 엔드포인트로 발송"""
        cnt = len(batch)

        # msg_type: kwargs 우선, 없으면 첫 메시지 기준으로 자동 판단
        msg_type = kwargs.get("msg_type") or _detect_msg_type(batch[0]["message"])

        params: Dict[str, str] = {
            **_build_auth_params(),
            "sender": self.sender,
            "cnt": str(cnt),
            "msg_type": msg_type,
            "testmode_yn": testmode_yn,
        }
        if msg_type == "LMS" and title:
            params["title"] = title

        for i, msg in enumerate(batch, start=1):
            params[f"rec_{i}"] = msg["to"]
            params[f"msg_{i}"] = msg["message"]

        logger.info(f"[Aligo] /send_mass/ 요청 — {cnt}건, msg_type={msg_type}, testmode={testmode_yn}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    ALIGO_SEND_MASS_URL,
                    data=params,
                    timeout=60.0,
                )
                response.raise_for_status()
                result = response.json()

            logger.info(f"[Aligo] /send_mass/ 응답: {result}")

            success = str(result.get("result_code")) == "1"
            return {
                "success": success,
                "success_cnt": result.get("success_cnt", 0),
                "error_cnt": result.get("error_cnt", 0),
                "error": None if success else result.get("message", "알 수 없는 오류"),
                "raw": result,
            }

        except httpx.HTTPError as e:
            logger.error(f"[Aligo] HTTP 오류 (/send_mass/): {e}")
            return {"success": False, "success_cnt": 0, "error_cnt": cnt, "error": str(e)}
        except Exception as e:
            logger.error(f"[Aligo] 예외 (/send_mass/): {e}")
            return {"success": False, "success_cnt": 0, "error_cnt": cnt, "error": str(e)}
