from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .dependencies import get_db, get_current_user  # JWT bilan get_current_user
from .schemas import GroupResponse, GroupCreate, UserResponse
from .models import Group, User, UserRole

groups_router = APIRouter(
    prefix="/groups",
    tags=["Groups"]
)

# ------------------------------
# GET all groups
# ------------------------------
@groups_router.get("/", response_model=List[GroupResponse])
def get_groups(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Role ga qarab guruhlarni olish
    if current_user.role in [UserRole.admin, UserRole.manager]:
        groups = db.query(Group).all()
    elif current_user.role == UserRole.teacher:
        groups = current_user.groups_as_teacher
    elif current_user.role == UserRole.student:
        groups = current_user.groups_as_student
    else:
        groups = []

    # Pydantic schema ga o‘tkazish
    response = []
    for group in groups:
        response.append(
            GroupResponse(
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
@groups_router.post("/", response_model=GroupResponse)
def create_group(
        group: GroupCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Faqat admin va manager yangi guruh qo‘sha oladi
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to create groups")

    new_group = Group(
        name=group.name,
        description=group.description
    )

    # Student va teacher larni qo‘shish
    if group.student_ids:
        students = db.query(User).filter(
            User.id.in_(group.student_ids),
            User.role == UserRole.student
        ).all()
        new_group.students = students

    if group.teacher_ids:
        teachers = db.query(User).filter(
            User.id.in_(group.teacher_ids),
            User.role == UserRole.teacher
        ).all()
        new_group.teachers = teachers

    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    return GroupResponse(
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
@groups_router.get("/{group_id}/students/", response_model=List[UserResponse])
def get_group_students(
        group_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Role bilan tekshirish: teacher faqat o‘z guruhidagi o‘quvchilarni oladi
    if current_user.role == UserRole.teacher and current_user not in group.teachers:
        raise HTTPException(status_code=403, detail="Not allowed to view students in this group")
    elif current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Students cannot view other students")

    # O‘quvchilar ro‘yxatini qaytarish
    return [UserResponse.from_orm(student) for student in group.students]

# ------------------------------
# DELETE group
# ------------------------------
@groups_router.delete("/{group_id}")
def delete_group(
        group_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # Faqat admin va manager o‘chira oladi
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="❌ Sizda o‘chirish huquqi yo‘q")

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="❌ Guruh topilmadi")

    # Guruhni o‘chirish
    db.delete(group)
    db.commit()
    return {"message": f"✅ Guruh '{group.name}' muvaffaqiyatli o‘chirildi"}
