import os
import re
import sqlite3
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "Не знайдено BOT_TOKEN. Встанови його командою:\n"
        "export BOT_TOKEN='ТВІЙ_ТОКЕН'"
    )

DB_FILE = "attendance.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# БАЗА ДАНИХ
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(student_id, date),
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# КЛАВІАТУРИ
# ============================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Журнал", callback_data="journal"),
            InlineKeyboardButton("👥 Учні", callback_data="students"),
        ],
        [
            InlineKeyboardButton("📚 Історія", callback_data="history"),
        ],
    ])


def students_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати учня", callback_data="add_student")],
        [InlineKeyboardButton("➖ Видалити учня", callback_data="delete_student")],
        [InlineKeyboardButton("📋 Список учнів", callback_data="student_list")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
    ])


# ============================================================
# СТАРТ
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    text = (
        "🤖 <b>Журнал відвідування</b>\n\n"
        "Оберіть потрібну дію:"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🏠 Головне меню:",
        reply_markup=main_keyboard(),
    )


# ============================================================
# КНОПКИ
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # -------------------------
    # ГОЛОВНЕ МЕНЮ
    # -------------------------

    if data == "back":
        context.user_data.clear()

        await query.edit_message_text(
            "🏠 Головне меню:",
            reply_markup=main_keyboard(),
        )
        return

    # -------------------------
    # УЧНІ
    # -------------------------

    if data == "students":
        await query.edit_message_text(
            "👥 <b>Учні</b>\n\nОберіть дію:",
            parse_mode="HTML",
            reply_markup=students_keyboard(),
        )
        return

    if data == "student_list":
        await show_student_list(query)
        return

    if data == "add_student":
        context.user_data["action"] = "add_student"

        await query.edit_message_text(
            "➕ Введіть ПІБ учня одним повідомленням.\n\n"
            "Наприклад:\n"
            "<code>Іваненко Іван Іванович</code>\n\n"
            "Для скасування введіть /cancel",
            parse_mode="HTML",
        )
        return

    if data == "delete_student":
        await show_delete_students(query)
        return

    if data.startswith("del_student:"):
        student_id = int(data.split(":")[1])

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT name FROM students WHERE id = ?",
            (student_id,),
        )

        student = cur.fetchone()

        if student:
            cur.execute(
                "DELETE FROM attendance WHERE student_id = ?",
                (student_id,),
            )

            cur.execute(
                "DELETE FROM students WHERE id = ?",
                (student_id,),
            )

            conn.commit()

            await query.edit_message_text(
                f"🗑 Учня <b>{student['name']}</b> видалено.",
                parse_mode="HTML",
                reply_markup=students_keyboard(),
            )
        else:
            await query.edit_message_text(
                "Учня не знайдено.",
                reply_markup=students_keyboard(),
            )

        conn.close()
        return

    # -------------------------
    # ЖУРНАЛ
    # -------------------------

    if data == "journal":
        context.user_data.clear()
        context.user_data["action"] = "journal_date"

        await query.edit_message_text(
            "📖 <b>Журнал</b>\n\n"
            "Введіть дату у форматі:\n\n"
            "<code>ДД.ММ.РРРР</code>\n\n"
            "Наприклад:\n"
            "<code>09.09.2026</code>\n\n"
            "Для скасування введіть /cancel",
            parse_mode="HTML",
        )
        return

    # -------------------------
    # ІСТОРІЯ
    # -------------------------

    if data == "history":
        context.user_data.clear()
        context.user_data["action"] = "history_date"

        await query.edit_message_text(
            "📚 <b>Історія журналу</b>\n\n"
            "Введіть дату у форматі:\n\n"
            "<code>ДД.ММ.РРРР</code>\n\n"
            "Наприклад:\n"
            "<code>09.09.2026</code>",
            parse_mode="HTML",
        )
        return

    # -------------------------
    # СТАТУС УЧНЯ
    # -------------------------

    if data.startswith("status:"):
        parts = data.split(":")
        student_id = int(parts[1])
        status = parts[2]

        date = context.user_data.get("journal_date")

        if not date:
            await query.edit_message_text(
                "Помилка: дату журналу не знайдено.",
                reply_markup=main_keyboard(),
            )
            return

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO attendance (student_id, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id, date)
            DO UPDATE SET status = excluded.status
        """, (student_id, date, status))

        conn.commit()

        cur.execute(
            "SELECT name FROM students WHERE id = ?",
            (student_id,),
        )

        student = cur.fetchone()
        conn.close()

        status_text = {
            "present": "✅ Присутній",
            "absent": "❌ Відсутній",
            "sick": "🤒 Хворіє",
            "reason": "📝 Поважна причина",
        }

        await query.edit_message_text(
            f"👤 <b>{student['name']}</b>\n\n"
            f"Дата: <b>{date}</b>\n"
            f"Відмітка: <b>{status_text[status]}</b>",
            parse_mode="HTML",
            reply_markup=attendance_menu(student_id),
        )

        return

    # -------------------------
    # НАЗАД ДО СПИСКУ ЖУРНАЛУ
    # -------------------------

    if data == "journal_students":
        await show_journal_students(query, context)
        return


# ============================================================
# СПИСОК УЧНІВ
# ============================================================

async def show_student_list(query):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name FROM students ORDER BY name"
    )

    students = cur.fetchall()
    conn.close()

    if not students:
        text = "📋 <b>Список учнів порожній.</b>"
    else:
        lines = ["📋 <b>Список учнів:</b>\n"]

        for i, student in enumerate(students, 1):
            lines.append(
                f"{i}. {student['name']}"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=students_keyboard(),
    )


async def show_delete_students(query):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name FROM students ORDER BY name"
    )

    students = cur.fetchall()
    conn.close()

    if not students:
        await query.edit_message_text(
            "📋 Список учнів порожній.",
            reply_markup=students_keyboard(),
        )
        return

    buttons = []

    for student in students:
        buttons.append([
            InlineKeyboardButton(
                f"🗑 {student['name']}",
                callback_data=f"del_student:{student['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="students")
    ])

    await query.edit_message_text(
        "➖ <b>Виберіть учня для видалення:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ЖУРНАЛ
# ============================================================

async def show_journal_students(query, context):
    date = context.user_data.get("journal_date")

    if not date:
        await query.edit_message_text(
            "Дата не вибрана.",
            reply_markup=main_keyboard(),
        )
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name FROM students ORDER BY name"
    )

    students = cur.fetchall()
    conn.close()

    if not students:
        await query.edit_message_text(
            "📋 Спочатку додайте учнів.",
            reply_markup=students_keyboard(),
        )
        return

    buttons = []

    for student in students:
        buttons.append([
            InlineKeyboardButton(
                student["name"],
                callback_data=f"student:{student['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Головне меню", callback_data="back")
    ])

    await query.edit_message_text(
        f"📖 <b>Журнал за {date}</b>\n\n"
        f"Оберіть учня:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def attendance_menu(student_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Присутній",
                callback_data=f"status:{student_id}:present",
            ),
            InlineKeyboardButton(
                "❌ Відсутній",
                callback_data=f"status:{student_id}:absent",
            ),
        ],
        [
            InlineKeyboardButton(
                "🤒 Хворіє",
                callback_data=f"status:{student_id}:sick",
            ),
            InlineKeyboardButton(
                "📝 Поважна причина",
                callback_data=f"status:{student_id}:reason",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ До списку",
                callback_data="journal_students",
            )
        ],
    ])


async def show_student_attendance(query, context, student_id):
    date = context.user_data.get("journal_date")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM students WHERE id = ?",
        (student_id,),
    )

    student = cur.fetchone()

    conn.close()

    if not student:
        await query.edit_message_text(
            "Учня не знайдено.",
            reply_markup=main_keyboard(),
        )
        return

    await query.edit_message_text(
        f"👤 <b>{student['name']}</b>\n\n"
        f"📅 Дата: <b>{date}</b>\n\n"
        f"Виберіть відмітку:",
        parse_mode="HTML",
        reply_markup=attendance_menu(student_id),
    )


# ============================================================
# ІСТОРІЯ
# ============================================================

async def show_history(update, date):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT students.name, attendance.status
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        WHERE attendance.date = ?
        ORDER BY students.name
    """, (date,))

    records = cur.fetchall()
    conn.close()

    if not records:
        await update.message.reply_text(
            f"📚 За <b>{date}</b> записів немає.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    status_text = {
        "present": "✅ Присутній",
        "absent": "❌ Відсутній",
        "sick": "🤒 Хворіє",
        "reason": "📝 Поважна причина",
    }

    lines = [
        f"📚 <b>Журнал за {date}</b>\n"
    ]

    for i, record in enumerate(records, 1):
        lines.append(
            f"{i}. <b>{record['name']}</b> — "
            f"{status_text.get(record['status'], record['status'])}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ============================================================
# ТЕКСТОВІ ПОВІДОМЛЕННЯ
# ============================================================

def valid_date(date_string):
    """
    Перевіряє формат ДД.ММ.РРРР
    """

    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", date_string):
        return False

    try:
        datetime.strptime(date_string, "%d.%m.%Y")
        return True
    except ValueError:
        return False


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    action = context.user_data.get("action")

    # -------------------------
    # ДОДАВАННЯ УЧНЯ
    # -------------------------

    if action == "add_student":

        if len(text) < 2:
            await update.message.reply_text(
                "❌ Ім'я занадто коротке. Введіть ПІБ ще раз."
            )
            return

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                "INSERT INTO students (name) VALUES (?)",
                (text,),
            )

            conn.commit()

            await update.message.reply_text(
                f"✅ Учня <b>{text}</b> додано.",
                parse_mode="HTML",
                reply_markup=students_keyboard(),
            )

        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "⚠️ Такий учень уже є у списку.",
                reply_markup=students_keyboard(),
            )

        finally:
            conn.close()

        context.user_data.clear()
        return

    # -------------------------
    # ДАТА ЖУРНАЛУ
    # -------------------------

    if action == "journal_date":

        if not valid_date(text):
            await update.message.reply_text(
                "❌ Неправильний формат дати.\n\n"
                "Введіть дату саме так:\n"
                "<code>ДД.ММ.РРРР</code>\n\n"
                "Наприклад:\n"
                "<code>09.09.2026</code>",
                parse_mode="HTML",
            )
            return

        context.user_data["journal_date"] = text
        context.user_data["action"] = None

        await send_journal_students(update, context)
        return

    # -------------------------
    # ДАТА ІСТОРІЇ
    # -------------------------

    if action == "history_date":

        if not valid_date(text):
            await update.message.reply_text(
                "❌ Неправильний формат дати.\n\n"
                "Потрібно:\n"
                "<code>ДД.ММ.РРРР</code>\n\n"
                "Наприклад:\n"
                "<code>09.09.2026</code>",
                parse_mode="HTML",
            )
            return

        context.user_data.clear()

        await show_history(update, text)
        return

    await update.message.reply_text(
        "Оберіть дію з меню:",
        reply_markup=main_keyboard(),
    )


