from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .auth import get_current_user
from .dependencies import get_db
from .schemas import CourseOut, CourseCreate
from .models import User, Course

courses_router = APIRouter(prefix="/courses", tags=["Courses"])


@courses_router.post("/", response_model=CourseOut)
def create_course(
    course: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # O‘qituvchini bazadan olish
    teacher = db.query(User).filter(User.id == course.teacher_id).first()
    if not teacher or teacher.role != "teacher":
        raise HTTPException(status_code=400, detail="O‘qituvchi topilmadi yoki noto‘g‘ri rol")

    # Yangi kurs yaratish
    new_course = Course(
        title=course.title,
        subject=course.subject,
        teacher_name=teacher.full_name,  # 🔹 fullname ishlatyapmiz
        price=course.price,
        start_date=course.start_date,
        description=course.description,
        created_by=current_user.id,
    )

    db.add(new_course)
    db.commit()
    db.refresh(new_course)

    return CourseOut(
        id=new_course.id,
        title=new_course.title,
        subject=new_course.subject,
        teacher_name=new_course.teacher_name,
        price=new_course.price,
        start_date=new_course.start_date,
        description=new_course.description,
        creator_id=new_course.created_by,
        creator_name=current_user.full_name,
    )


@courses_router.get("/", response_model=list[CourseOut])
def get_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).all()
    return [
        CourseOut(
            id=c.id,
            title=c.title,
            subject=c.subject,
            teacher_name=c.teacher_name,
            price=c.price,
            start_date=c.start_date,
            description=c.description,
            creator_id=c.created_by,
            creator_name=c.creator.full_name if c.creator else None,
        )
        for c in courses
    ]
