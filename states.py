from aiogram.fsm.state import State, StatesGroup


class ApplyForm(StatesGroup):
    choosing_vacancy = State()
    answering_questions = State()
    waiting_file = State()
    finished = State()
