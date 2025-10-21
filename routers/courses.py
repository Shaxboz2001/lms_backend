# routers/courses.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from .dependencies import get_db, get_current_user
from .models import User, Course, UserRole, StudentCourse
from .schemas import CourseCreate, CourseOut, UserResponse

courses_router = APIRouter(prefix="/courses", tags=["Courses"])


# CREATE course (admin/manager)
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
        description=course.description,
        price=course.price,
        start_date=course.start_date,
        teacher_id=teacher.id,
        teacher_name=teacher.full_name,
        created_by=current_user.id,
    )

    db.add(new_course)
    db.commit()
    db.refresh(new_course)

    return CourseOut.from_orm(new_course)


# GET all courses (everyone)
@courses_router.get("/", response_model=List[CourseOut])
def get_courses(db: Session = Depends(get_db)):
    # joinedload so that frontend can access teacher_name etc.
    return db.query(Course).options(joinedload(Course.teacher)).all()


# GET course details (includes students if admin/manager OR teacher OR student enrolled)
@courses_router.get("/{course_id}", response_model=CourseOut)
def get_course_detail(course_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    course = db.query(Course).options(joinedload(Course.students).joinedload(StudentCourse.student)).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # If student requests detail, ensure either public info is allowed OR student is enrolled.
    if current_user.role == UserRole.student:
        enrolled = db.query(StudentCourse).filter(
            StudentCourse.course_id == course_id,
            StudentCourse.student_id == current_user.id
        ).first()
        if not enrolled:
            # If you prefer to allow students to view course details even if not enrolled, remove this block.
            raise HTTPException(status_code=403, detail="Siz bu kurs tafsilotlarini koʻrishga haqli emassiz")

    return CourseOut.from_orm(course)


# STUDENT enroll to course (student enrolls themself)
@courses_router.post("/{course_id}/enroll", response_model=UserResponse)
def enroll_course(course_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat studentlar kursga yozilishi mumkin")

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    exists = db.query(StudentCourse).filter(
        StudentCourse.course_id == course_id,
        StudentCourse.student_id == current_user.id
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Siz allaqachon bu kursga yozilgansiz")

    enrollment = StudentCourse(student_id=current_user.id, course_id=course_id)
    db.add(enrollment)

    # optional: set student's fee to course.price if you want automatic fee assign
    current_user.fee = course.price

    db.commit()
    db.refresh(current_user)
    return UserResponse.from_orm(current_user)


# GET teacher's courses (teacher only)
@courses_router.get("/teacher/my", response_model=List[CourseOut])
def teacher_my_courses(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.teacher:
        raise HTTPException(status_code=403, detail="Faqat teacherlar uchun")
    return db.query(Course).filter(Course.teacher_id == current_user.id).all()
