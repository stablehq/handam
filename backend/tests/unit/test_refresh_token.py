"""decode_refresh_token() 유닛 테스트 — 순수 함수, DB 불필요."""
import pytest
import jwt
from datetime import datetime, timedelta, timezone
from app.auth.utils import create_refresh_token, create_access_token, decode_refresh_token
from app.config import settings


class TestDecodeRefreshToken:
    def test_valid_refresh_token(self):
        """유효한 refresh token → 페이로드 반환."""
        token = create_refresh_token({"sub": "testuser"})
        payload = decode_refresh_token(token)
        assert payload["sub"] == "testuser"
        assert payload["type"] == "refresh"

    def test_access_token_rejected(self):
        """access token을 refresh token으로 사용 → 에러."""
        token = create_access_token({"sub": "testuser"})
        with pytest.raises(jwt.InvalidTokenError):
            decode_refresh_token(token)

    def test_expired_token_rejected(self):
        """만료된 토큰 → ExpiredSignatureError."""
        to_encode = {"sub": "testuser", "type": "refresh"}
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        to_encode["exp"] = expired
        token = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_refresh_token(token)

    def test_tampered_token_rejected(self):
        """서명 변조된 토큰 → PyJWTError."""
        token = create_refresh_token({"sub": "testuser"})
        # Tamper the token by appending garbage
        tampered = token + "xyz"
        with pytest.raises(jwt.PyJWTError):
            decode_refresh_token(tampered)

    def test_refresh_token_contains_sub(self):
        """refresh token payload에 sub 필드 포함."""
        token = create_refresh_token({"sub": "admin"})
        payload = decode_refresh_token(token)
        assert payload.get("sub") == "admin"
