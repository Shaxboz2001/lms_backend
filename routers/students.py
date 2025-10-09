from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .dependencies import get_db, get_current_user
from passlib.context import CryptContext
from .schemas import UserResponse, UserCreate, UserBase
from .models import User, UserRole, StudentStatus

students_router = APIRouter(
    prefix="/students",
    tags=["Students"]
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ✅ Student qo‘shish
@students_router.post("/", response_model=UserResponse)
def create_student(
    student: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    existing_user = db.query(User).filter(User.username == student.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # 🔥 Parolni hash qilib saqlaymiz
    hashed_password = pwd_context.hash(student.password or "1234")

    new_student = User(
        username=student.username,
        full_name=student.full_name,
        password=hashed_password,
        phone=student.phone,
        address=student.address,
        role=UserRole.student,
        subject=student.subject,
        fee=student.fee,
        status=StudentStatus.studying,  # <-- doim default
        age=student.age,
        group_id=student.group_id,
        teacher_id=student.teacher_id
    )

    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


# ✅ Barcha studentlarni olish
@students_router.get("/", response_model=List[UserResponse])
def get_students(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")

    students = db.query(User).filter(User.role == UserRole.student).all()
    return students


# ✅ Bitta studentni olish
@students_router.get("/{student_id}", response_model=UserResponse)
def get_student(student_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


# ✅ Student ma'lumotini o‘zgartirish
@students_router.put("/{student_id}", response_model=UserResponse)
def update_student(
    student_id: int,
    updated: UserBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")

    student = db.query(User).filter(
        User.id == student_id,
        User.role == UserRole.student
    ).first()

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    update_data = updated.dict(exclude_unset=True)

    # 🔒 Agar password kelgan bo‘lsa — hash qilamiz
    if "password" in update_data and update_data["password"]:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        update_data["password"] = pwd_context.hash(update_data["password"])

    # 🔁 Boshqa fieldlarni yangilaymiz
    for key, value in update_data.items():
        setattr(student, key, value)

    db.commit()
    db.refresh(student)
    return student



# ✅ Studentni o‘chirish
@students_router.delete("/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    db.delete(student)
    db.commit()
    return {"detail": "Student deleted successfully"}
