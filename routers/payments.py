# routers/payments.py
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List, Optional
from datetime import date, datetime

from .dependencies import get_db, get_current_user
from .models import User, UserRole, Payment, Group, PaymentStatus  # sizning mavjud modellaringiz
from .schemas import PaymentResponse  # agar bor bo'lsa

payments_router = APIRouter(prefix="/payments", tags=["Payments"])


# ---------------------------
# GET all payments (with role-based access)
# ---------------------------
@payments_router.get("/", response_model=List[PaymentResponse])
def get_payments(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == UserRole.student:
        payments = db.query(Payment).filter(Payment.student_id == current_user.id).all()
    elif current_user.role == UserRole.teacher:
        group_ids = [g.id for g in getattr(current_user, "groups_as_teacher", [])]
        payments = db.query(Payment).filter(
            (Payment.teacher_id == current_user.id) | (Payment.group_id.in_(group_ids))
        ).all()
    elif current_user.role in [UserRole.manager, UserRole.admin]:
        payments = db.query(Payment).all()
    else:
        payments = []

    for p in payments:
        p.is_overdue = bool(p.due_date and p.due_date < date.today() and p.status != "paid")

    return payments


# ---------------------------
# CREATE payment manually (admin/manager)
# ---------------------------
@payments_router.post("/", response_model=PaymentResponse)
def create_payment(
    amount: float = Body(..., gt=0),
    description: Optional[str] = Body(None),
    student_id: Optional[int] = Body(None),
    group_id: Optional[int] = Body(None),
    month: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar to‘lov qo‘sha olmaydi.")
    if not student_id:
        raise HTTPException(status_code=400, detail="O‘quvchi ID kiritilmadi.")
    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    # agar group_id yo'q bo'lsa student.group_id dan olish
    group = None
    if not group_id:
        if student.group_id:
            group = db.query(Group).filter(Group.id == student.group_id).first()
            if not group:
                raise HTTPException(status_code=400, detail="O‘quvchiga biriktirilgan guruh topilmadi.")
            group_id = group.id
        else:
            raise HTTPException(status_code=400, detail="Guruh aniqlanmadi va o‘quvchiga biriktirilmagan.")
    else:
        group = db.query(Group).filter(Group.id == group_id).first()

    if not month:
        month = date.today().strftime("%Y-%m")

    course_price = group.course.price if (group and getattr(group, "course", None)) else 0
    # status avtomatik: agar to‘langan >= course_price => paid, agar < => partial
    status = "paid" if amount >= course_price and course_price > 0 else ("partial" if amount > 0 else "unpaid")
    debt_amount = max(course_price - amount, 0) if course_price else 0

    payment = Payment(
        amount=amount,
        description=description or (group.course.title if group and getattr(group, "course", None) else "To'lov"),
        student_id=student_id,
        group_id=group_id,
        month=month,
        status=status,
        debt_amount=debt_amount,
        created_at=datetime.now()
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# ---------------------------
# GENERATE monthly unpaid debts (simple)
# ---------------------------
@payments_router.post("/generate-debts")
def generate_monthly_debts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin generatsiya qilishi mumkin.")
    today = date.today()
    current_month = today.strftime("%Y-%m")
    created_count = 0
    groups = db.query(Group).all()
    for group in groups:
        course_price = group.course.price if group and getattr(group, "course", None) else 0
        students = db.query(User).filter(User.group_id == group.id, User.role == UserRole.student).all()
        for student in students:
            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == current_month
            ).first()
            if not existing:
                payment = Payment(
                    amount=0,
                    description=f"{current_month} uchun avtomatik qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status="unpaid" if course_price > 0 else "paid",
                    debt_amount=course_price,
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                )
                db.add(payment)
                created_count += 1
    db.commit()
    return {"message": f"{created_count} ta yangi qarz yozildi", "month": current_month}


# ---------------------------
# MARK as paid (partial/full)
# ---------------------------
@payments_router.put("/mark-paid/{payment_id}")
def mark_payment_as_paid(payment_id: int, amount: float = Body(..., gt=0), db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Sizda ruxsat yo‘q.")
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To‘lov topilmadi.")
    course_price = payment.group.course.price if payment.group and getattr(payment.group, "course", None) else 0
    payment.amount = (payment.amount or 0) + amount
    remaining = course_price - payment.amount if course_price else 0
    if remaining <= 0:
        payment.status = "paid"
        payment.debt_amount = 0
    else:
        payment.status = "partial"
        payment.debt_amount = remaining
    payment.paid_at = datetime.now()
    db.commit()
    db.refresh(payment)
    return {"message": "To‘lov yangilandi ✅", "payment": payment}


# ---------------------------
# GET student history (admin/manager or self)
# ---------------------------
@payments_router.get("/student/{student_id}/history")
def get_student_payment_history(student_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q!")
    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi")
    payments = db.query(Payment).filter(Payment.student_id == student_id).order_by(Payment.month.desc()).all()
    history = []
    total_paid = 0
    total_debt = 0
    for p in payments:
        course_name = p.group.course.title if p.group and getattr(p.group, "course", None) else None
        group_name = p.group.name if p.group else None
        total_paid += p.amount or 0
        total_debt += p.debt_amount or 0
        history.append({
            "month": p.month,
            "course_name": course_name,
            "group_name": group_name,
            "amount": p.amount or 0,
            "debt_amount": p.debt_amount or 0,
            "status": p.status,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "is_overdue": bool(p.due_date and p.due_date < date.today() and p.status != "paid"),
        })
    return {
        "student_id": student.id,
        "student_name": student.full_name or student.username,
        "total_paid": total_paid,
        "total_debt": total_debt,
        "history": history,
    }

class CalculateMonthPayload(BaseModel):
    month: Optional[str] = None
# ---------------------------
# CALCULATE monthly payments from attendance + balance
# ---------------------------
@payments_router.post("/calculate-monthly")
def calculate_monthly_payments(
    payload: CalculateMonthPayload = Body(...),   # <-- endi JSON: { "month": "2025-10" } qabul qiladi
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Har bir guruh uchun oylik to‘lovni attendance va balans asosida hisoblaydi.
    Sababli/sababsiz darslar manager tomonidan belgilanadi.
    """
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin hisoblay oladi.")

    today = date.today()
    current_month = payload.month or today.strftime("%Y-%m")
    groups = db.query(Group).all()
    created, updated = 0, 0

    for group in groups:
        # course va price mavjudligini tekshirish
        course_price = group.course.price if getattr(group, "course", None) else 0
        lessons_count = 12  # agar kurs modelida alohida `lessons_count` bo'lsa, undan foydalaning
        if not course_price or lessons_count <= 0:
            continue

        students = db.query(User).filter(User.group_id == group.id, User.role == UserRole.student).all()

        for student in students:
            # === 1) Attendance yozuvlari (raw SQL orqali) ===
            # SQLda strftime ishlatsa, bu SQLite uchun to'g'ri. Agar siz boshqa DB (Postgres) ishlatsangiz,
            # date funktsiyasini moslashtirish kerak bo'ladi (EXTRACT/TO_CHAR).
            attendance_records = db.execute(
                text(
                    """
                    SELECT date, status, reason
                    FROM attendance
                    WHERE student_id = :sid
                      AND group_id = :gid
                      AND strftime('%Y-%m', date) = :month
                    """
                ),
                {"sid": student.id, "gid": group.id, "month": current_month}
            ).fetchall()

            # attendance_records qatorlari RowProxy bo'ladi -> a['status'] yoki a.status ishlaydi
            attended_lessons = sum(1 for a in attendance_records if (a['status'] if 'status' in a.keys() else a.status) == "present")
            absent_sababli = sum(1 for a in attendance_records if (a.get('status') if hasattr(a, 'get') else (a['status'] if 'status' in a.keys() else a.status)) == "absent" and (a.get('reason') if hasattr(a, 'get') else (a['reason'] if 'reason' in a.keys() else a.reason)) == "sababli")
            absent_sababsiz = sum(1 for a in attendance_records if (a.get('status') if hasattr(a, 'get') else (a['status'] if 'status' in a.keys() else a.status)) == "absent" and (a.get('reason') if hasattr(a, 'get') else (a['reason'] if 'reason' in a.keys() else a.reason)) == "sababsiz")

            total_lessons = attended_lessons + absent_sababli + absent_sababsiz
            per_lesson_price = course_price / lessons_count

            # === 2) O‘tgan oy balansini olish ===
            previous_payment = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id
            ).order_by(Payment.month.desc()).first()

            previous_balance = 0.0
            if previous_payment:
                # previous_payment.debt_amount — qolgan qarz (agar >0)
                # previous_payment.amount — to'lov jami
                # status ga qarab balans aniqlanadi (oldingi kodga mos)
                if previous_payment.status == PaymentStatus.unpaid or previous_payment.status == PaymentStatus.partial:
                    previous_balance = float(previous_payment.debt_amount or 0.0)
                elif previous_payment.status == PaymentStatus.paid:
                    # agar ortiqcha to'lov bo'lsa (negativ balans) — agar siz negative debit saqlayotgan bo'lsangiz
                    previous_balance = -float(previous_payment.amount or 0.0) if (previous_payment.amount or 0) > 0 else 0.0

            # === 3) Bu oy uchun qarzni hisoblash ===
            if total_lessons == 0:
                monthly_due = 0.0
            else:
                # sizning talabga ko'ra: sababsiz qoldirilgan darslar ham qarzga kiritiladi
                effective_lessons = attended_lessons + absent_sababsiz
                # modelizda kurs uchun oy davomida to'liq narx ishlatiladi:
                monthly_due = round(per_lesson_price * lessons_count, 2)

            # === 4) Umumiy qarzni hisoblash (oldingi balans bilan) ===
            if previous_balance > 0:
                final_debt = monthly_due + previous_balance
            elif previous_balance < 0:
                final_debt = max(0, monthly_due + previous_balance)
            else:
                final_debt = monthly_due

            # === 5) To‘lov yozuvi yangilash yoki yaratish ===
            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == current_month
            ).first()

            if existing:
                existing.debt_amount = float(final_debt)
                existing.status = PaymentStatus.paid if final_debt <= 0 else PaymentStatus.partial if final_debt < course_price else PaymentStatus.unpaid
                updated += 1
            else:
                new_payment = Payment(
                    amount=0.0,
                    description=f"{current_month} uchun hisoblangan qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status=PaymentStatus.unpaid if final_debt > 0 else PaymentStatus.paid,
                    debt_amount=float(final_debt),
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                )
                db.add(new_payment)
                created += 1

    db.commit()
    return {
        "message": f"✅ Hisoblash yakunlandi: {created} yangi, {updated} yangilandi.",
        "month": current_month
    }



# ---------------------------
# Update attendance reason (manager)
# ---------------------------
@payments_router.post("/attendance/reason")
def update_attendance_reason(student_id: int = Body(...), date_value: str = Body(...), group_id: int = Body(...),
                             reason: str = Body(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager o‘zgartira oladi.")
    att = db.execute(
        text("""
            SELECT * FROM attendance
            WHERE student_id = :sid AND group_id = :gid AND date = :dt
        """),
        {"sid": student_id, "gid": group_id, "dt": date_value}
    ).fetchone()
    if not att:
        raise HTTPException(status_code=404, detail="Dars topilmadi.")
    db.execute(
        text("""
            UPDATE attendance
            SET reason = :reason
            WHERE student_id = :sid AND group_id = :gid AND date = :dt
        """),
        {"reason": reason, "sid": student_id, "gid": group_id, "dt": date_value}
    )
    db.commit()
    return {"message": f"Dars uchun sabab yangilandi: {reason}"}
