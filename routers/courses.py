from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .dependencies import get_db, get_current_user
from .schemas import CourseCreate, CourseOut
from .models import User, Course, UserRole

courses_router = APIRouter(prefix="/courses", tags=["Courses"])

# ------------------------------
# CREATE Course
# ------------------------------
@courses_router.post("/", response_model=CourseOut)
def create_course(
    course: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Kurs yaratish uchun ruxsat yo‘q")

    teacher = db.query(User).filter(User.id == course.teacher_id).first()
    if not teacher or teacher.role != UserRole.teacher:
        raise HTTPException(status_code=400, detail="O‘qituvchi topilmadi yoki noto‘g‘ri rol")

    new_course = Course(
        title=course.title,
        subject=course.subject,
        teacher_name=teacher.full_name,
        price=course.price,
        start_date=course.start_date,
        description=course.description,
        created_by=current_user.id,
    )

    db.add(new_course)
    db.commit()
    db.refresh(new_course)

    return CourseOut.from_orm(new_course)


# ------------------------------
# GET All Courses
# ------------------------------
@courses_router.get("/", response_model=List[CourseOut])
def get_courses(db: Session = Depends(get_db)):
    return db.query(Course).all()
