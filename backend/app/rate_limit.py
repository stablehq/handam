"""
Rate Limiting configuration — slowapi Limiter instance
Separated to avoid circular imports between main.py and api/auth.py
"""
from fastapi import Request
from slowapi import Limiter


def _get_real_ip(request: Request) -> str:
    """X-Forwarded-For 파싱 (nginx 프록시 대응)"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_ip)
