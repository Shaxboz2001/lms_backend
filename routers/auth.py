from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from .schemas import UserCreate, UserResponse
from .database import SessionLocal
from .models import User

auth_router = APIRouter(prefix="/auth", tags=["Auth"])

# ------------------------------
# Sozlamalar
# ------------------------------
SECRET_KEY = "2001"  # ⚠️ Render uchun ENV dan olish yaxshiroq
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ------------------------------
# DB sessiya
# ------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------------
# Token yaratish
# ------------------------------
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ------------------------------
# Register
# ------------------------------
@auth_router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="❌ Username already exists")

    # ⚠️ bcrypt 72 baytdan uzun parollarni qabul qilmaydi
    safe_password = user.password[:72]
    hashed_pw = pwd_context.hash(safe_password)

    new_user = User(
        username=user.username,
        password=hashed_pw,
        role=user.role,
        full_name=user.full_name,
        phone=user.phone,
        address=user.address,
        subject=user.subject,
        fee=user.fee,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


# ------------------------------
# Login
# ------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

@auth_router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()

    if not user:
        raise HTTPException(status_code=401, detail="Foydalanuvchi topilmadi")

    # ⚠️ 72 bayt limitini inobatga olamiz
    safe_password = request.password[:72]

    try:
        valid = pwd_context.verify(safe_password, user.password)
    except Exception as e:
        print(f"❌ [LOGIN ERROR] bcrypt verify xato: {e}")
        raise HTTPException(status_code=500, detail="Parolni tekshirishda xatolik")

    if not valid:
        raise HTTPException(status_code=401, detail="Noto‘g‘ri login yoki parol")

    access_token = create_access_token({"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role.value if hasattr(user.role, 'value') else user.role,
        "userid": user.id
    }

# ------------------------------
# Get Current User
# ------------------------------
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


# ------------------------------
# Current user endpoint (test)
# ------------------------------
@auth_router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
