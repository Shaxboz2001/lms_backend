from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from .dependencies import get_db
from .models import Group, Course, User, UserRole, StudentCourse, group_students
from .schemas import GroupCreate, GroupUpdate, GroupResponse, UserResponse
from typing import List

groups_router = APIRouter(prefix="/groups", tags=["Groups"])


# ------------------------------
# CREATE group
# ------------------------------
@groups_router.post("/", response_model=GroupResponse)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    # 1️⃣ Kursni tekshirish
    course = db.query(Course).filter(Course.id == group.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # 2️⃣ O‘qituvchini tekshirish
    teacher = None
    if group.teacher_id:
        teacher = db.query(User).filter(
            User.id == group.teacher_id,
            User.role == UserRole.teacher
        ).first()
        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher not found")

    # 3️⃣ Yangi guruh obyektini yaratish
    new_group = Group(
        name=group.name,
        description=group.description,
        course_id=group.course_id,
        teacher_id=group.teacher_id
    )

    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    # 4️⃣ Talabalarni bog‘lash (agar mavjud bo‘lsa)
    if getattr(group, "student_ids", None):
        students = db.query(User).filter(
            User.id.in_(group.student_ids),
            User.role == UserRole.student
        ).all()

        if not students:
            raise HTTPException(status_code=404, detail="No valid students found")

        # Har bir studentni shu group va kursga bog‘laymiz
        for student in students:
            student.group_id = new_group.id

            # StudentCourse jadvaliga ham yozamiz
            enrollment_exists = db.query(StudentCourse).filter(
                StudentCourse.student_id == student.id,
                StudentCourse.course_id == course.id
            ).first()

            if not enrollment_exists:
                enrollment = StudentCourse(
                    student_id=student.id,
                    course_id=course.id
                )
                db.add(enrollment)

        db.commit()

    db.refresh(new_group)
    return new_group



# ------------------------------
# GET all groups
# ------------------------------
@groups_router.get("/", response_model=List[GroupResponse])
def get_groups(db: Session = Depends(get_db)):
    groups = db.query(Group).options(
        joinedload(Group.course),
        joinedload(Group.teacher),
        joinedload(Group.students),
    ).all()
    return groups


# ------------------------------
# UPDATE group
# ------------------------------
@groups_router.put("/{group_id}", response_model=GroupResponse)
def update_group(group_id: int, updated: GroupUpdate, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    if updated.name is not None:
        group.name = updated.name
    if updated.description is not None:
        group.description = updated.description
    if updated.course_id is not None:
        group.course_id = updated.course_id

    # O‘qituvchilarni yangilash
    if updated.teacher_id:
        teacher = db.query(User).filter(
            User.id.in_([updated.teacher_id]), User.role == UserRole.teacher
        ).all()
        group.teacher = teacher

    # Talabalarni yangilash
    if updated.student_ids is not None:
        students = db.query(User).filter(
            User.id.in_(updated.student_ids), User.role == UserRole.student
        ).all()
        group.students = students

    db.commit()
    db.refresh(group)
    return group


# ------------------------------
# DELETE group
# ------------------------------
@groups_router.delete("/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    db.delete(group)
    db.commit()
    return {"message": "Group deleted successfully"}


# ------------------------------
# GET courses, teachers, students
# ------------------------------
@groups_router.get("/courses")
def get_courses(db: Session = Depends(get_db)):
    return db.query(Course).all()


@groups_router.get("/teachers/{course_id}")
def get_teachers_for_course(course_id: int, db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    teacher = db.query(User).filter(User.id == course.teacher_id).first()
    return [teacher] if teacher else []


@groups_router.get("/students/{course_id}")
def get_students_for_course(course_id: int, db: Session = Depends(get_db)):
    students = (
        db.query(User)
        .filter(User.course_id == course_id, User.role == UserRole.student)
        .all()
    )
    return students

# routers/groups.py
@groups_router.get("/{group_id}/students/", response_model=List[UserResponse])
def get_students_by_group(group_id: int, db: Session = Depends(get_db)):
    # 1️⃣ Guruh mavjudligini tekshirish
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # 2️⃣ group_students jadvalidan student_id larni olish
    stmt = select(group_students.c.student_id).where(group_students.c.group_id == group_id)
    student_ids = [row[0] for row in db.execute(stmt).all()]

    if not student_ids:
        return []  # Guruhda student yo‘q

    # 3️⃣ Users jadvalidan studentlarni olish
    students = db.query(User).filter(User.id.in_(student_ids), User.role == UserRole.student).all()
    return students

