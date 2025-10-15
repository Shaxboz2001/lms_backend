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
    new_course = Course(
        title=course.title,
        description=course.description,
        start_date=course.start_date,
        price=course.price,
        creator_id=current_user.id,
    )
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    return CourseOut(
        id=new_course.id,
        title=new_course.title,
        description=new_course.description,
        start_date=new_course.start_date,
        price=new_course.price,
        creator_id=new_course.creator_id,
        creator_name=current_user.full_name,
    )


@courses_router.get("/", response_model=list[CourseOut])
def get_courses(db: Session = Depends(get_db)):
    courses = db.query(Course).all()
    return [
        CourseOut(
            id=c.id,
            title=c.title,
            description=c.description,
            start_date=c.start_date,
            price=c.price,
            creator_id=c.creator_id,
            creator_name=c.creator.full_name if c.creator else None,
        )
        for c in courses
    ]
