from .auth import auth_router
from .database import Base, engine
from .attendance import attend_router
from .courses import courses_router
from .groups import groups_router
from .payments import payments_router
from .students import students_router
from .teachers import teachers_router
from .test_page import tests_router
from .users import users_router
from .dashboard import dashboard_router

__all__ = [
    "Base", "engine", "auth_router", "attend_router", "courses_router",
    "groups_router", "payments_router", "students_router", "teachers_router",
    "tests_router", "users_router", "dashboard_router"
]
