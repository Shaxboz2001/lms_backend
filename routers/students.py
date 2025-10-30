from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from passlib.context import CryptContext
from .dependencies import get_db, get_current_user
from .schemas import UserResponse, UserCreate, UserBase
from .models import User, UserRole, StudentStatus, Course, StudentCourse, StudentAnswer

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
    # 🔒 Faqat admin yoki manager
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    # 🔍 Username mavjudligini tekshirish
    existing_user = db.query(User).filter(User.username == student.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # 🔒 Parolni hash qilish
    hashed_password = pwd_context.hash(student.password or "1234")

    # 🎓 Kursni tekshirish (fee olish uchun)
    course_fee = None
    if getattr(student, "course_id", None):
        course = db.query(Course).filter(Course.id == student.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        course_fee = course.price  # ✅ course.price dan olinadi

    # 🧑‍🎓 Yangi student
    new_student = User(
        username=student.username,
        full_name=student.full_name,
        password=hashed_password,
        phone=student.phone,
        address=student.address,
        role=UserRole.student,
        fee=course_fee or student.fee,
        status=student.status or StudentStatus.studying,
        age=student.age,
        group_id=getattr(student, "group_id", None),
        teacher_id=getattr(student, "teacher_id", None),
    )

    db.add(new_student)
    db.commit()
    db.refresh(new_student)

    # 🧩 Agar kurs tanlangan bo‘lsa, StudentCourse jadvaliga qo‘shamiz
    if getattr(student, "course_id", None):
        new_enrollment = StudentCourse(
            student_id=new_student.id,
            course_id=student.course_id
        )
        db.add(new_enrollment)
        db.commit()

    return new_student


# ✅ Barcha studentlarni olish
@students_router.get("/", response_model=List[UserResponse])
def get_students(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")

    students = db.query(User).filter(User.role == UserRole.student).all()
    return students


# ✅ Bitta studentni olish
@students_router.get("/{student_id}", response_model=UserResponse)
def get_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


# ✅ Studentni yangilash
@students_router.put("/{student_id}", response_model=UserResponse)
def update_student(
    student_id: int,
    updated: UserBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    update_data = updated.dict(exclude_unset=True)

    # 🔒 Parol yangilansa — hash qilamiz
    if "password" in update_data and update_data["password"]:
        update_data["password"] = pwd_context.hash(update_data["password"])

    # 🎓 Agar course_id o‘zgarsa — StudentCourse jadvalini yangilaymiz
    if "course_id" in update_data and update_data["course_id"]:
        new_course = db.query(Course).filter(Course.id == update_data["course_id"]).first()
        if not new_course:
            raise HTTPException(status_code=404, detail="New course not found")

        # Eski enrolmentni o‘chir
        db.query(StudentCourse).filter(StudentCourse.student_id == student.id).delete()

        # Yangi enrolment qo‘sh
        new_enrollment = StudentCourse(
            student_id=student.id,
            course_id=update_data["course_id"]
        )
        db.add(new_enrollment)

        update_data["fee"] = new_course.price

    # 🧩 Ma'lumotlarni yangilash
    for key, value in update_data.items():
        setattr(student, key, value)

    db.commit()
    db.refresh(student)
    return student


# ✅ Studentni o‘chirish
@students_router.delete("/{student_id}")
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # 1️⃣ StudentAnswer dan o‘chiramiz
    db.query(StudentAnswer).filter(StudentAnswer.student_id == student.id).delete(synchronize_session=False)

    # 2️⃣ StudentCourse dan ham o‘chiramiz
    db.query(StudentCourse).filter(StudentCourse.student_id == student.id).delete(synchronize_session=False)

    # 3️⃣ Student o‘zi
    db.delete(student)
    db.commit()

    return {"detail": f"✅ Student '{student.full_name}' deleted successfully"}
