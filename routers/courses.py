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

# GET student's enrolled courses
@courses_router.get("/student/{student_id}", response_model=List[CourseOut])
def get_student_courses(student_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Faqat admin, manager yoki o‘sha studentning o‘zi kirishi mumkin
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Siz bu talabaning kurslarini ko‘ra olmaysiz")

    courses = (
        db.query(Course)
        .join(StudentCourse, Course.id == StudentCourse.course_id)
        .filter(StudentCourse.student_id == student_id)
        .options(joinedload(Course.teacher))
        .all()
    )

    return courses

# GET teacher's courses by ID (admin, manager yoki teacher o‘zi ko‘rsa bo‘ladi)
@courses_router.get("/teacher/{teacher_id}", response_model=List[CourseOut])
def get_teacher_courses(teacher_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Faqat admin, manager yoki o‘sha teacherning o‘zi ko‘ra oladi
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != teacher_id:
        raise HTTPException(status_code=403, detail="Siz bu o‘qituvchining kurslarini ko‘ra olmaysiz")

    courses = (
        db.query(Course)
        .filter(Course.teacher_id == teacher_id)
        .options(joinedload(Course.students))
        .all()
    )

    return courses

@courses_router.delete("/{course_id}")
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Faqat admin yoki manager o‘chira oladi
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Faqat admin yoki manager o‘chira oladi")

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        # Importlar kerak bo‘lishi mumkin
        from .models import Group, StudentCourse, Payment

        # 1️⃣ StudentCourse (many-to-many jadval) yozuvlarini o‘chirish
        db.query(StudentCourse).filter(StudentCourse.course_id == course_id).delete(synchronize_session=False)

        # 2️⃣ Group jadvalidagi bog‘liqliklarni NULL qilish (agar groupda course_id mavjud bo‘lsa)
        db.query(Group).filter(Group.course_id == course_id).update({Group.course_id: None})

        # 3️⃣ Payment jadvalida course_id mavjud bo‘lsa NULL qilish
        if hasattr(Payment, "course_id"):
            db.query(Payment).filter(Payment.course_id == course_id).update({Payment.course_id: None})

        # 4️⃣ O‘zi Course ni o‘chirish
        db.delete(course)
        db.commit()

        return {"message": f"✅ Course '{course.title}' deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not delete course: {str(e)}")
