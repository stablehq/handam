"""_detect_msg_type() 유닛 테스트 — 순수 함수, DB 불필요."""
import pytest
from app.real.sms import _detect_msg_type


class TestDetectMsgType:
    def test_short_korean_is_sms(self):
        """짧은 한국어 — EUC-KR 90바이트 이하 → SMS."""
        text = "안녕하세요"  # 10 bytes EUC-KR
        assert _detect_msg_type(text) == "SMS"

    def test_long_korean_is_lms(self):
        """긴 한국어 — EUC-KR 90바이트 초과 → LMS."""
        # 한글 1자 = 2바이트 EUC-KR, 46자 = 92바이트
        text = "가" * 46
        assert _detect_msg_type(text) == "LMS"

    def test_english_only_is_sms(self):
        """영어 — 90바이트 이하 → SMS."""
        text = "Hello World"  # 11 bytes
        assert _detect_msg_type(text) == "SMS"

    def test_long_english_is_lms(self):
        """영어 91자 → LMS."""
        text = "a" * 91
        assert _detect_msg_type(text) == "LMS"

    def test_exactly_90_bytes_is_sms(self):
        """정확히 90바이트(한글 45자) → SMS (경계값)."""
        text = "가" * 45  # 90 bytes EUC-KR
        assert _detect_msg_type(text) == "SMS"

    def test_91_bytes_is_lms(self):
        """91바이트 → LMS."""
        # 45 한글(90 bytes) + 1 영문(1 byte) = 91 bytes
        text = "가" * 45 + "a"
        assert _detect_msg_type(text) == "LMS"

    def test_empty_string_is_sms(self):
        """빈 문자열 → SMS."""
        assert _detect_msg_type("") == "SMS"

    def test_mixed_korean_english(self):
        """한글+영문 혼합 짧은 문자 → SMS."""
        text = "안녕 Hello"  # 4+5+1+1 = 4*2+6 = 14 bytes EUC-KR
        assert _detect_msg_type(text) == "SMS"
