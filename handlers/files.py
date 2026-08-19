"""Janob HR Bot — rezyume (PDF), video-vizitka yoki portfolio link qabul qilish (ixtiyoriy)."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.contact import ask_full_name
from i18n import DEFAULT_LANG, t
from states import ApplyForm

router = Router(name="files")


@router.message(ApplyForm.waiting_file, F.document)
async def handle_resume(message: Message, state: FSMContext):
    await state.update_data(resume_file_id=message.document.file_id)
    await ask_full_name(message, state)


@router.message(ApplyForm.waiting_file, F.video)
async def handle_video(message: Message, state: FSMContext):
    await state.update_data(video_file_id=message.video.file_id)
    await ask_full_name(message, state)


@router.message(ApplyForm.waiting_file, F.text)
async def handle_portfolio_link(message: Message, state: FSMContext):
    """Nomzod fayl o'rniga matn/havola (masalan portfolio linki) yuborishi mumkin."""
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)

    text = message.text.strip()
    if not text:
        await message.answer(t("portfolio_link_empty", lang))
        return

    answers = data.get("answers", {})
    answers["portfolio_link"] = text
    await state.update_data(answers=answers)
    await ask_full_name(message, state)


@router.callback_query(ApplyForm.waiting_file, F.data == "skip_resume")
async def skip_resume(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await ask_full_name(callback.message, state)


@router.message(ApplyForm.waiting_file)
async def handle_wrong_file(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await message.answer(t("wrong_file_type", lang))
