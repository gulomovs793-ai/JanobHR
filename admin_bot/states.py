from aiogram.fsm.state import State, StatesGroup


class AdminForm(StatesGroup):
    # --- Yangi vakansiya yaratish oqimi ---
    creating_title = State()
    creating_description = State()
    reviewing_ai_questions = State()
    entering_manual_questions = State()
    creating_resume_required = State()

    # --- Mavjud vakansiyani tahrirlash oqimi ---
    editing_description_for_regen = State()
    editing_manual_questions = State()
