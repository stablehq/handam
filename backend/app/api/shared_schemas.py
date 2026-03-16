"""Shared Pydantic response schemas for API consistency"""
from pydantic import BaseModel
from typing import Optional


class ActionResponse(BaseModel):
    success: bool
    message: str


class ExecutionResult(BaseModel):
    success: bool
    target_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    message: Optional[str] = None
