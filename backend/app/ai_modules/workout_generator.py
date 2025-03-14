from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, WorkoutRoutine, WorkoutLog
from ..auth import get_current_user
from openai import AsyncOpenAI
import os
import json

router = APIRouter(
    prefix="/api/workout",
    tags=["workout"]
)

# Cliente OpenAI para el módulo de workout
client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=os.getenv("BASE_URL")
)

# Modelos Pydantic
class Exercise(BaseModel):
    name: str
    sets: int
    reps: str
    rest: str
    notes: Optional[str] = None

class WorkoutRoutineCreate(BaseModel):
    name: str
    description: str
    exercises: List[Exercise]
    tips: List[str]
    progression: List[str]

class WorkoutLogCreate(BaseModel):
    routine_id: int
    completed_exercises: List[dict]
    notes: Optional[str] = None
    duration: float

class WorkoutPrompt(BaseModel):
    goal: str
    experience_level: str
    equipment_available: List[str]
    time_available: int
    focus_areas: List[str]
    injuries: Optional[List[str]] = None

# Funciones auxiliares
def format_workout_prompt(prompt: WorkoutPrompt) -> str:
    """Formatea los datos del prompt para el modelo de IA"""
    return f"""Genera una rutina de entrenamiento detallada con las siguientes especificaciones:    
    - Objetivo: {prompt.goal}
    - Nivel de experiencia: {prompt.experience_level}
    - Equipo disponible: {', '.join(prompt.equipment_available)}
    - Tiempo disponible: {prompt.time_available} minutos
    - Áreas de enfoque: {', '.join(prompt.focus_areas)}
    - Lesiones/Limitaciones: {', '.join(prompt.injuries) if prompt.injuries else 'Ninguna'}
    
    Por favor, proporciona la rutina en formato JSON con la siguiente estructura:
    {{
        "name": "Nombre de la rutina",
        "description": "Descripción detallada",
        "exercises": [
            {{
                "name": "Nombre del ejercicio",
                "sets": número_de_series,
                "reps": "rango_de_repeticiones",
                "rest": "tiempo_de_descanso",
                "notes": "notas_técnicas"
            }}
        ],
        "tips": ["consejos_importantes"],
        "progression": ["sugerencias_de_progresión"]
    }}
    """

# Endpoints
@router.post("/generate")
async def generate_workout(
    prompt: WorkoutPrompt,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Genera una rutina de entrenamiento personalizada usando IA"""
    try:
        # Imprimir el prompt para debugging
        print(f"Generating workout with prompt: {prompt}")
        
        # Generar la rutina
        response = await client.chat.completions.create(
            model="qwen/qwq-32b:online",
            messages=[
                {
                    "role": "system",
                    "content": "Eres un entrenador personal experto especializado en crear rutinas de entrenamiento personalizadas."
                },
                {
                    "role": "user",
                    "content": format_workout_prompt(prompt)
                }
            ],
            temperature=0.7,
            max_tokens=2000
        )
        
        # Imprimir la respuesta para debugging
        print(f"Raw AI response: {response.choices[0].message.content}")
        
        # Extraer y validar el JSON de la respuesta
        try:
            workout_data = json.loads(response.choices[0].message.content)
            
            # Validar campos requeridos
            required_fields = ["name", "description", "exercises", "tips", "progression"]
            for field in required_fields:
                if field not in workout_data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Crear la rutina en la base de datos
            routine = WorkoutRoutine(
                user_id=current_user.id,
                **workout_data
            )
            db.add(routine)
            db.commit()
            db.refresh(routine)
            
            return routine
            
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error parsing AI response"
            )
            
    except Exception as e:
        print(f"Error generating workout: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating workout: {str(e)}"
        )

@router.post("/log")
async def log_workout(
    log: WorkoutLogCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Registra una sesión de entrenamiento completada"""
    # Verificar que la rutina existe y pertenece al usuario
    routine = db.query(WorkoutRoutine).filter(
        WorkoutRoutine.id == log.routine_id,
        WorkoutRoutine.user_id == current_user.id
    ).first()
    
    if not routine:
        raise HTTPException(status_code=404, detail="Workout routine not found")
    
    workout_log = WorkoutLog(
        user_id=current_user.id,
        **log.dict()
    )
    db.add(workout_log)
    db.commit()
    db.refresh(workout_log)
    
    return workout_log

@router.get("/history")
async def get_workout_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtiene el historial de entrenamientos del usuario"""
    logs = db.query(WorkoutLog).filter(
        WorkoutLog.user_id == current_user.id
    ).order_by(WorkoutLog.created_at.desc()).all()
    
    return logs

@router.get("/routines")
async def get_workout_routines(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtiene todas las rutinas de entrenamiento del usuario"""
    routines = db.query(WorkoutRoutine).filter(
        WorkoutRoutine.user_id == current_user.id
    ).order_by(WorkoutRoutine.created_at.desc()).all()
    
    return routines

@router.get("/routines/{routine_id}")
async def get_workout_routine(
    routine_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtiene una rutina de entrenamiento específica"""
    routine = db.query(WorkoutRoutine).filter(
        WorkoutRoutine.id == routine_id,
        WorkoutRoutine.user_id == current_user.id
    ).first()
    
    if not routine:
        raise HTTPException(status_code=404, detail="Workout routine not found")
    
    return routine