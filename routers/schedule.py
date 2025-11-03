from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from .dependencies import get_db
from .auth import get_current_user
from .models import User, UserRole, Schedule, Group
from .schemas import ScheduleResponse, ScheduleCreate, ScheduleUpdate, ScheduleBase

schedules_router = APIRouter(prefix="/schedules", tags=["Schedules"])

# ✅ 1. Barcha jadvalni olish
@schedules_router.get("/", response_model=List[ScheduleResponse])
def get_all_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    schedules = db.query(Schedule).all()
    return schedules


# ✅ 2. Teacher o‘z jadvalini ko‘rish
@schedules_router.get("/my", response_model=List[ScheduleResponse])
def get_my_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.teacher:
        raise HTTPException(status_code=403, detail="Faqat ustozlar uchun")
    return db.query(Schedule).filter(Schedule.teacher_id == current_user.id).all()

# ✅ 3. Student o‘z guruhining jadvalini ko‘rish
@schedules_router.get("/student", response_model=List[ScheduleResponse])
def get_student_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # faqat studentlar uchun
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat o‘quvchilar uchun")

    # student qaysi guruhlarga a'zo — group_students orqali
    group_ids = [g.id for g in current_user.groups_as_student]

    if not group_ids:
        return []  # hech bir guruhga a'zo bo‘lmasa, bo‘sh qaytaradi

    # faqat shu guruhlarning jadvali chiqadi
    schedules = (
        db.query(Schedule)
        .filter(Schedule.group_id.in_(group_ids))
        .order_by(Schedule.day_of_week)
        .all()
    )
    return schedules


# ✅ 4. Yangi jadval yaratish
@schedules_router.post("/", response_model=ScheduleResponse)
def create_schedule(
    req: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 👮‍♂️ Ruxsat tekshiruvi
    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")

    # 👇 Guruhni topamiz
    group = db.query(Group).filter(Group.id == req.group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi")

    # 👇 Teacher bo‘lsa — faqat o‘z guruhida dars yaratadi
    if current_user.role == UserRole.teacher:
        if group.teacher_id != current_user.id:
            raise HTTPException(status_code=403, detail="Bu guruh sizniki emas")
        teacher_id = current_user.id
    else:
        # Admin yoki Manager — guruhdan teacher_id oladi
        teacher_id = group.teacher_id
        if not teacher_id:
            raise HTTPException(status_code=400, detail="Guruhga ustoz biriktirilmagan")

    # 👇 Yangi jadvalni yaratamiz
    new_item = Schedule(
        group_id=req.group_id,
        teacher_id=teacher_id,
        day_of_week=req.day_of_week,
        start_time=req.start_time,
        end_time=req.end_time,
        room=req.room,
        created_at=datetime.utcnow(),
    )

    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


# ✅ 5. Jadvalni tahrirlash
@schedules_router.put("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: int,
    req: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Jadval topilmadi")

    # Teacher faqat o‘z darsini tahrirlaydi
    if current_user.role == UserRole.teacher and schedule.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Siz bu jadvalni o‘zgartira olmaysiz")

    for key, value in req.dict(exclude_unset=True).items():
        setattr(schedule, key, value)

    schedule.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(schedule)
    return schedule


# ✅ 6. Jadvalni o‘chirish
@schedules_router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Jadval topilmadi")

    if current_user.role == UserRole.teacher and schedule.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Siz faqat o‘z darslaringizni o‘chira olasiz")

    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")

    db.delete(schedule)
    db.commit()
    return {"message": "Jadval o‘chirildi"}
