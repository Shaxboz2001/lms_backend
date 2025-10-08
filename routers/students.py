from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..dependencies import get_db, get_current_user
from passlib.context import CryptContext

router = APIRouter(
    prefix="/students",
    tags=["Students"]
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ✅ Student qo‘shish
@router.post("/", response_model=schemas.UserResponse)
def create_student(
    student: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    existing_user = db.query(models.User).filter(models.User.username == student.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # 🔥 Parolni hash qilib saqlaymiz
    hashed_password = pwd_context.hash(student.password or "1234")

    new_student = models.User(
        username=student.username,
        full_name=student.full_name,
        password=hashed_password,  # 🔥 bu yerda endi hashlangan parol
        phone=student.phone,
        address=student.address,
        role=models.UserRole.student,
        subject=student.subject,
        fee=student.fee,
        status=student.status or models.StudentStatus.studying,
        age=student.age,
        group_id=student.group_id,
        teacher_id=student.teacher_id
    )

    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


# ✅ Barcha studentlarni olish
@router.get("/", response_model=List[schemas.UserResponse])
def get_students(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager, models.UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")

    students = db.query(models.User).filter(models.User.role == models.UserRole.student).all()
    return students


# ✅ Bitta studentni olish
@router.get("/{student_id}", response_model=schemas.UserResponse)
def get_student(student_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    student = db.query(models.User).filter(models.User.id == student_id, models.User.role == models.UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


# ✅ Student ma'lumotini o‘zgartirish
@router.put("/{student_id}", response_model=schemas.UserResponse)
def update_student(
    student_id: int,
    updated: schemas.UserBase,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager, models.UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")

    student = db.query(models.User).filter(
        models.User.id == student_id,
        models.User.role == models.UserRole.student
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
@router.delete("/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    student = db.query(models.User).filter(models.User.id == student_id, models.User.role == models.UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    db.delete(student)
    db.commit()
    return {"detail": "Student deleted successfully"}
