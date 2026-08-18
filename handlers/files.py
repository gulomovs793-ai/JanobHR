"""Janob HR Bot — rezyume (PDF) yoki video-vizitka qabul qilish."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.questions import complete_application
from states import ApplyForm

router = Router(name="files")


@router.message(ApplyForm.waiting_file, F.document)
async def handle_resume(message: Message, state: FSMContext):
    await complete_application(message, state, resume_file_id=message.document.file_id)


@router.message(ApplyForm.waiting_file, F.video)
async def handle_video(message: Message, state: FSMContext):
    await complete_application(message, state, video_file_id=message.video.file_id)


@router.message(ApplyForm.waiting_file)
async def handle_wrong_file(message: Message, state: FSMContext):
    await message.answer("Iltimos, PDF fayl yoki video yuboring.")
