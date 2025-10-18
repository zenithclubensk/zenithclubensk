"""
ENSK Family Telegram Bot
Single-file prototype (Python + sqlite3) for managing specialties, years, modules, lessons,
with summaries, practical works, directed works, and past exams.

Usage:
- Set environment variable BOT_TOKEN to your Telegram bot token
- (Optional) Set ADMIN_IDS as comma-separated admin Telegram user IDs
- Run: python ensk_family_bot.py

Dependencies:
- python-telegram-bot (v20+)

This is a starting prototype. Customize messages, keyboard text, and DB content as needed.
"""

import os
import asyncio
import sqlite3
from typing import List, Tuple, Optional
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

# --- Config ---------------------------------------------------------------------------------
BOT_TOKEN = os.getenv("8286089353:AAE6dyRz7ni-WAZPyqhTlfxJUh0xaarudA8")  # ضع التوكن هنا أو استعمل متغير البيئة
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
DB_PATH = Path("ensk_family.db")
MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)

# Conversation states for admin content upload
(AWAIT_SPECIALTY, AWAIT_YEAR, AWAIT_MODULE, AWAIT_LESSON_TITLE, AWAIT_LESSON_SUMMARY, AWAIT_UPLOAD_FILES) = range(6)

# --- Database helpers -----------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS specialties (
        id INTEGER PRIMARY KEY,
        code TEXT UNIQUE,
        name TEXT
    );
    CREATE TABLE IF NOT EXISTS years (
        id INTEGER PRIMARY KEY,
        specialty_id INTEGER,
        year_label TEXT,
        FOREIGN KEY(specialty_id) REFERENCES specialties(id)
    );
    CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY,
        year_id INTEGER,
        module_name TEXT,
        FOREIGN KEY(year_id) REFERENCES years(id)
    );
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY,
        module_id INTEGER,
        title TEXT,
        summary TEXT,
        FOREIGN KEY(module_id) REFERENCES modules(id)
    );
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        lesson_id INTEGER,
        file_type TEXT,
        file_path TEXT,
        original_name TEXT,
        FOREIGN KEY(lesson_id) REFERENCES lessons(id)
    );
    CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY,
        lesson_id INTEGER,
        question TEXT,
        options TEXT,
        answer_index INTEGER,
        FOREIGN KEY(lesson_id) REFERENCES lessons(id)
    );
    """)
    conn.commit()
    conn.close()

# --- Utility functions ----------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def keyboard_from_pairs(pairs: List[Tuple[str, str]], row_width=2):
    buttons = [InlineKeyboardButton(text=label, callback_data=key) for key, label in pairs]
    rows = [buttons[i:i+row_width] for i in range(0, len(buttons), row_width)]
    return InlineKeyboardMarkup(rows)

# --- Core Bot Handlers ----------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "أهلا بك في ENSK Family Bot 🎓\n"
        "اختر التخصص لبدء التصفح أو استخدم /search للبحث عن درس.\n\n"
        "إذا كنت مسؤولًا، استعمل /admin للإدارة."
    )
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, code, name FROM specialties ORDER BY name")
    rows = c.fetchall()
    conn.close()

    if not rows:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("لا يوجد محتوى بعد - اطلب من المسؤولين الإضافة", callback_data='no_op')]])
        await update.message.reply_text(text, reply_markup=kb)
        return

    pairs = [(f"spec:{r['id']}", f"{r['name']} ({r['code']})") for r in rows]
    await update.message.reply_text(text, reply_markup=keyboard_from_pairs(pairs, row_width=1))


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("spec:"):
        spec_id = int(data.split(":", 1)[1])
        await show_years(q, spec_id)
        return
    if data.startswith("year:"):
        year_id = int(data.split(":", 1)[1])
        await show_modules(q, year_id)
        return
    if data.startswith("mod:"):
        mod_id = int(data.split(":", 1)[1])
        await show_lessons(q, mod_id)
        return
    if data.startswith("lesson:"):
        lesson_id = int(data.split(":", 1)[1])
        await show_lesson_detail(q, lesson_id)
        return
    if data == 'no_op':
        await q.reply_text("انتظر إضافة المحتوى من الإدارة.")
        return
    if data.startswith('file:'):
        fid = int(data.split(':', 1)[1])
        await send_file(q, fid)
        return

    await q.reply_text("خيار غير معروف.")


async def show_years(query_or_message, spec_id: int):
    if hasattr(query_or_message, 'answer'):
        q = query_or_message
        send = q.message.reply_text
    else:
        send = query_or_message.reply_text

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name FROM specialties WHERE id=?", (spec_id,))
    spec = c.fetchone()
    c.execute("SELECT id, year_label FROM years WHERE specialty_id=? ORDER BY id", (spec_id,))
    years = c.fetchall()
    conn.close()

    if not years:
        await send("لا توجد سنوات مضافة لهذا التخصص بعد.")
        return

    text = f"التخصص: {spec['name']}\nاختر السنة:" if spec else "اختر السنة:"
    pairs = [(f"year:{r['id']}", r['year_label']) for r in years]
    await send(text, reply_markup=keyboard_from_pairs(pairs, row_width=2))


async def show_modules(q, year_id: int):
    await q.answer()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT year_label FROM years WHERE id=?", (year_id,))
    y = c.fetchone()
    c.execute("SELECT id, module_name FROM modules WHERE year_id=? ORDER BY module_name", (year_id,))
    modules = c.fetchall()
    conn.close()

    if not modules:
        await q.message.reply_text("لا توجد مقررات مضافة لهذه السنة بعد.")
        return

    text = f"السنة: {y['year_label']}\nاختر المقرر:" if y else "اختر المقرر:"
    pairs = [(f"mod:{r['id']}", r['module_name']) for r in modules]
    await q.message.reply_text(text, reply_markup=keyboard_from_pairs(pairs, row_width=1))


async def show_lessons(q, mod_id: int):
    await q.answer()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT module_name FROM modules WHERE id=?", (mod_id,))
    m = c.fetchone()
    c.execute("SELECT id, title FROM lessons WHERE module_id=? ORDER BY title", (mod_id,))
    lessons = c.fetchall()
    conn.close()

    if not lessons:
        await q.message.reply_text("لا توجد دروس لهذه المقرر بعد.")
        return

    text = f"المقرر: {m['module_name']}\nاختر الدرس:" if m else "اختر الدرس:"
    pairs = [(f"lesson:{r['id']}", r['title']) for r in lessons]
    await q.message.reply_text(text, reply_markup=keyboard_from_pairs(pairs, row_width=1))


async def show_lesson_detail(q, lesson_id: int):
    await q.answer()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT title, summary FROM lessons WHERE id=?", (lesson_id,))
    lesson = c.fetchone()
    c.execute("SELECT id, file_type, original_name FROM files WHERE lesson_id=?", (lesson_id,))
    files = c.fetchall()
    conn.close()

    if not lesson:
        await q.message.reply_text("الدرس غير موجود.")
        return

    text = f"📘 *{lesson['title']}*\n\n{lesson['summary'] or 'لا يوجد ملخص.'}"
    pairs = [(f"file:{f['id']}", f"{f['file_type']} — {f['original_name']}") for f in files]

    if pairs:
        kb = keyboard_from_pairs(pairs, row_width=1)
        await q.message.reply_markdown(text)
        await q.message.reply_text("الملفات المتاحة:", reply_markup=kb)
    else:
        await q.message.reply_markdown(text)


async def send_file(q, file_id: int):
    await q.answer()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT file_path, original_name FROM files WHERE id=?", (file_id,))
    f = c.fetchone()
    conn.close()
    if not f:
        await q.message.reply_text("الملف غير موجود.")
        return
    path = Path(f['file_path'])
    if not path.exists():
        await q.message.reply_text("الملف لم يعد متوفرًا على الخادم.")
        return
    await q.message.reply_document(document=InputFile(path), filename=f['original_name'])

# --- Search ---------------------------------------------------------------------------------

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ' '.join(context.args) if context.args else None
    if not text:
        await update.message.reply_text('استعمل: /search <كلمات البحث>')
        return
    q = f"%{text}%"
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT lessons.id as id, lessons.title as title, modules.module_name as module
        FROM lessons
        JOIN modules ON lessons.module_id=modules.id
        WHERE lessons.title LIKE ? OR lessons.summary LIKE ?
        LIMIT 20
    """, (q, q))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text('ما لقيت والو، جرّب كلمات أخرى.')
        return
    pairs = [(f"lesson:{r['id']}", f"{r['title']} — {r['module']}") for r in rows]
    await update.message.reply_text(f'نتائج البحث ({len(rows)}):', reply_markup=keyboard_from_pairs(pairs, row_width=1))

