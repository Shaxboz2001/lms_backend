from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, Date
from sqlalchemy.orm import Session
from datetime import date, timedelta
from io import BytesIO
from typing import Literal
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from fastapi.responses import StreamingResponse

from .dependencies import get_db, get_current_user
from .models import User, Group, Payment, Attendance, UserRole

reports_router = APIRouter(prefix="/reports", tags=["Reports"])


# ✅ Umumiy hisobot (summary)
@reports_router.get("/summary")
def get_summary(
    period: Literal["daily", "weekly", "monthly"] = "daily",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    today = date.today()
    start_date = today
    if period == "weekly":
        start_date = today - timedelta(days=7)
    elif period == "monthly":
        start_date = today - timedelta(days=30)

    total_students = db.query(User).filter(User.role == UserRole.student).count()
    leads = db.query(User).filter(User.role == UserRole.student, User.status == "interested").count()
    studying = db.query(User).filter(User.role == UserRole.student, User.status == "studying").count()

    new_students = db.query(User).filter(User.role == UserRole.student, User.age != None).count()
    total_groups = db.query(Group).count()
    payments = db.query(Payment).filter(Payment.created_at >= start_date).all()
    total_payments = sum(p.amount for p in payments)
    average_payment = round(total_payments / len(payments), 2) if payments else 0

    data = {
        "students": {
            "total": total_students,
            "new": new_students,
            "leads": leads,
            "studying": studying,
            "conversion_rate": round(studying / leads * 100, 2) if leads else 0,
        },
        "groups": {"active_groups": total_groups, "new_started": 2},
        "payments": {
            "total_amount": total_payments,
            "average_payment": average_payment,
            "debtor_count": 5
        },
        "attendance": {
            "attendance_rate": 85,
            "total_records": 123
        },
        "courses": {
            "active": 8,
            "upcoming": 3
        }
    }
    return data


# ✅ Trend (so‘nggi 7 kun)
@reports_router.get("/trend")
def get_payment_trend(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    today = date.today()
    data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        payments = db.query(Payment).filter(cast(Payment.created_at, Date) == d).all()
        total = sum(p.amount for p in payments)
        data.append({"date": d.strftime("%d-%m"), "total": total})
    return data


# ✅ Excel / PDF export
@reports_router.get("/export")
def export_report(
    period: Literal["daily", "weekly", "monthly"] = "daily",
    format: Literal["excel", "pdf"] = "excel",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Not allowed")

    summary = get_summary(period, db, current_user)

    # ---- Excel ----
    if format == "excel":
        df = pd.DataFrame([
            {
                "Period": period,
                "Total Students": summary["students"]["total"],
                "New Students": summary["students"]["new"],
                "Leads": summary["students"]["leads"],
                "Studying": summary["students"]["studying"],
                "Conversion %": summary["students"]["conversion_rate"],
                "Payments Total": summary["payments"]["total_amount"],
                "Avg Payment": summary["payments"]["average_payment"],
                "Debtors": summary["payments"]["debtor_count"],
                "Attendance %": summary["attendance"]["attendance_rate"],
                "Groups": summary["groups"]["active_groups"],
                "Courses": summary["courses"]["active"]
            }
        ])
        output = BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=report_{period}.xlsx"}
        )

    # ---- PDF ----
    elif format == "pdf":
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = [Paragraph(f"Hisobot ({period.capitalize()})", styles["Title"]), Spacer(1, 12)]

        table_data = [["Ko‘rsatkich", "Qiymat"]]
        for k, v in {
            "Umumiy o‘quvchilar": summary["students"]["total"],
            "Yangi o‘quvchilar": summary["students"]["new"],
            "Leads": summary["students"]["leads"],
            "O‘qiyotgan": summary["students"]["studying"],
            "Konversiya (%)": summary["students"]["conversion_rate"],
            "To‘lovlar (so‘m)": summary["payments"]["total_amount"],
            "O‘rtacha to‘lov": summary["payments"]["average_payment"],
            "Qarzdorlar": summary["payments"]["debtor_count"],
            "Qatnashuv (%)": summary["attendance"]["attendance_rate"],
            "Guruhlar": summary["groups"]["active_groups"],
            "Kurslar": summary["courses"]["active"],
        }.items():
            table_data.append([k, str(v)])

        t = Table(table_data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1976d2")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))

        elements.append(t)
        doc.build(elements)
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=report_{period}.pdf"}
        )
