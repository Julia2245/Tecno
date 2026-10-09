from aiogram import Router

from . import admin, errors, performance, start


def build_root_router() -> Router:
    root = Router(name="root")
    root.include_router(start.router)
    root.include_router(performance.router)
    root.include_router(admin.router)
    # Register at the parent so failures from every child router are covered.
    root.errors.register(errors.global_error_handler)
    return root
