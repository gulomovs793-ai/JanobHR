"""Runtime safety patches for Janob HR.

Python imports sitecustomize automatically on startup when this file is on
sys.path. Keep this file tiny and defensive: it must never change business
logic, only protect the service from known startup duplication issues.
"""

import asyncio
import importlib.abc
import importlib.machinery
import logging
import sys

logger = logging.getLogger("janob_hr_runtime")
print("JANOBHR_SITECUSTOMIZE_LOADED", file=sys.stderr)

_PARTNER_TASK_STARTED = False


def _is_partner_bot_main_coro(coro) -> bool:
    code = getattr(coro, "cr_code", None)
    if code is None:
        return False
    filename = (getattr(code, "co_filename", "") or "").replace("\\", "/")
    name = getattr(code, "co_name", "") or ""
    return filename.endswith("/partner_bot.py") and name in {"main", "guarded_main"}


async def _skipped_partner_task() -> None:
    logger.warning("Partner Bot duplicate polling task skipped before router re-attach.")


def _install_asyncio_partner_task_guard() -> None:
    original_create_task = asyncio.create_task
    if getattr(original_create_task, "_janobhr_partner_task_guarded", False):
        return

    def guarded_create_task(coro, *args, **kwargs):
        global _PARTNER_TASK_STARTED
        if _is_partner_bot_main_coro(coro):
            if _PARTNER_TASK_STARTED:
                try:
                    coro.close()
                except Exception:
                    pass
                return original_create_task(_skipped_partner_task(), *args, **kwargs)
            _PARTNER_TASK_STARTED = True
        return original_create_task(coro, *args, **kwargs)

    guarded_create_task._janobhr_partner_task_guarded = True
    asyncio.create_task = guarded_create_task


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
    if getattr(module, "_janobhr_partner_main_guarded", False):
        return
    original_main = getattr(module, "main", None)
    if original_main is None:
        return

    running = False

    async def guarded_main(*args, **kwargs):
        nonlocal running
        if running:
            logger.warning("Partner Bot already running; duplicate startup skipped.")
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


_install_asyncio_partner_task_guard()
_install_aiogram_router_reattach_guard()
_install_partner_bot_main_guard()