# --- Admin Panel -----------------------------------------------------------------------------

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text('غير مسموح — خاص بالمسؤولين فقط.')
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('إضافة محتوى جديد', callback_data='admin:add')],
        [InlineKeyboardButton('قائمة التخصصات/إعادة التهيئة', callback_data='admin:list')]
    ])
    await update.message.reply_text('لوحة الإدارة:', reply_markup=kb)


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == 'admin:add':
        await q.message.reply_text('أدخل اسم التخصص (مثال: "رياضيات" أو رمز التخصص):')
        return AWAIT_SPECIALTY
    if q.data == 'admin:list':
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT s.name as spec, y.year_label as year, m.module_name as module, l.title as lesson
            FROM specialties s
            LEFT JOIN years y ON y.specialty_id=s.id
            LEFT JOIN modules m ON m.year_id=y.id
            LEFT JOIN lessons l ON l.module_id=m.id
            ORDER BY s.name
            LIMIT 200
        """)
        rows = c.fetchall()
        conn.close()
        txt = '\n'.join([
            f"{r['spec'] or '-'} | {r['year'] or '-'} | {r['module'] or '-'} | {r['lesson'] or '-'}"
            for r in rows
        ]) or 'لا توجد بيانات.'
        await q.message.reply_text(txt)
        return
    await q.message.reply_text('خيار غير معروف.')


async def admin_receive_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if '|' in text:
        code, name = [s.strip() for s in text.split('|', 1)]
    else:
        code = text.lower().replace(' ', '_')
        name = text
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO specialties (code, name) VALUES (?, ?)", (code, name))
    conn.commit()
    c.execute("SELECT id FROM specialties WHERE code=?", (code,))
    spec_id = c.fetchone()['id']
    conn.close()

    await update.message.reply_text(
        f"تم تسجيل التخصص: {name}\n"
        "أدخل الآن تسمية السنة (مثال: 'سنة 1' أو '3 متوسط'). "
        "يمكنك إدخال عدة سنوات مفصولة بـ ;"
    )

    context.user_data['spec_id'] = spec_id
    return AWAIT_YEAR
