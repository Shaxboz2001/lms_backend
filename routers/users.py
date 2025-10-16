from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List
from passlib.context import CryptContext
from .dependencies import get_db, get_current_user
from .schemas import UserResponse, RoleEnum, UserUpdate
from .models import User, UserRole

users_router = APIRouter(prefix="/users", tags=["Users"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ------------------------------
# GET All Users
# ------------------------------
@users_router.get("/", response_model=List[UserResponse])
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role in [UserRole.admin, UserRole.manager]:
        return db.query(User).all()
    return [current_user]


# ------------------------------
# CREATE User
# ------------------------------
@users_router.post("/", response_model=UserResponse)
def create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: RoleEnum = Body(RoleEnum.student),
    full_name: str = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Foydalanuvchi yaratish uchun ruxsat yo‘q")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Bu foydalanuvchi nomi band")

    hashed_pw = pwd_context.hash(password)
    new_user = User(username=username, password=hashed_pw, role=UserRole(role), full_name=full_name)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


# ------------------------------
# GET My Profile
# ------------------------------
@users_router.get("/me", response_model=UserResponse)
def get_my_profile(current_user: User = Depends(get_current_user)):
    return current_user


# ------------------------------
# UPDATE User
# ------------------------------
@users_router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    if current_user.id != user_id and current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Bu foydalanuvchini tahrirlash mumkin emas")

    data = user_update.dict(exclude_unset=True)
    if "password" in data:
        data["password"] = pwd_context.hash(data["password"])

    for key, val in data.items():
        setattr(user, key, val)

    db.commit()
    db.refresh(user)
    return user


# ------------------------------
# GET Single User
# ------------------------------
@users_router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    if current_user.role != UserRole.admin and current_user.id != user.id:
        raise HTTPException(status_code=403, detail="Bu profilni ko‘rish mumkin emas")

    return user
