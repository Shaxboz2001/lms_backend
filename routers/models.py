from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Enum, Float, ForeignKey,
    DateTime, Table, Text, Date, JSON
)
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime
import enum

# ==============================
# ENUMS
# ==============================
class UserRole(str, enum.Enum):
    admin = "admin"
    teacher = "teacher"
    manager = "manager"
    student = "student"


class StudentStatus(str, enum.Enum):
    interested = "interested"
    studying = "studying"
    left = "left"
    graduated = "graduated"


class PaymentStatus(str, enum.Enum):
    paid = "paid"
    partial = "partial"
    unpaid = "unpaid"


# ==============================
# Many-to-Many relationships
# ==============================
group_students = Table(
    "group_students",
    Base.metadata,
    Column("group_id", Integer, ForeignKey("groups.id")),
    Column("student_id", Integer, ForeignKey("users.id"))
)
group_teachers = Table(
    "group_teachers",
    Base.metadata,
    Column("group_id", Integer, ForeignKey("groups.id")),
    Column("teacher_id", Integer, ForeignKey("users.id"))
)
# ==============================
# USER MODEL
# ==============================
class User(Base):
    __tablename__ = "users"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=True)
    password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.student)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    subject = Column(String, nullable=True)
    fee = Column(Float, nullable=True, default=0.0)
    status = Column(Enum(StudentStatus), default=StudentStatus.interested)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    teacher_percent = Column(Float, nullable=True)  # custom percent for each teacher


    # 🔹 Relationships
    # Teacher bo‘lgan user -> group’lar
    groups_as_teacher = relationship(
        "Group",
        back_populates="teacher",
        foreign_keys="Group.teacher_id"
    )

    # Student bo‘lgan user -> group’lar
    groups_as_student = relationship(
        "Group",
        secondary=group_students,
        back_populates="students"
    )

    # Attendances
    attendances_as_student = relationship(
        "Attendance",
        foreign_keys="Attendance.student_id",
        back_populates="student"
    )
    attendances_as_teacher = relationship(
        "Attendance",
        foreign_keys="Attendance.teacher_id",
        back_populates="teacher"
    )

    # Payments
    payments_as_student = relationship(
        "Payment",
        foreign_keys="Payment.student_id",
        back_populates="student"
    )
    payments_as_teacher = relationship(
        "Payment",
        foreign_keys="Payment.teacher_id",
        back_populates="teacher"
    )

    # Courses
    created_courses = relationship(
        "Course",
        back_populates="creator",
        foreign_keys="[Course.created_by]"
    )
    enrolled_courses = relationship(
        "StudentCourse",
        back_populates="student"
    )


# ==============================
# GROUP MODEL
# ==============================
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 🔹 Relationships
    course = relationship("Course", back_populates="groups")
    teacher = relationship("User", back_populates="groups_as_teacher", foreign_keys=[teacher_id])
    students = relationship("User", secondary=group_students, back_populates="groups_as_student")

    attendances = relationship("Attendance", back_populates="group")
    payments = relationship("Payment", back_populates="group")
    tests = relationship("Test", back_populates="group")


# ==============================
# PAYMENT MODEL
# ==============================
class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    teacher_id = Column(Integer, ForeignKey("users.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    month = Column(String(7), nullable=True)  # 2025-10
    created_at = Column(DateTime, default=datetime.utcnow)

    total_due = Column(Float, default=0)
    debt_amount = Column(Float, default=0)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.unpaid)
    due_date = Column(Date, nullable=True)
    is_overdue = Column(Integer, default=0)

    # 🔹 Relationships
    student = relationship("User", foreign_keys=[student_id], back_populates="payments_as_student")
    teacher = relationship("User", foreign_keys=[teacher_id], back_populates="payments_as_teacher")
    group = relationship("Group", back_populates="payments")


# ==============================
# ATTENDANCE MODEL
# ==============================
class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="present")

    student = relationship("User", foreign_keys=[student_id], back_populates="attendances_as_student")
    teacher = relationship("User", foreign_keys=[teacher_id], back_populates="attendances_as_teacher")
    group = relationship("Group", back_populates="attendances")


# ==============================
# TEST MODEL
# ==============================
class Test(Base):
    __tablename__ = "tests"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="tests")
    questions = relationship("Question", back_populates="test")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"))
    text = Column(String, nullable=False)
    type = Column(String, default="single")

    test = relationship("Test", back_populates="questions")
    options = relationship("Option", back_populates="question")


class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"))
    text = Column(String, nullable=False)
    is_correct = Column(Integer, default=0)

    question = relationship("Question", back_populates="options")


class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    selected_option_id = Column(Integer, ForeignKey("options.id"))
    submitted_at = Column(DateTime, default=datetime.utcnow)


# ==============================
# COURSE MODEL
# ==============================
class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Float, default=0)
    start_date = Column(Date, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    teacher_name = Column(String, nullable=True)

    creator = relationship("User", back_populates="created_courses", foreign_keys=[created_by])
    teacher = relationship("User", foreign_keys=[teacher_id])

    students = relationship("StudentCourse", back_populates="course")
    groups = relationship("Group", back_populates="course")  # 🔥 course–group bog‘lanishi


# ==============================
# STUDENT COURSE MODEL
# ==============================
class StudentCourse(Base):
    __tablename__ = "student_courses"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    course_id = Column(Integer, ForeignKey("courses.id"))
    joined_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("User", back_populates="enrolled_courses")
    course = relationship("Course", back_populates="students")

# salary

class SalarySetting(Base):
    __tablename__ = "salary_settings"
    id = Column(Integer, primary_key=True)
    teacher_percent = Column(Float, default=50.0)     # percent for teachers from payments
    manager_active_percent = Column(Float, default=10.0)  # percent per active student's payments
    manager_new_percent = Column(Float, default=25.0)     # percent from new student's first payment
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow, default=datetime.utcnow)

class Payroll(Base):
    __tablename__ = "payroll"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)  # 'teacher' or 'manager'
    month = Column(String, nullable=False)  # 'YYYY-MM'
    earned = Column(Float, default=0.0)
    deductions = Column(Float, default=0.0)
    net = Column(Float, default=0.0)
    status = Column(String, default="pending")  # pending | paid
    details = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

    user = relationship("User", backref="payrolls")

class PayrollPayment(Base):
    __tablename__ = "payroll_payments"
    id = Column(Integer, primary_key=True)
    payroll_id = Column(Integer, ForeignKey("payroll.id"), nullable=False)
    paid_amount = Column(Float, nullable=False)
    paid_by = Column(Integer, ForeignKey("users.id"))  # admin who paid
    paid_at = Column(DateTime, default=datetime.utcnow)