async def send_journal_students(update, context):
    date = context.user_data.get("journal_date")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name FROM students ORDER BY name"
    )

    students = cur.fetchall()
    conn.close()

    if not students:
        await update.message.reply_text(
            "📋 Список учнів порожній.\n\n"
            "Спочатку додайте учнів.",
            reply_markup=students_keyboard(),
        )
        return

    buttons = []

    for student in students:
        buttons.append([
            InlineKeyboardButton(
                student["name"],
                callback_data=f"student:{student['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 Головне меню",
            callback_data="back",
        )
    ])

    await update.message.reply_text(
        f"📖 <b>Журнал за {date}</b>\n\n"
        f"Оберіть учня:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ОБРОБКА ВИБОРУ УЧНЯ
# ============================================================

async def student_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("student:"):
        return

    student_id = int(query.data.split(":")[1])

    await show_student_attendance(
        query,
        context,
        student_id,
    )


# ============================================================
# CANCEL
# ============================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Дію скасовано.",
        reply_markup=main_keyboard(),
    )


# ============================================================
# ЗАПУСК
# ============================================================

def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("menu", menu_command)
    )

    application.add_handler(
        CommandHandler("cancel", cancel)
    )

    application.add_handler(
        CallbackQueryHandler(student_callback, pattern=r"^student:")
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    logger.info("Бот запущений.")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
