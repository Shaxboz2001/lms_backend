from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date
from .models import User, UserRole, Group, Attendance
from .dependencies import get_db, get_current_user
from .schemas import AttendanceResponse, AttendanceCreate

attend_router = APIRouter(
    prefix="/attendance",
    tags=["Attendance"]
)


# ------------------------------
# POST: Bitta kun uchun yo‘qlama qo‘shish
# ------------------------------
@attend_router.post("/", response_model=List[AttendanceResponse])
def create_attendance(
    group_id: int = Body(...),
    records: List[dict] = Body(...),
    date_: Optional[date] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.teacher, UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed to create attendance")

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    attendance_date = date_ or datetime.utcnow().date()

    existing = db.query(Attendance).filter(
        Attendance.group_id == group_id,
        Attendance.date == attendance_date
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Attendance for {attendance_date} already exists")

    attendance_list = []
    for record in records:
        student = db.query(User).filter(User.id == record["student_id"]).first()
        if not student:
            continue

        attendance_entry = Attendance(
            student_id=record["student_id"],
            teacher_id=current_user.id,
            group_id=group_id,
            date=attendance_date,
            status="present" if record["is_present"] else "absent",
            reason=record.get("reason", None)
        )
        db.add(attendance_entry)
        attendance_list.append(attendance_entry)

    db.commit()
    for att in attendance_list:
        db.refresh(att)

    return attendance_list


# ------------------------------
# PATCH: Sababni yangilash
# ------------------------------
@attend_router.patch("/reason")
def update_reason(
    student_id: int = Body(...),
    group_id: int = Body(...),
    date_value: str = Body(...),
    reason: str = Body(...),  # "sababli" | "sababsiz"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Only manager or admin can update reasons")

    attendance = db.query(Attendance).filter(
        Attendance.student_id == student_id,
        Attendance.group_id == group_id,
        Attendance.date == date_value
    ).first()

    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    attendance.reason = reason
    db.commit()
    db.refresh(attendance)
    return {"message": f"Reason updated to {reason}"}


# ------------------------------
# GET: Oy bo‘yicha hisobot
# ------------------------------
@attend_router.get("/report/{group_id}")
def get_group_report(
    group_id: int,
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    today = datetime.utcnow()
    month = month or today.month
    year = today.year

    first_day = date(year, month, 1)
    last_day = today if month == today.month else date(year, month, 28)

    students = group.students

    attendances = db.query(Attendance).filter(
        Attendance.group_id == group_id,
        Attendance.date >= first_day,
        Attendance.date <= last_day
    ).order_by(Attendance.date.asc()).all()

    if not attendances:
        return {"day_list": [], "rows": [], "message": "Bu oyda dars mavjud emas"}

    day_list = sorted(list({a.date for a in attendances}))

    rows = []
    for s in students:
        row = {"fullname": s.full_name}
        for d in day_list:
            att = next((a for a in attendances if a.student_id == s.id and a.date == d), None)
            if att:
                if att.status == "present":
                    row[d.strftime("%d.%m.%Y")] = "✅"
                elif att.reason == "sababli":
                    row[d.strftime("%d.%m.%Y")] = "🟡"
                else:
                    row[d.strftime("%d.%m.%Y")] = "❌"
            else:
                row[d.strftime("%d.%m.%Y")] = "-"
        rows.append(row)

    return {
        "day_list": [d.strftime("%d.%m.%Y") for d in day_list],
        "rows": rows
    }