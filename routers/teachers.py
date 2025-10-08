from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .dependencies import get_db
from .dependencies import get_current_user
from .schemas import GroupResponse
from .models import User, Group

teachers_router = APIRouter(
    prefix="/teacher",
    tags=["teacher"]
)


@teachers_router.get("/groups/", response_model=List[GroupResponse])
def get_teacher_groups(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Faqat teacherlar uchun")

    groups = db.query(Group).join(Group.teachers) \
        .filter(User.id == current_user.id).all()
    return groups
