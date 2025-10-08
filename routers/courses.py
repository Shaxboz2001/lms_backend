from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas, database
from .auth import get_current_user
from ..dependencies import get_db

router = APIRouter(prefix="/courses", tags=["Courses"])

@router.post("/", response_model=schemas.CourseOut)
def create_course(
    course: schemas.CourseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    new_course = models.Course(
        title=course.title,
        description=course.description,
        start_date=course.start_date,
        end_date=course.end_date,
        price=course.price,
        creator_id=current_user.id,
    )
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    return schemas.CourseOut(
        id=new_course.id,
        title=new_course.title,
        description=new_course.description,
        start_date=new_course.start_date,
        end_date=new_course.end_date,
        price=new_course.price,
        creator_id=new_course.creator_id,
        creator_name=current_user.full_name,
    )


@router.get("/", response_model=list[schemas.CourseOut])
def get_courses(db: Session = Depends(get_db)):
    courses = db.query(models.Course).all()
    return [
        schemas.CourseOut(
            id=c.id,
            title=c.title,
            description=c.description,
            start_date=c.start_date,
            end_date=c.end_date,
            price=c.price,
            creator_id=c.creator_id,
            creator_name=c.creator.full_name if c.creator else None,
        )
        for c in courses
    ]
