"""Runtime safety patches for Janob HR.

Python imports sitecustomize automatically on startup when this file is on
sys.path. Keep this file tiny and defensive: it must never change business
logic, only protect the service from a known aiogram router re-attach crash
seen during Render startup after embedding the partner bot into the web service.
"""

import logging

logger = logging.getLogger("janob_hr_runtime")


def _install_aiogram_router_reattach_guard() -> None:
    try:
        from aiogram.dispatcher.router import Router
    except Exception:
        return

    original_include_router = Router.include_router
    if getattr(original_include_router, "_janobhr_guarded", False):
        return

    def guarded_include_router(self, router):
        try:
            return original_include_router(self, router)
        except RuntimeError as exc:
            message = str(exc)
            if "Router is already attached" not in message:
                raise
            if router is self:
                raise
            # Aiogram stores the parent router internally. Clearing it only
            # after this exact crash lets the app recover from duplicated
            # startup/import ordering without changing normal routing behavior.
            try:
                setattr(router, "_parent_router", None)
                logger.warning(
                    "Aiogram router re-attach guard applied: router=%s target=%s",
                    getattr(router, "name", repr(router)),
                    getattr(self, "name", repr(self)),
                )
                return original_include_router(self, router)
            except Exception:
                raise exc

    guarded_include_router._janobhr_guarded = True
    Router.include_router = guarded_include_router


_install_aiogram_router_reattach_guard()
