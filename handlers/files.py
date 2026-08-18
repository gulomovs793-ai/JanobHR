"""Janob HR Bot — rezyume (PDF) yoki video-vizitka qabul qilish."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.contact import ask_full_name
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


@router.message(ApplyForm.waiting_file)
async def handle_wrong_file(message: Message, state: FSMContext):
    await message.answer("Iltimos, PDF fayl yoki video yuboring.")
