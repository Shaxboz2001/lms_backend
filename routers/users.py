from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..dependencies import get_db, get_current_user  # JWT bilan get_current_user

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# ------------------------------
# GET all users
# ------------------------------
@router.get("/", response_model=List[schemas.UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)  # JWT orqali
):
    # Admin va manager barcha userlarni ko‘ra oladi
    if current_user.role in [models.UserRole.admin, models.UserRole.manager]:
        users = db.query(models.User).all()
    else:
        # Teacher va student faqat o‘zini ko‘rishi mumkin
        users = [current_user]
    return users

# ------------------------------
# Create new user
# ------------------------------
@router.post("/", response_model=schemas.UserResponse)
def create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: schemas.RoleEnum = Body(schemas.RoleEnum.student),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)  # JWT orqali
):
    # Faqat admin yoki manager user qo‘sha oladi
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to create users")

    # Username unique tekshiruv
    existing_user = db.query(models.User).filter(models.User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Passwordni hash qilish
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed_pw = pwd_context.hash(password)

    new_user = models.User(
        username=username,
        password=hashed_pw,
        role=models.UserRole(role)
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
