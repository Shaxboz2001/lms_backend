from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from typing import List

from .dependencies import get_db
from .models import Group, Course, User, UserRole, StudentCourse, group_students
from .schemas import GroupCreate, GroupUpdate, GroupResponse, UserResponse

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

    # 2️⃣ O‘qituvchini tekshirish (agar kelsa)
    teacher = None
    if getattr(group, "teacher_id", None):
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

    # 4️⃣ Talabalarni olish
    students = []
    if getattr(group, "student_ids", None):
        students = db.query(User).filter(
            User.id.in_(group.student_ids),
            User.role == UserRole.student
        ).all()

        if not students:
            raise HTTPException(status_code=404, detail="No valid students found")

    # 5️⃣ Guruhni saqlash
    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    # 6️⃣ Talabalarni guruhga biriktirish
    if students:
        new_group.students = students
        for student in students:
            # StudentCourse yozuvini tekshirish
            exists = db.query(StudentCourse).filter(
                StudentCourse.student_id == student.id,
                StudentCourse.course_id == course.id
            ).first()
            if not exists:
                db.add(StudentCourse(student_id=student.id, course_id=course.id))

            # group_id yangilash
            student.group_id = new_group.id

            # 🟢 Statusni "studying" qilish
            if hasattr(student, "status"):
                student.status = "studying"

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
        course = db.query(Course).filter(Course.id == updated.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        group.course_id = updated.course_id

    # Teacher yangilash
    if getattr(updated, "teacher_id", None) is not None:
        if updated.teacher_id is None:
            group.teacher_id = None
        else:
            teacher = db.query(User).filter(
                User.id == updated.teacher_id,
                User.role == UserRole.teacher
            ).first()
            if not teacher:
                raise HTTPException(status_code=404, detail="Teacher not found")
            group.teacher_id = teacher.id

    # Talabalarni yangilash
    if updated.student_ids is not None:
        if len(updated.student_ids) == 0:
            group.students = []
        else:
            students = db.query(User).filter(
                User.id.in_(updated.student_ids),
                User.role == UserRole.student
            ).all()
            if not students:
                raise HTTPException(status_code=404, detail="No valid students found")
            group.students = students

            # Kursga yozilganligini tekshiramiz
            if group.course_id:
                for student in students:
                    exists = db.query(StudentCourse).filter(
                        StudentCourse.student_id == student.id,
                        StudentCourse.course_id == group.course_id
                    ).first()
                    if not exists:
                        db.add(StudentCourse(student_id=student.id, course_id=group.course_id))
                    student.group_id = group.id

                    # 🟢 Yangi o‘quvchi qo‘shilganda status = "studying"
                    if hasattr(student, "status"):
                        student.status = "studying"

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

    try:
        db.execute(group_students.delete().where(group_students.c.group_id == group_id))
        if "group_id" in User.__table__.c:
            db.execute(
                User.__table__.update().where(User.__table__.c.group_id == group_id).values(group_id=None)
            )
        db.delete(group)
        db.commit()
        return {"message": "Group deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not delete group: {str(e)}")


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


@groups_router.get("/students/{course_id}", response_model=List[UserResponse])
def get_students_for_course(course_id: int, db: Session = Depends(get_db)):
    students = (
        db.query(User)
        .join(StudentCourse, StudentCourse.student_id == User.id)
        .filter(StudentCourse.course_id == course_id, User.role == UserRole.student)
        .all()
    )
    return students


# ------------------------------
# GET students by group
# ------------------------------
@groups_router.get("/{group_id}/students/", response_model=List[UserResponse])
def get_students_by_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    course_id = group.course_id

    students = (
        db.query(User)
        .join(StudentCourse, StudentCourse.student_id == User.id)
        .filter(
            User.role == UserRole.student,
            StudentCourse.course_id == course_id
        )
        .all()
    )
    return students
