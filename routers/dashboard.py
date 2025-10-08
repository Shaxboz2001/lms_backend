from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/")
def get_dashboard(role: str = "student"):
    if role == "admin":
        return {"pages": ["Users", "Groups", "Payments", "Reports"]}
    elif role == "teacher":
        return {"pages": ["Attendance", "Tests"]}
    elif role == "manager":
        return {"pages": ["Groups", "Students", "Payments"]}
    else:
        return {"pages": ["My Courses", "Grades", "Enroll"]}
