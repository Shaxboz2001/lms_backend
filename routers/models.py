from sqlalchemy import Column, Integer, String, Enum, Float, ForeignKey, DateTime, Table, Text, Date
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime
import enum

# ==============================
# User roles
# ==============================
class UserRole(str, enum.Enum):
    admin = "admin"
    teacher = "teacher"
    manager = "manager"
    student = "student"

# ==============================
# Student status
# ==============================
class StudentStatus(str, enum.Enum):
    interested = "interested"
    studying = "studying"
    left = "left"
    graduated = "graduated"

# ==============================
# User model
# ==============================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=True)
    password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.student)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    age = Column(Integer, nullable=True)

    # Student-specific
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    subject = Column(String, nullable=True)
    fee = Column(Float, nullable=True)
    status = Column(Enum(StudentStatus), default=StudentStatus.interested)

    # Relationships
    groups_as_teacher = relationship("Group", secondary="group_teachers", back_populates="teachers")
    groups_as_student = relationship("Group", secondary="group_students", back_populates="students")
    attendances_as_student = relationship("Attendance", foreign_keys="Attendance.student_id", back_populates="student")
    attendances_as_teacher = relationship("Attendance", foreign_keys="Attendance.teacher_id", back_populates="teacher")
    payments_as_student = relationship("Payment", foreign_keys="Payment.student_id", back_populates="student")
    payments_as_teacher = relationship("Payment", foreign_keys="Payment.teacher_id", back_populates="teacher")

    # ✅ Qo‘shilganlar:
    created_courses = relationship("Course", back_populates="creator")  # o‘zi yaratgan kurslar
    enrolled_courses = relationship("StudentCourse", back_populates="student")  # o‘zi qatnashgan kurslar


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
# Group model
# ==============================
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    students = relationship("User", secondary=group_students, back_populates="groups_as_student")
    teachers = relationship("User", secondary=group_teachers, back_populates="groups_as_teacher")
    attendances = relationship("Attendance", back_populates="group")
    payments = relationship("Payment", back_populates="group")
    tests = relationship("Test", back_populates="group")

# ==============================
# Payment model
# ==============================
class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    teacher_id = Column(Integer, ForeignKey("users.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    month = Column(String(7), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("User", foreign_keys=[student_id], back_populates="payments_as_student")
    teacher = relationship("User", foreign_keys=[teacher_id], back_populates="payments_as_teacher")
    group = relationship("Group", back_populates="payments")

# ==============================
# Attendance model
# ==============================
class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="present")  # present / absent / late

    student = relationship("User", foreign_keys=[student_id], back_populates="attendances_as_student")
    teacher = relationship("User", foreign_keys=[teacher_id], back_populates="attendances_as_teacher")
    group = relationship("Group", back_populates="attendances")

# ==============================
# Test models
# ==============================
class Test(Base):
    __tablename__ = "tests"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    created_by = Column(Integer, ForeignKey("users.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    created_at = Column(DateTime, default=datetime.utcnow)  # ✅ shu yer
    group = relationship("Group", back_populates="tests")
    questions = relationship("Question", back_populates="test")

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"))
    text = Column(String, nullable=False)
    type = Column(String, default="single")  # single / multiple

    test = relationship("Test", back_populates="questions")
    options = relationship("Option", back_populates="question")

class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"))
    text = Column(String, nullable=False)
    is_correct = Column(Integer, default=0)  # 1 = true, 0 = false

    question = relationship("Question", back_populates="options")

class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    selected_option_id = Column(Integer, ForeignKey("options.id"))
    submitted_at = Column(DateTime, default=datetime.utcnow)

# ==============================
# Course model
# ==============================
class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    teacher_name = Column(String, nullable=False)
    price = Column(Integer, nullable=True)
    start_date = Column(Date, nullable=True)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="created_courses")
    students = relationship("StudentCourse", back_populates="course")

# ==============================
# StudentCourse model
# ==============================
class StudentCourse(Base):
    __tablename__ = "student_courses"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    course_id = Column(Integer, ForeignKey("courses.id"))
    joined_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("User", back_populates="enrolled_courses")
    course = relationship("Course", back_populates="students")
