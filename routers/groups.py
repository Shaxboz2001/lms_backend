from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
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

    # 3️⃣ Yangi guruh obyektini yaratish (teacher_id bilan ham ishlaydi)
    new_group = Group(
        name=group.name,
        description=group.description,
        course_id=group.course_id,
        teacher_id=group.teacher_id  # foreign key sifatida saqlanadi
    )

    # 4️⃣ Agar talabalar kelgan bo'lsa, ularni olish (validatsiya)
    students = []
    if getattr(group, "student_ids", None):
        students = db.query(User).filter(
            User.id.in_(group.student_ids),
            User.role == UserRole.student
        ).all()

        if not students:
            raise HTTPException(status_code=404, detail="No valid students found")

    # 5️⃣ Guruh va bog'lanmalarni saqlash: avval group qo'shamiz,
    # so'ng relationshiplar/esenrolllarni qo'shamiz
    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    # 6️⃣ Agar teacher obyekt mavjud bo'lsa, (relationship orqali) biriktirish — bu ixtiyoriy,
    # lekin teacher_id allaqachon set qilingan. Agar xohlasangiz object ham biriktirish mumkin:
    if teacher:
        # teacher_id allaqachon to'g'ri, bu satr majburiy emas:
        new_group.teacher_id = teacher.id

    # 7️⃣ Talabalarni guruhga biriktirish va StudentCourse yozuvlarini qo'shish
    if students:
        # relationship orqali assign qilamiz
        new_group.students = students

        # Har bir student uchun StudentCourse (agar mavjud bo'lmasa) qo'shamiz:
        for student in students:
            exists = db.query(StudentCourse).filter(
                StudentCourse.student_id == student.id,
                StudentCourse.course_id == course.id
            ).first()
            if not exists:
                enrollment = StudentCourse(student_id=student.id, course_id=course.id)
                db.add(enrollment)

        # Va agar studentlar uchun group_id maydonini yangilash kerak bo'lsa:
        for student in students:
            student.group_id = new_group.id

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
        # agar course o'zgarsa, kurs mavjudligini tekshirish foydali
        course = db.query(Course).filter(Course.id == updated.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        group.course_id = updated.course_id

    # Teacher yangilash — yagona integer kutiladi
    if getattr(updated, "teacher_id", None) is not None:
        # agar null (None) yuborilsa, teacherni olib tashlash
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

    # Talabalarni yangilash (to'liq qayta o'rnatish)
    if updated.student_ids is not None:
        # agar bo'sh ro'yxat yuborilsa, students bo'sh qilinadi
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

            # kursga yozuvlar (StudentCourse) ham tekshiriladi/qo'shiladi
            if group.course_id:
                for student in students:
                    exists = db.query(StudentCourse).filter(
                        StudentCourse.student_id == student.id,
                        StudentCourse.course_id == group.course_id
                    ).first()
                    if not exists:
                        db.add(StudentCourse(student_id=student.id, course_id=group.course_id))
                    # va group_id maydonini yangilash
                    student.group_id = group.id

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

    # 1️⃣ Shu guruhdagi barcha foydalanuvchilarning group_id sini NULL qilamiz
    db.query(User).filter(User.group_id == group_id).update({User.group_id: None})

    # 2️⃣ Guruhni o‘chiramiz
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


# many-to-many asosida course ga yozilgan studentlarni olish
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
# GET students by group (using group_students junction table)
# ------------------------------
@groups_router.get("/{group_id}/students/", response_model=List[UserResponse])
def get_students_by_group(group_id: int, db: Session = Depends(get_db)):
    # 1️⃣ Guruhni topamiz
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # 2️⃣ Shu guruhga tegishli kursni aniqlaymiz
    course_id = group.course_id

    # 3️⃣ Many-to-many orqali o‘sha kursga yozilgan studentlarni olish
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

