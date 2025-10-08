from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date
from .. import models, schemas
from ..dependencies import get_db, get_current_user

router = APIRouter(
    prefix="/attendance",
    tags=["Attendance"]
)

# ------------------------------
# POST: Bitta kun uchun yo‘qlama qo‘shish
# ------------------------------
@router.post("/", response_model=List[schemas.AttendanceResponse])
def create_attendance(
    group_id: int = Body(...),
    records: List[schemas.AttendanceCreate] = Body(...),
    date_: Optional[date] = Body(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in [models.UserRole.teacher, models.UserRole.admin, models.UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to create attendance")

    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    if current_user.role == models.UserRole.teacher and current_user not in group.teachers:
        raise HTTPException(status_code=403, detail="You can only add attendance for your groups")

    attendance_date = date_ or datetime.utcnow().date()

    # Shu kunga oldin yozilgan attendance mavjudligini tekshirish
    existing = db.query(models.Attendance).filter(
        models.Attendance.group_id == group_id,
        models.Attendance.date == attendance_date
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Attendance for {attendance_date} already exists")

    attendance_list = []
    for record in records:
        student = db.query(models.User).filter(models.User.id == record.student_id).first()
        if not student:
            continue

        attendance_entry = models.Attendance(
            student_id=record.student_id,
            teacher_id=current_user.id,
            group_id=group_id,
            date=attendance_date,
            status="present" if record.is_present else "absent"
        )
        db.add(attendance_entry)
        attendance_list.append(attendance_entry)

    db.commit()
    for att in attendance_list:
        db.refresh(att)

    return attendance_list


# ------------------------------
# GET: Oy bo‘yicha hisobot (faqat saqlangan kunlar)
# ------------------------------
@router.get("/report/{group_id}")
def get_group_report(
    group_id: int,
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    if current_user.role == models.UserRole.teacher and current_user not in group.teachers:
        raise HTTPException(status_code=403, detail="Not allowed to view this group's attendance")

    today = datetime.utcnow()
    month = month or today.month
    year = today.year

    # Oy boshidan hozirgi kungacha yoki tanlangan oy oxirigacha
    first_day = date(year, month, 1)
    last_day = today if month == today.month else date(year, month, 28)

    # O‘quvchilar
    students = group.students

    # Ushbu oy uchun attendance
    attendances = db.query(models.Attendance).filter(
        models.Attendance.group_id == group_id,
        models.Attendance.date >= first_day,
        models.Attendance.date <= last_day
    ).order_by(models.Attendance.date.asc()).all()

    if not attendances:
        return {"day_list": [], "rows": [], "message": "Bu oyda dars mavjud emas"}

    # Faol attendance saqlangan kunlar ro‘yxati
    day_list = sorted(list({a.date for a in attendances}))

    rows = []
    for s in students:
        row = {"fullname": s.full_name}
        for d in day_list:
            att = next((a for a in attendances if a.student_id == s.id and a.date == d), None)
            row[d.strftime("%d.%m.%Y")] = "Bor" if att and att.status=="present" else "Yo'q"
        rows.append(row)

    return {
        "day_list": [d.strftime("%d.%m.%Y") for d in day_list],
        "rows": rows
    }
