from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    api_key = Column(String, unique=True)
    credits = Column(Integer, default=100)
    subscription_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tasks = relationship("Task", back_populates="owner")
    api_requests = relationship("APIRequest", back_populates="user")
    subscription = relationship("Subscription", back_populates="user", uselist=False)

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String)
    status = Column(String, default="todo")
    priority = Column(String, default="medium")
    tags = Column(JSON, default=list)
    due_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="tasks")

class APIRequest(Base):
    __tablename__ = "api_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    model = Column(String)
    tokens_used = Column(Integer)
    endpoint = Column(String)
    method = Column(String)
    status_code = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="api_requests")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    stripe_subscription_id = Column(String, unique=True)
    plan_id = Column(String)
    status = Column(String)
    current_period_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="subscription")

class WorkoutRoutine(Base):
    __tablename__ = "workout_routines"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    description = Column(String)
    exercises = Column(JSON)
    tips = Column(JSON)
    progression = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    workout_logs = relationship("WorkoutLog", back_populates="routine")

class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    routine_id = Column(Integer, ForeignKey("workout_routines.id"))
    completed_exercises = Column(JSON)
    notes = Column(String, nullable=True)
    duration = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    routine = relationship("WorkoutRoutine", back_populates="workout_logs")