from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from .. import models, schemas
from ..dependencies import get_db
from .auth import get_current_user

router = APIRouter(prefix="/tests", tags=["Tests"])


# ✅ Test yaratish (Teacher)
@router.post("/", response_model=schemas.TestResponse)
def create_test(test: schemas.TestCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.teacher:
        raise HTTPException(status_code=403, detail="Faqat teacher test yaratishi mumkin")

    db_test = models.Test(
        title=test.title,
        description=test.description,
        created_by=current_user.id,  # testni kim yaratgan
        group_id=test.group_id,
        created_at=datetime.utcnow()
    )
    db.add(db_test)
    db.commit()
    db.refresh(db_test)

    for q in test.questions:
        db_question = models.Question(
            test_id=db_test.id,
            text=q.text
        )
        db.add(db_question)
        db.commit()
        db.refresh(db_question)

        for opt in q.options:
            db_option = models.Option(
                question_id=db_question.id,
                text=opt.text,
                is_correct=int(opt.is_correct)
            )
            db.add(db_option)
        db.commit()

    return db_test


# ✅ Testlarni olish (Teacher yoki Student)
@router.get("/", response_model=List[schemas.TestResponse])
def get_my_tests(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role == models.UserRole.student:
        group_ids = [g.id for g in current_user.groups_as_student]
    elif current_user.role == models.UserRole.teacher:
        group_ids = [g.id for g in current_user.groups_as_teacher]
    elif current_user.role in [models.UserRole.admin, models.UserRole.manager]:
        return db.query(models.Test).all()
    else:
        return []

    if not group_ids:
        return []
    tests = db.query(models.Test).filter(models.Test.group_id.in_(group_ids)).all()
    return tests


# ✅ Testni ID orqali olish (Student yechishi uchun)
@router.get("/{test_id}", response_model=schemas.TestResponse)
def get_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # 👇 Student testni ko‘ra oladimi?
    if current_user.role == models.UserRole.student:
        student_groups = (
            db.query(models.group_students.c.group_id)
            .filter(models.group_students.c.student_id == current_user.id)
            .all()
        )
        student_group_ids = [g[0] for g in student_groups]

        if test.group_id not in student_group_ids:
            raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")

    return test


# ✅ Testni javobini yuborish (Student)
@router.post("/{test_id}/submit")
def submit_test(
    test_id: int,
    answers: schemas.TestSubmit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    if current_user.role != models.UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat studentlar test topshira oladi")

    score = 0
    for ans in answers.answers:
        option = db.query(models.Option).filter(models.Option.id == ans.option_id).first()
        if option and option.is_correct:
            score += 1

        db_answer = models.StudentAnswer(
            student_id=current_user.id,
            question_id=ans.question_id,
            selected_option_id=ans.option_id
        )
        db.add(db_answer)

    db.commit()

    total = db.query(models.Question).filter(models.Question.test_id == test_id).count()
    return {"student_name": current_user.full_name, "score": score, "total": total}


# ✅ Teacher uchun test natijalari
@router.get("/{test_id}/results")
def get_test_results(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1️⃣ Testni topamiz
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # 2️⃣ Faqat testni yaratgan o‘qituvchi ko‘ra oladi
    if current_user.role != models.UserRole.teacher or test.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Siz bu testning natijalarini ko‘ra olmaysiz")

    # 3️⃣ Student natijalari
    results = (
        db.query(
            models.StudentAnswer.student_id,
            models.User.full_name,
            models.StudentAnswer.submitted_at
        )
        .join(models.User, models.User.id == models.StudentAnswer.student_id)
        .filter(models.StudentAnswer.question_id.in_(
            db.query(models.Question.id).filter(models.Question.test_id == test_id)
        ))
        .distinct(models.StudentAnswer.student_id)
        .all()
    )

    # 4️⃣ Har bir student uchun ball hisoblash
    output = []
    total = db.query(models.Question).filter(models.Question.test_id == test_id).count()

    for res in results:
        student_answers = (
            db.query(models.StudentAnswer)
            .filter(
                models.StudentAnswer.student_id == res.student_id,
                models.StudentAnswer.question_id.in_(
                    db.query(models.Question.id).filter(models.Question.test_id == test_id)
                )
            )
            .all()
        )

        correct = 0
        for ans in student_answers:
            option = db.query(models.Option).filter(models.Option.id == ans.selected_option_id).first()
            if option and option.is_correct:
                correct += 1

        output.append({
            "student_name": res.full_name,
            "score": correct,
            "total": total,
            "submitted_at": res.submitted_at.strftime("%Y-%m-%d %H:%M:%S") if res.submitted_at else None
        })

    return {"test_name": test.title, "results": output}
