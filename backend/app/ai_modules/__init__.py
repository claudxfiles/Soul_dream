from fastapi import APIRouter
from .workout_generator import router as workout_router

__all__ = ["workout_router"]