"""Runtime safety patches for Janob HR.

Python imports sitecustomize automatically on startup when this file is on
sys.path. Keep this file tiny and defensive: it must never change business
logic, only protect the service from known startup duplication issues.
"""

import asyncio
import importlib.abc
import importlib.machinery
import logging
import os
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


def _patch_partner_reply_keyboard(module) -> None:
    """Mini Appni reply-keyboard ichidan olib tashlaydi va ko'k menu tugmasini chatga majburan ulaydi."""
    if getattr(module, "_janobhr_partner_keyboard_patched", False):
        return
    try:
        from aiogram.types import KeyboardButton, MenuButtonWebApp, ReplyKeyboardMarkup, WebAppInfo

        def main_menu() -> ReplyKeyboardRemove:
            return ReplyKeyboardRemove()

        module.main_menu = main_menu

        original_send_partner_home = getattr(module, "send_partner_home", None)
        if original_send_partner_home and not getattr(original_send_partner_home, "_janobhr_menu_wrapped", False):
            async def send_partner_home(message, partner):
                base_url = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
                if not base_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
                    base_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME').strip()}"
                if base_url:
                    try:
                        await message.bot.set_chat_menu_button(
                            chat_id=message.chat.id,
                            menu_button=MenuButtonWebApp(
                                text="Boshqaruv paneli",
                                web_app=WebAppInfo(url=f"{base_url}/partner"),
                            ),
                        )
                        logger.info(
                    "Partner Mini App boshqaruv tugmasi chatga o'rnatildi: chat_id=%s",
                            message.chat.id,
                        )
                    except Exception:
                        logger.exception(
                            "Partner Mini App menu tugmasi chatga o'rnatilmadi: chat_id=%s",
                            getattr(getattr(message, "chat", None), "id", None),
                        )
                return await original_send_partner_home(message, partner)

            send_partner_home._janobhr_menu_wrapped = True
            module.send_partner_home = send_partner_home

        module._janobhr_partner_keyboard_patched = True
        logger.info("Partner reply keyboarddan Boshqaruv paneli tugmasi olib tashlandi.")
    except Exception:
        logger.exception("Partner reply keyboard patch qo'llanmadi")


def _wrap_partner_bot_main(module) -> None:
    if getattr(module, "_janobhr_partner_main_guarded", False):
        _patch_partner_reply_keyboard(module)
        return
    original_main = getattr(module, "main", None)
    if original_main is None:
        return

    _patch_partner_reply_keyboard(module)
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


async def _configure_partner_miniapp_menu() -> None:
    token = os.getenv("PARTNER_BOT_TOKEN", "").strip()
    base_url = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    if not base_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
        base_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME').strip()}"
    if not token or not base_url:
        return
    try:
        from aiogram import Bot
        from aiogram.types import MenuButtonWebApp, WebAppInfo

        bot = Bot(token=token)
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Boshqaruv paneli",
                    web_app=WebAppInfo(url=f"{base_url}/partner"),
                )
            )
            logger.info("Partner Mini App global menu tugmasi o'rnatildi: %s/partner", base_url)
        finally:
            await bot.session.close()
    except Exception:
        logger.exception("Partner Mini App global menu tugmasi o'rnatilmadi")


def _install_partner_miniapp_runtime_hook() -> None:
    try:
        from aiohttp import web
    except Exception:
        return

    original_run_app = web.run_app
    if getattr(original_run_app, "_janobhr_partner_miniapp_guarded", False):
        return

    def guarded_run_app(app, *args, **kwargs):
        try:
            from partner_miniapp_api import register_partner_miniapp

            register_partner_miniapp(app)
            app.on_startup.append(lambda _app: _configure_partner_miniapp_menu())
            logger.info("Partner Mini App route ulandi: /partner")
        except Exception:
            logger.exception("Partner Mini App route ulanmadi")
        return original_run_app(app, *args, **kwargs)

    guarded_run_app._janobhr_partner_miniapp_guarded = True
    web.run_app = guarded_run_app


_install_asyncio_partner_task_guard()
_install_aiogram_router_reattach_guard()
_install_partner_bot_main_guard()
_install_partner_miniapp_runtime_hook()
