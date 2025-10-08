from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..dependencies import get_db, get_current_user  # JWT bilan get_current_user

router = APIRouter(
    prefix="/groups",
    tags=["Groups"]
)

# ------------------------------
# GET all groups
# ------------------------------
@router.get("/", response_model=List[schemas.GroupResponse])
def get_groups(
        db: Session = Depends(get_db),
        current_user: models.User = Depends(get_current_user)
):
    # Role ga qarab guruhlarni olish
    if current_user.role in [models.UserRole.admin, models.UserRole.manager]:
        groups = db.query(models.Group).all()
    elif current_user.role == models.UserRole.teacher:
        groups = current_user.groups_as_teacher
    elif current_user.role == models.UserRole.student:
        groups = current_user.groups_as_student
    else:
        groups = []

    # Pydantic schema ga o‘tkazish
    response = []
    for group in groups:
        response.append(
            schemas.GroupResponse(
                id=group.id,
                name=group.name,
                description=group.description,
                created_at=group.created_at,
                student_ids=[s.id for s in group.students],
                teacher_ids=[t.id for t in group.teachers]
            )
        )
    return response


# ------------------------------
# CREATE group
# ------------------------------
@router.post("/", response_model=schemas.GroupResponse)
def create_group(
        group: schemas.GroupCreate,
        db: Session = Depends(get_db),
        current_user: models.User = Depends(get_current_user)
):
    # Faqat admin va manager yangi guruh qo‘sha oladi
    if current_user.role not in [models.UserRole.admin, models.UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to create groups")

    new_group = models.Group(
        name=group.name,
        description=group.description
    )

    # Student va teacher larni qo‘shish
    if group.student_ids:
        students = db.query(models.User).filter(
            models.User.id.in_(group.student_ids),
            models.User.role == models.UserRole.student
        ).all()
        new_group.students = students

    if group.teacher_ids:
        teachers = db.query(models.User).filter(
            models.User.id.in_(group.teacher_ids),
            models.User.role == models.UserRole.teacher
        ).all()
        new_group.teachers = teachers

    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    return schemas.GroupResponse(
        id=new_group.id,
        name=new_group.name,
        description=new_group.description,
        created_at=new_group.created_at,
        student_ids=[s.id for s in new_group.students],
        teacher_ids=[t.id for t in new_group.teachers]
    )

# ------------------------------
# GET all students in a group
# ------------------------------
@router.get("/{group_id}/students/", response_model=List[schemas.UserResponse])
def get_group_students(
        group_id: int,
        db: Session = Depends(get_db),
        current_user: models.User = Depends(get_current_user)
):
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Role bilan tekshirish: teacher faqat o‘z guruhidagi o‘quvchilarni oladi
    if current_user.role == models.UserRole.teacher and current_user not in group.teachers:
        raise HTTPException(status_code=403, detail="Not allowed to view students in this group")
    elif current_user.role == models.UserRole.student:
        raise HTTPException(status_code=403, detail="Students cannot view other students")

    # O‘quvchilar ro‘yxatini qaytarish
    return [schemas.UserResponse.from_orm(student) for student in group.students]
