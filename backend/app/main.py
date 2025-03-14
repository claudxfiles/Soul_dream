from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from openai import AsyncOpenAI
import asyncio
from dotenv import load_dotenv
import os
import stripe
from .auth import (
    get_current_user,
    create_access_token,
    get_password_hash,
    verify_password,
    generate_api_key
)
from .models import User, APIRequest, Subscription
from .database import get_db
from sqlalchemy.orm import Session
from typing import Optional, List
import redis
from .task_router import router as task_router
from .ai_modules import workout_router

# Cargar variables de entorno
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Configurar Redis para rate limiting
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

app = FastAPI(
    title="AI Task Manager",
    description="Sistema de gestión de tareas potenciado por IA",
    version="1.0.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(task_router, prefix="/api", tags=["tasks"])
app.include_router(workout_router)

# Cliente OpenAI global
client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=os.getenv("BASE_URL")
)

# Modelos Pydantic
class ChatRequest(BaseModel):
    message: str
    model: str = "qwen/qwq-32b:online"

class UserCreate(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class SubscriptionCreate(BaseModel):
    plan_id: str

# Endpoints de autenticación
@app.post("/register", response_model=Token)
async def register_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    api_key = generate_api_key()
    
    db_user = User(
        email=user.email,
        hashed_password=hashed_password,
        api_key=api_key
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="Incorrect email or password"
        )
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

async def record_api_usage(user_id: int, model: str, tokens: int, db: Session):
    """Registra el uso de la API en la base de datos"""
    api_request = APIRequest(
        user_id=user_id,
        model=model,
        tokens_used=tokens,
        endpoint="/chat",
        method="POST",
        status_code=200
    )
    db.add(api_request)
    db.commit()

# Endpoint de chat con rate limiting y tracking de uso
@app.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verificar rate limiting
    rate_key = f"rate_limit:{current_user.id}"
    requests = redis_client.get(rate_key)
    if requests and int(requests) > 100:  # 100 requests per hour
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Verificar créditos
    if current_user.credits <= 0:
        raise HTTPException(status_code=402, detail="No credits remaining")
    
    try:
        stream = await client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://your-site.com",
                "X-Title": "Your Application",
            },
            model=request.model,
            messages=[
                {
                    "role": "user",
                    "content": request.message
                }
            ],
            stream=True,
            extra_body={
                "provider": {
                    "order": ["Groq","Fireworks"],
                    "allow_fallbacks": False
                }
            }
        )
        
        response_text = ""
        tokens_used = 0
        
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                response_text += chunk.choices[0].delta.content
                tokens_used += 1
        
        # Registrar uso en background
        background_tasks.add_task(
            record_api_usage,
            user_id=current_user.id,
            model=request.model,
            tokens=tokens_used,
            db=db
        )
        
        return {"response": response_text}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def handle_successful_subscription(session: dict, db: Session):
    """Maneja una suscripción exitosa"""
    user = db.query(User).filter(User.email == session.customer_email).first()
    if user:
        subscription = Subscription(
            user_id=user.id,
            stripe_subscription_id=session.subscription,
            plan_id=session.line_items[0].price.id,
            status="active",
            current_period_end=session.subscription.current_period_end
        )
        db.add(subscription)
        db.commit()

# Endpoints de suscripción
@app.post("/create-checkout-session")
async def create_checkout_session(
    subscription: SubscriptionCreate,
    current_user: User = Depends(get_current_user)
):
    try:
        checkout_session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            line_items=[{"price": subscription.plan_id, "quantity": 1}],
            mode="subscription",
            success_url="http://localhost:3000/success",
            cancel_url="http://localhost:3000/cancel",
        )
        return {"url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    if event.type == "checkout.session.completed":
        session = event.data.object
        await handle_successful_subscription(session, db)
    
    return {"status": "success"}

# Endpoint de información del usuario
@app.get("/me")
async def get_user_info(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "credits": current_user.credits,
        "subscription": current_user.subscription_id
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)