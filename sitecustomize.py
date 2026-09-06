"""Runtime safety patches for Janob HR.

Python imports sitecustomize automatically on startup when this file is on
sys.path. Keep this file tiny and defensive: it must never change business
logic, only protect the service from known startup duplication issues.
"""

import importlib.abc
import importlib.machinery
import logging
import sys

logger = logging.getLogger("janob_hr_runtime")


def _install_aiogram_router_reattach_guard() -> None:
    """Last-resort guard for aiogram Router re-attach crashes."""
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
            if "Router is already attached" not in message or router is self:
                raise
            try:
                # aiogram keeps the parent router on this private field.
                object.__setattr__(router, "_parent_router", None)
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


def _wrap_partner_bot_main(module) -> None:
    """Make partner_bot.main idempotent inside one Render web process.

    The web service can import/start the partner bot during startup more than
    once. The first call should keep polling; repeated calls must not attach the
    same aiogram routers to another Dispatcher because that creates:
    RuntimeError: Router is already attached.
    """
    if getattr(module, "_janobhr_partner_main_guarded", False):
        return
    original_main = getattr(module, "main", None)
    if original_main is None:
        return

    running = False

    async def guarded_main(*args, **kwargs):
        nonlocal running
        if running:
            logger.warning(
                "Partner bot already running in this process; duplicate startup skipped."
            )
            return None
        running = True
        try:
            return await original_main(*args, **kwargs)
        finally:
            running = False

    module.main = guarded_main
    module._janobhr_partner_main_guarded = True


class _PartnerBotGuardLoader(importlib.abc.Loader):
    def __init__(self, original_loader):
        self.original_loader = original_loader

    def create_module(self, spec):
        create_module = getattr(self.original_loader, "create_module", None)
        if create_module is None:
            return None
        return create_module(spec)

    def exec_module(self, module):
        self.original_loader.exec_module(module)
        _wrap_partner_bot_main(module)


class _PartnerBotGuardFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "partner_bot":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if not isinstance(spec.loader, _PartnerBotGuardLoader):
            spec.loader = _PartnerBotGuardLoader(spec.loader)
        return spec


def _install_partner_bot_main_guard() -> None:
    if "partner_bot" in sys.modules:
        _wrap_partner_bot_main(sys.modules["partner_bot"])
        return
    if not any(isinstance(finder, _PartnerBotGuardFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _PartnerBotGuardFinder())


_install_aiogram_router_reattach_guard()
_install_partner_bot_main_guard()
