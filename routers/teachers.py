from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..dependencies import get_db
from ..dependencies import get_current_user

router = APIRouter(
    prefix="/teacher",
    tags=["teacher"]
)


@router.get("/groups/", response_model=List[schemas.GroupResponse])
def get_teacher_groups(
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Faqat teacherlar uchun")

    groups = db.query(models.Group).join(models.Group.teachers) \
        .filter(models.User.id == current_user.id).all()
    return groups
