from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List
from .dependencies import get_db, get_current_user  # JWT bilan get_current_user
from .schemas import UserResponse, RoleEnum, UserUpdate
from .models import User, UserRole

users_router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# ------------------------------
# GET all users
# ------------------------------
@users_router.get("/", response_model=List[UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # JWT orqali
):
    # Admin va manager barcha userlarni ko‘ra oladi
    if current_user.role in [UserRole.admin, UserRole.manager]:
        users = db.query(User).all()
    else:
        # Teacher va student faqat o‘zini ko‘rishi mumkin
        users = [current_user]
    return users

# ------------------------------
# Create new user
# ------------------------------
@users_router.post("/", response_model=UserResponse)
def create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: RoleEnum = Body(RoleEnum.student),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # JWT orqali
):
    # Faqat admin yoki manager user qo‘sha oladi
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to create users")

    # Username unique tekshiruv
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Passwordni hash qilish
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed_pw = pwd_context.hash(password)

    new_user = User(
        username=username,
        password=hashed_pw,
        role=UserRole(role)
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@users_router.get("/me")
def get_my_profile(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "phone": current_user.phone,
        "address": current_user.address,
        "age": current_user.age,
        "group_id": current_user.group_id,
        "subject": current_user.subject,
        "fee": current_user.fee,
        "status": current_user.status,
    }

@users_router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Ruxsat: faqat o'z profilini tahrirlash yoki admin/manager
    if current_user.id != user_id and current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to update this user")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.dict(exclude_unset=True)

    # Username uniqueness tekshiruvi (agar username kelgan bo'lsa)
    if "username" in update_data and update_data["username"]:
        exists = db.query(User).filter(User.username == update_data["username"], User.id != user_id).first()
        if exists:
            raise HTTPException(status_code=400, detail="Username already exists")

    # Agar password bor bo'lsa -> hash qilamiz
    if "password" in update_data and update_data["password"]:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        update_data["password"] = pwd_context.hash(update_data["password"])
    elif "password" in update_data and not update_data["password"]:
        # bo'sh parol jo'natilsa, uni inobatga olmang (ya'ni o'chiring)
        update_data.pop("password", None)

    # Yangilash
    for key, value in update_data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


@users_router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Faqat o‘z profilini yoki admin boshqa foydalanuvchini ko‘rishi mumkin
    if current_user.id != user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="You are not allowed to view this profile")

    return user

