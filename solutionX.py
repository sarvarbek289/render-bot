import os
import math
import time
import json
import html 
import random
import re
import sqlite3
import threading
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import telebot
from telebot import types

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

import ai_grader      # Gemini orqali Writing/Speaking AI tekshiruvi (ai_grader.py)

# =========================
# ⚙️ SOZLAMALAR
# =========================

TOKEN = os.getenv("BOT_TOKEN", "8901997013:AAHntuWt538ty0pwHtt1x8yTrAT4ShtuH2k")
GROUP_ID = int(os.getenv("GROUP_ID", "-1004307752693"))
KANAL_ID = os.getenv("KANAL_ID", "@solutionX_mvp")
KANAL_HAVOLA = os.getenv("KANAL_HAVOLA", "https://t.me/solutionX_mvp")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "6324823602, 8503938285").replace(" ", "").split(",") if x}

REFERRAL_MIN_PERCENT = 30   # do'st Grammar Testda kamida shuncha % olishi kerak (25 tadan 8 ta)
REFERRAL_MIN_SECONDS = 90   # 25 talik testga ketgan minimal vaqt (tavakkal bosishdan himoya)
GRAMMAR_QUESTIONS_PER_TEST = 25
GRAMMAR_MINUTES = 15        # faqat matnda ko'rsatiladi (taymer yo'q)

# --- Reading / Listening materiallari ---
# Papka tuzilmasi: materials/<reading|listening>/part<1-6>/*.json  (listening uchun yoniga audio ham)
# Bir part papkasiga bir nechta .json qo'shsangiz, bot ularni navbat bilan/tasodifiy beradi.
MATERIALS_DIR = os.path.join(BASE_DIR, "materials")
AUDIO_MAX_PLAYS = 2         # imtihondagidek: har bir audio ko'pi bilan 2 marta eshittiriladi

# --- Writing / Speaking AI tekshiruvi (Gemini; kalit .env dagi GEMINI_API_KEY) ---
AI_SESSION_TTL = 45 * 60            # topshiriq berilgach javob kutish muddati (soniya)
AI_MIN_WORDS_ABS = 15               # Writing: bundan qisqa javob AI ga yuborilmaydi
AI_MAX_TEXT_CHARS = 4000            # Writing: eng uzun javob (belgi)
AI_MIN_VOICE_SEC = 5                # Speaking: eng qisqa ovoz
AI_MAX_VOICE_SEC = 240              # Speaking: eng uzun ovoz (4 daqiqa)
AI_MAX_AUDIO_BYTES = 15 * 1024 * 1024

TZ_OFFSET_HOURS = 5                 # Toshkent (UTC+5): AI kunlik limiti shu vaqt bo'yicha almashadi

# --- Peshqadamlar ---
LEADERBOARD_SIZE = 10 

if not TOKEN:
    raise SystemExit("BOT_TOKEN topilmadi. .env fayl yarating yoki: export BOT_TOKEN='...'")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
BOT_USERNAME = bot.get_me().username

# =========================
# 🗄 BAZA (SQLite)
# =========================

_db = sqlite3.connect(os.path.join(BASE_DIR, "bot.db"), check_same_thread=False)
_db.row_factory = sqlite3.Row
_lock = threading.Lock()


def q_exec(sql, params=()):
    with _lock:
        cur = _db.execute(sql, params)
        _db.commit()
        return cur


def q_one(sql, params=()):
    with _lock:
        return _db.execute(sql, params).fetchone()


def q_all(sql, params=()):
    with _lock:
        return _db.execute(sql, params).fetchall()


GRAMMAR_LEVELS = {          # callback kodi -> (tugma matni, bazadagi cefr_level qiymatlari)
    "A2": ("A2", ("A2",)),
    "B1": ("B1", ("B1",)),
    "B2": ("B2", ("B2",)),
    "C1": ("C1 & C2", ("C1", "C2")),
}

SEED_QUESTIONS = [
    # (skill, part, cefr, topic, type, difficulty, grammar_tag, text, options, correct, explanation)
    ("Grammar", 1, "A2", "Daily life", "Multiple Choice", 2, "Present Simple",
     "She ___ to school every day.", {"A": "go", "B": "goes", "C": "going"}, "B",
     "He/she/it bilan fe'lga -s/-es qo'shiladi."),
    ("Grammar", 1, "B1", "Education", "Multiple Choice", 4, "Conditionals",
     "If I ___ more time, I would learn French.", {"A": "have", "B": "had", "C": "will have"}, "B",
     "Second conditional: If + Past Simple, would + V1."),
    ("Grammar", 1, "B1", "Travel", "Multiple Choice", 5, "Present Perfect",
     "I ___ never been to London.", {"A": "have", "B": "has", "C": "am"}, "A",
     "I/you/we/they + have + V3."),
    ("Grammar", 1, "B2", "Work", "Multiple Choice", 6, "Passive Voice",
     "The report ___ by the manager yesterday.", {"A": "wrote", "B": "was written", "C": "is writing"}, "B",
     "Past Passive: was/were + V3."),
    ("Grammar", 1, "B2", "Science", "Multiple Choice", 7, "Articles",
     "___ Sun rises in the east.", {"A": "A", "B": "An", "C": "The"}, "C",
     "Yagona narsalar oldidan 'the' ishlatiladi."),
    ("Grammar", 1, "B1", "Daily life", "Multiple Choice", 4, "Prepositions",
     "She is good ___ mathematics.", {"A": "at", "B": "in", "C": "on"}, "A",
     "good at — biror narsada yaxshi."),
    ("Grammar", 1, "A1", "Sport", "Multiple Choice", 1, "Present Simple",
     "They ___ football on Sundays.", {"A": "play", "B": "plays", "C": "playing"}, "A",
     "I/you/we/they bilan fe'l o'zgarmaydi."),
    ("Grammar", 1, "A2", "Entertainment", "Multiple Choice", 2, "Past Simple",
     "We ___ to the cinema last night.", {"A": "go", "B": "went", "C": "gone"}, "B",
     "Last night — o'tgan zamon, go -> went."),
    ("Grammar", 1, "A2", "Weather", "Multiple Choice", 2, "Present Continuous",
     "Look! It ___ now.", {"A": "rains", "B": "is raining", "C": "rain"}, "B",
     "Look!/now — hozir bo'layotgan ish: is/am/are + V-ing."),
    ("Grammar", 1, "A2", "Education", "Multiple Choice", 3, "Comparatives",
     "This book is ___ than that one.", {"A": "more interesting", "B": "most interesting", "C": "interestinger"}, "A",
     "Uzun sifatlar: more + sifat + than."),
    ("Grammar", 1, "B1", "Daily life", "Multiple Choice", 4, "Present Perfect",
     "She has lived here ___ 2015.", {"A": "for", "B": "since", "C": "from"}, "B",
     "since + aniq vaqt nuqtasi, for + davomiylik."),
    ("Grammar", 1, "B1", "Law", "Multiple Choice"   , 4, "Modal Verbs",
     "You ___ wear a seat belt. It's the law.", {"A": "must", "B": "can", "C": "might"}, "A",
     "Majburiyat/qonun — must."),
    ("Grammar", 1, "B1", "Weather", "Multiple Choice", 4, "Conditionals",
     "If it rains tomorrow, we ___ at home.", {"A": "stay", "B": "will stay", "C": "stayed"}, "B",
     "First conditional: If + Present Simple, will + V1."),
    ("Grammar", 1, "B1", "Daily life", "Multiple Choice", 4, "Past Continuous",
     "I ___ TV when the phone rang.", {"A": "watched", "B": "was watching", "C": "am watching"}, "B",
     "Boshqa ish kesib qo'ygan jarayon — was/were + V-ing."),
    ("Grammar", 1, "B1", "Food", "Multiple Choice", 4, "Quantifiers",
     "There isn't ___ milk in the fridge.", {"A": "much", "B": "many", "C": "a few"}, "A",
     "Sanalmaydigan otlar bilan much ishlatiladi."),
    ("Grammar", 1, "B1", "Hobbies", "Multiple Choice", 5, "Gerund / Infinitive",
     "He enjoys ___ books.", {"A": "read", "B": "to read", "C": "reading"}, "C",
     "enjoy + V-ing."),
    ("Grammar", 1, "B1", "People", "Multiple Choice", 5, "Relative Clauses",
     "The man ___ lives next door is a doctor.", {"A": "who", "B": "which", "C": "whose"}, "A",
     "Odamlar uchun who ishlatiladi."),
    ("Grammar", 1, "B1", "Work", "Multiple Choice", 5, "Reported Speech",
     "She said that she ___ tired.", {"A": "is", "B": "was", "C": "will be"}, "B",
     "Reported speech: Present -> Past (is -> was)."),
    ("Grammar", 1, "B1", "Feelings", "Multiple Choice", 4, "Prepositions",
     "He is afraid ___ dogs.", {"A": "of", "B": "from", "C": "at"}, "A",
     "afraid of — biror narsadan qo'rqish."),
    ("Grammar", 1, "B1", "People", "Multiple Choice", 4, "Articles",
     "She is ___ honest woman.", {"A": "a", "B": "an", "C": "the"}, "B",
     "honest [h] o'qilmaydi, unli tovush bilan boshlanadi -> an."),
    ("Grammar", 1, "A2", "Daily life", "Multiple Choice", 2, "Question Forms",
     "___ do you live?", {"A": "Where", "B": "Who", "C": "What"}, "A",
     "Joy so'rash uchun where ishlatiladi."),
    ("Grammar", 1, "B2", "Education", "Multiple Choice", 7, "Conditionals",
     "If I had studied harder, I ___ the exam.", {"A": "would pass", "B": "would have passed", "C": "will pass"}, "B",
     "Third conditional: If + Past Perfect, would have + V3."),
    ("Grammar", 1, "B2", "Wishes", "Multiple Choice", 6, "Wish",
     "I wish I ___ more free time.", {"A": "have", "B": "had", "C": "will have"}, "B",
     "Hozirgi afsus: wish + Past Simple."),
    ("Grammar", 1, "B2", "Entertainment", "Multiple Choice", 6, "Past Perfect",
     "When we arrived, the film ___ already started.", {"A": "has", "B": "had", "C": "was"}, "B",
     "Boshqa o'tgan ishdan oldin tugagan ish — had + V3."),
    ("Grammar", 1, "B2", "Languages", "Multiple Choice", 6, "Passive Voice",
     "English ___ all over the world.", {"A": "speaks", "B": "is spoken", "C": "is speaking"}, "B",
     "Present Passive: am/is/are + V3."),
    ("Grammar", 1, "B2", "Daily life", "Multiple Choice", 7, "Modals of Deduction",
     "He's not answering the phone. He ___ be asleep.", {"A": "must", "B": "ought", "C": "would"}, "A",
     "Kuchli taxmin (deyarli aniq) — must be."),
    ("Grammar", 1, "B2", "Weather", "Multiple Choice", 6, "Linking Words",
     "___ it was raining, we went for a walk.", {"A": "Although", "B": "Because", "C": "So"}, "A",
     "Qarama-qarshilik: although + gap (garchi ...)."),
    ("Grammar", 1, "B2", "Childhood", "Multiple Choice", 6, "Used to",
     "I ___ play chess when I was a child.", {"A": "use to", "B": "used to", "C": "am used to"}, "B",
     "O'tmishdagi odat — used to + V1."),
    ("Grammar", 1, "B2", "Past", "Multiple Choice", 8, "Inversion",
     "Had I known, I ___ you.", {"A": "would have told", "B": "will tell", "C": "told"}, "A",
     "Had I known = If I had known (third conditional inversiyasi)."),
    ("Grammar", 1, "B2", "Education", "Multiple Choice", 7, "Future Perfect",
     "By next year, she ___ her degree.", {"A": "will finish", "B": "will have finished", "C": "finishes"}, "B",
     "By + kelajak vaqti — will have + V3."),
]


# =========================
# 📚 GRAMMAR SAVOLLAR BANKI (daraja bo'yicha)
# =========================
# Har bir element: (grammar_tag, savol matni, TO'G'RI javob, [3 ta noto'g'ri variant], izoh)
# Variantlar botga yuklanganda aralashtiriladi, shuning uchun to'g'ri javob har xil harfda chiqadi.

_BANK_A2 = [
    ("Present Simple" , "My brother ___ football on Sundays.", "plays", ["play", "playing", "is play"],
     "He/she/it bilan fe'lga -s qo'shiladi."),
    ("Present Continuous", "Look! The children ___ in the garden.", "are playing", ["play", "plays", "played"],
     "Hozir bo'layotgan ish — am/is/are + V-ing."),
    ("Past Simple", "She ___ her homework yesterday.", "didn't do", ["doesn't do", "didn't did", "not did"],
     "Inkor: didn't + V1 (asosiy fe'l o'zgarmaydi)."),
    ("Articles", "I have ___ umbrella in my bag.", "an", ["a", "the", "some"],
     "umbrella unli tovush bilan boshlanadi -> an."),
    ("Prepositions", "The lesson starts ___ 9 o'clock.", "at", ["in", "on", "by"],
     "Aniq soat oldidan at ishlatiladi."),
    ("Prepositions", "I usually visit my grandmother ___ Saturdays.", "on", ["in", "at", "for"],
     "Hafta kunlari oldidan on ishlatiladi."),
    ("Prepositions", "My birthday is ___ July.", "in", ["on", "at", "to"],
     "Oylar oldidan in ishlatiladi."),
    ("Superlatives", "Mount Everest is ___ mountain in the world.", "the highest", ["higher", "highest", "the higher"],
     "Orttirma daraja: the + sifat-est."),
    ("Quantifiers", "How ___ sugar do you want in your tea?", "much", ["many", "few", "several"],
     "Sanalmaydigan ot (sugar) bilan much."),
    ("Quantifiers", "How ___ students are there in your class?", "many", ["much", "long", "often"],
     "Sanaladigan ko'plik ot bilan many."),
    ("There is/are", "There ___ two bottles of water on the table.", "are", ["is", "be", "am"],
     "Ko'plik ot oldidan there are."),
    ("Modal verbs", "She ___ speak three languages.", "can", ["cans", "is can", "does can"],
     "can har doim V1 bilan keladi, -s olmaydi."),
    ("Modal verbs", "You ___ wear a seat belt in the car. It's the law.", "must", ["might", "would", "may"],
     "Qonun/majburiyat — must."),
    ("Future", "Look at those clouds. It ___ rain.", "is going to", ["will to", "going to", "does going to"],
     "Ko'rinib turgan belgi asosida bashorat — be going to."),
    ("Future", "I'm cold. I ___ close the window.", "will", ["would to", "am going", "do"],
     "Shu zahoti qilingan qaror — will."),
    ("Present Perfect", "I ___ in Tashkent since 2015.", "have lived", ["live", "lived", "am living"],
     "since bilan Present Perfect ishlatiladi."),
    ("Present Perfect", "She has worked here ___ five years.", "for", ["since", "ago", "during"],
     "Davomiylik (5 yil) oldidan for."),
    ("Question Forms", "___ is your favourite subject?", "What", ["Who", "Where", "When"],
     "Narsa haqida so'rash — What."),
    ("Question Forms", "___ does the film start?", "What time", ["What", "How", "Who"],
     "Soatni so'rash — What time."),
    ("Pronouns", "This is Anna. ___ is my sister.", "She", ["He", "Her", "It"],
     "Ayol kishi uchun ega olmoshi — she."),
    ("Pronouns", "Please help ___. I can't carry this box.", "me", ["I", "my", "mine"],
     "Fe'ldan keyin to'ldiruvchi olmosh — me."),
    ("Possessives", "Is this your pen? No, it isn't ___.", "mine", ["my", "me", "I"],
     "Ot kerak emas — egalik olmoshi mine."),
    ("Adverbs of Frequency", "He ___ late for school.", "is never", ["never is", "is not never", "does never"],
     "be fe'lidan keyin never keladi."),
    ("Adverbs", "She speaks English very ___.", "well", ["good", "goodly", "best"],
     "good sifat, fe'lni well ravishi aniqlaydi."),
    ("Gerund", "She is good at ___.", "drawing", ["draw", "to draw", "drew"],   
     "Predlogdan keyin fe'l V-ing shaklida keladi."),
    ("Infinitive", "I want ___ a new phone.", "to buy", ["buying", "buy", "bought"],
     "want + to + V1."),
    ("Some/Any", "I don't have ___ brothers.", "any", ["some", "a", "an"],
     "Inkor gapda any ishlatiladi."),
    ("Some/Any", "Would you like ___ tea?", "some", ["any", "many", "few"],
     "Taklif (offer) gapda some ishlatiladi."),
    ("Past Continuous", "I was watching TV when the phone ___.", "rang", ["ring", "has rung", "rings"],
     "Uzun jarayonni qisqa ish bo'ldi: Past Simple."),
    ("Irregular Verbs", "He ___ a new car last month.", "bought", ["buyed", "buy", "has buyed"],
     "buy — bought — bought."),
    ("Was/Were", "They ___ at home yesterday.", "were", ["was", "are", "be"],
     "they bilan o'tgan zamonda were."),
    ("Question Forms", "___ she like coffee?", "Does", ["Do", "Is", "Has"],
     "she bilan Present Simple so'roq: Does."),
    ("Prepositions", "I live ___ Tashkent.", "in", ["at", "on", "to"],
     "Shahar oldidan in."),
    ("Prepositions", "We go ___ school by bus.", "to", ["at", "in", "on"],
     "Harakat yo'nalishi — to."),
    ("Conjunctions", "I was tired, ___ I went to bed early.", "so", ["because", "but", "although"],
     "Natija — so."),
    ("Conjunctions", "I stayed at home ___ it was raining.", "because", ["so", "but", "or"],
     "Sabab — because."),
    ("Suggestions", "___ go to the park!", "Let's", ["Let", "We", "Lets"],
     "Taklif: Let's + V1."),
    ("Quantifiers", "I have ___ friends in this city.", "a few", ["a little", "much", "an"],
     "Sanaladigan ko'plik ot bilan a few."),
    ("Imperatives", "___ late for the lesson!", "Don't be", ["Not be", "Aren't", "Don't"],
     "Inkor buyruq: Don't + V1."),
    ("Possessive 's", "This is ___ car.", "Ali's", ["Alis", "Ali", "of Ali"],
     "Egalik: ot + 's."),
]

_BANK_B1 = [
    ("Present Perfect", "I ___ him since last year.", "haven't seen", ["didn't see", "don't see", "haven't saw"],
     "since bilan Present Perfect: have/has + V3."),
    ("Past Simple", "When I was a child, I ___ in a small village.", "lived", ["have lived", "live", "am living"],
     "O'tgan zamondagi tugagan davr — Past Simple."),
    ("Conditionals", "If I were you, I ___ that job.", "would take", ["will take", "took", "would took"],
     "Second conditional: If + Past, would + V1."),
    ("Passive Voice", "This bridge ___ in 1990.", "was built", ["built", "is built", "has built"],
     "Past Passive: was/were + V3."),
    ("Passive Voice", "English ___ in many countries.", "is spoken", ["speaks", "is speak", "spoken"],
     "Present Passive: am/is/are + V3."),
    ("Relative Clauses", "The book ___ I bought yesterday is very good.", "which", ["who", "whose", "where"],
     "Narsa uchun which (yoki that)."),
    ("Relative Clauses", "That's the girl ___ father is a pilot.", "whose", ["who", "which", "her"],
     "Egalikni bildiradi — whose."),
    ("Indirect Questions", "Could you tell me where ___?", "the station is", ["is the station", "the station does", "does the station be"],
     "Ichki savolda gap tartibi darak gapdagidek: ega + fe'l."),
    ("Modal verbs", "You ___ smoke here. It's forbidden.", "mustn't", ["don't have to", "may", "would"],
     "Taqiq — mustn't."),
    ("Modal verbs", "You ___ come with me if you don't want to.", "don't have to", ["mustn't", "can't", "shouldn't"],
     "Majburiy emas — don't have to."),
    ("Modal verbs", "You look ill. You ___ see a doctor.", "should", ["can", "would", "might"],
     "Maslahat — should."),
    ("Gerund", "Thank you for ___ me.", "helping", ["to help", "help", "helped"],
     "Predlogdan keyin V-ing."),
    ("Gerund", "I'm looking forward to ___ you.", "seeing", ["see", "saw", "to see"],
     "look forward to + V-ing (bu yerda to — predlog)."),
    ("Gerund/Infinitive", "He stopped ___ because it was unhealthy.", "smoking", ["to smoke", "smoke", "smoked"],
     "stop + V-ing — odatni to'xtatish."),
    ("Used to", "I ___ play tennis when I was younger, but now I don't.", "used to", ["am used to", "use to", "get used to"],
     "O'tmishdagi odat — used to + V1."),
    ("Too/Enough", "He isn't old ___ to drive a car.", "enough", ["too", "very", "so"],
     "Sifatdan KEYIN enough + to + V1."),
    ("Too/Enough", "The tea is ___ hot to drink.", "too", ["enough", "so", "very"],
     "too + sifat + to + V1 — ortiqcha darajada."),
    ("So/Such", "It was ___ a beautiful day that we went to the beach.", "such", ["so", "very", "too"],
     "such + a + sifat + ot."),
    ("Quantifiers", "There are ___ people in the room, so it feels empty.", "few", ["a few", "little", "a little"],
     "few — deyarli yo'q (salbiy ma'no)."),
    ("Past Continuous", "While I ___ dinner, the lights went out.", "was cooking", ["cooked", "cook", "have cooked"],
     "Davom etayotgan ish — Past Continuous."),
    ("Present Perfect Continuous", "I ___ for you for an hour!", "have been waiting", ["am waiting", "wait", "waited"],
     "for an hour — have been + V-ing."),
    ("Comparatives", "The more you practise, ___ you become.", "the better", ["better", "the best", "best"],
     "The more..., the better... tuzilmasi."),
    ("Comparisons", "She isn't as tall ___ her sister.", "as", ["than", "like", "that"],
     "as ... as tuzilmasi."),
    ("Question Tags", "You like pizza, ___?", "don't you", ["do you", "aren't you", "didn't you"],
     "Darak gap -> inkor tag."),
    ("Wish", "I wish I ___ a car.", "had", ["have", "would have", "has"],
     "Hozirgi afsus: wish + Past Simple."),
    ("Prepositions", "I'm not good ___ cooking.", "at", ["in", "on", "with"],
     "good at + V-ing."),
    ("Prepositions", "She's married ___ a doctor.", "to", ["with", "by", "for"],
     "married to."),
    ("Phrasal Verbs", "Please turn ___ the TV. It's too loud.", "down", ["up", "in", "at"],
     "turn down — ovozni pasaytirish."),
    ("Phrasal Verbs", "I'm looking ___ my keys. Have you seen them?", "for", ["at", "after", "up"],
     "look for — qidirmoq."),
    ("Phrasal Verbs", "He gave ___ smoking last year.", "up", ["in", "out", "away"],
     "give up — tashlamoq."),
    ("Articles", "My sister works as ___ engineer.", "an", ["a", "the", "some"],
     "Kasb oldidan a/an; engineer unli bilan boshlanadi."),
    ("Articles", "He plays ___ guitar very well.", "the", ["a", "an", "some"],
     "Cholg'u asboblari oldidan the."),
    ("Uncountable Nouns", "I need some ___.", "advice", ["advices", "an advice", "many advices"],
     "advice — sanalmaydigan ot."),
    ("Quantifiers", "We haven't got ___ time.", "much", ["many", "a few", "few"],
     "time sanalmaydi — much."),
    ("Conditionals", "If you heat ice, it ___.", "melts", ["will melt", "melted", "would melt"],
     "Zero conditional: umumiy haqiqat — Present + Present."),
    ("Conditionals", "You won't pass the exam ___ you study harder.", "unless", ["if", "when", "because"],
     "unless = if ... not."),
    ("Past Perfect", "When I arrived, the train ___.", "had already left", ["has already left", "was already leaving", "already leaves"],
     "Boshqa o'tgan ishdan oldin — Past Perfect."),
    ("Linking Words", "___ the rain, we had a great picnic.", "Despite", ["Although", "Because", "However"],
     "Despite + ot/V-ing."),
    ("Linking Words", "He was tired. ___, he finished the work.", "However", ["Because", "Although", "Despite"],
     "Qarama-qarshilik: However, + gap."),
    ("Present Perfect", "I've lived here ___ 2010.", "since", ["for", "from", "during"],
     "since + boshlanish nuqtasi."),
    ("Reflexive Pronouns", "She hurt ___ while playing tennis.", "herself", ["her", "she", "hers"],
     "Ega va to'ldiruvchi bir xil — herself."),
    ("Gerund", "She is used to ___ up early.", "getting", ["get", "got", "gets"],
     "be used to + V-ing."),
    ("Adjective Order", "She has a ___ dress.", "beautiful red silk", ["silk red beautiful", "red beautiful silk", "beautiful silk red"],
     "Tartib: fikr -> rang -> material."),
]

_BANK_B2 = [
    ("Conditionals", "If she ___ the bus, she wouldn't have been late.", "hadn't missed", ["didn't miss", "hasn't missed", "wouldn't miss"],
     "Third conditional: If + Past Perfect."),
    ("Mixed Conditionals", "If I had taken that job, I ___ in London now.", "would be living", ["would have lived", "will live", "had lived"],
     "Mixed: o'tmishdagi shart, hozirgi natija."),
    ("Wish", "I wish I ___ harder for the exam last week.", "had studied", ["studied", "would study", "have studied"],
     "O'tmishdagi afsus: wish + Past Perfect."),
    ("Wish", "I wish I ___ swim.", "could", ["can", "would", "will"],
     "Hozirgi afsus: wish + could."),
    ("Passive Voice", "The work ___ by Friday.", "must be finished", ["must finish", "must be finish", "must have finish"],
     "Modal passive: modal + be + V3."),
    ("Passive Voice", "The window ___ by the children.", "has been broken", ["has broken", "have been broken", "is broke"],
     "Present Perfect Passive: has/have been + V3."),
    ("Causative", "I ___ my car repaired yesterday.", "had", ["did", "made", "took"],
     "have + narsa + V3 — o'zimiz qilmay, boshqaga qildirish."),
    ("Reported Speech", "'I will call you tomorrow,' he said. -> He said he ___ me the next day.", "would call", ["will call", "called", "calls"],
     "will -> would, tomorrow -> the next day."),
    ("Reported Speech", "She asked, 'Have you seen the film?' -> She asked me if I ___ the film.", "had seen", ["have seen", "would see", "did see"],
     "Present Perfect -> Past Perfect."),
    ("Reported Speech", "He told me ___ late.", "not to be", ["don't be", "not be", "to don't be"],
     "Inkor buyruq: told + kimga + not to + V1."),
    ("Relative Clauses", "My brother, ___ lives in Canada, is a pilot.", "who", ["that", "which", "whom"],
     "Non-defining clause'da that ishlatilmaydi."),
    ("Relative Clauses", "The city ___ I was born is very old.", "where", ["which", "that", "what"],
     "Joy uchun where."),
    ("Participle Clauses", "The man ___ at the door is my uncle.", "standing", ["stood", "stands", "to stand"],
     "Aktiv ma'noli participle — V-ing."),
    ("Gerund/Infinitive", "I regret ___ you that your application was rejected.", "to tell", ["telling", "tell", "told"],
     "regret to + V1 — yomon xabarni hozir aytish."),
    ("Gerund/Infinitive", "I remember ___ him at the party last year.", "meeting", ["to meet", "meet", "met"],
     "remember + V-ing — o'tgan voqeani eslash."),
    ("Gerund/Infinitive", "Don't forget ___ the door when you leave.", "to lock", ["locking", "lock", "locked"],
     "forget to + V1 — qilishni unutmaslik."),
    ("Gerund/Infinitive", "She suggested ___ to the cinema.", "going", ["to go", "go", "that we to go"],
     "suggest + V-ing."),
    ("Modals of Deduction", "The lights are off. They ___ gone to bed.", "must have", ["must be", "had", "may"],
     "O'tmish haqida kuchli taxmin — must have + V3."),
    ("Modal Perfect", "You ___ told me earlier! Now it's too late.", "should have", ["should", "must", "would"],
     "Afsus/tanqid — should have + V3."),
    ("Modal Perfect", "We ___ so fast. The train was late.", "needn't have driven", ["needn't driven", "not need have driven", "mustn't have driven"],
     "needn't have + V3 — keraksiz bajarilgan ish."),
    ("Past Perfect Continuous", "She was exhausted because she ___ all day.", "had been working", ["has been working", "is working", "would work"],
     "O'tgan voqeagacha davom etgan jarayon."),
    ("Future Continuous", "This time tomorrow, I ___ on a beach.", "will be lying", ["will lie", "lie", "am lain"],
     "Kelajakdagi aniq vaqtda davom etayotgan ish."),
    ("Time Clauses", "I'll call you as soon as I ___ home.", "get", ["will get", "am getting", "got"],
     "Vaqt gapida kelasi zamon o'rniga Present Simple."),
    ("Past Perfect", "By the time we arrived, the concert ___.", "had started", ["has started", "was starting", "starts"],
     "By the time + Past Simple, ... Past Perfect."),
    ("Articles", "She is ___ best student in our class.", "the", ["a", "an", "this"],
     "Orttirma daraja oldidan the."),
    ("Articles", "___ Netherlands is famous for its tulips.", "The", ["A", "An", "Some"],
     "Ko'plik shaklidagi davlat nomlari oldidan the."),
    ("Prepositions", "She's responsible ___ the marketing team.", "for", ["of", "to", "at"],
     "responsible for."),
    ("Prepositions", "I'm not used ___ such cold weather.", "to", ["with", "for", "at"],
     "be used to + ot/V-ing."),
    ("Comparatives", "This exam was ___ than I expected.", "far more difficult", ["more difficultly", "very more difficult", "the most difficult"],
     "Darajani kuchaytirish: far/much + comparative."),
    ("Inversion", "Not only ___ late, but he also forgot the documents.", "did he arrive", ["he arrived", "he did arrive", "arrived he"],
     "Not only boshda kelsa — inversiya (did he arrive)."),
    ("Agreement", "She doesn't like jazz, and ___ do I.", "neither", ["so", "too", "either"],
     "Inkor gapga qo'shilish — neither + yordamchi fe'l + ega."),
    ("Agreement", "'I love pizza.' '___ do I.'", "So", ["Neither", "Too", "Also"],
     "Tasdiq gapga qo'shilish — so + yordamchi fe'l + ega."),
    ("Linking Words", "___ he was tired, he kept working.", "Even though", ["Despite", "In spite", "However"],
     "Even though + to'liq gap."),
    ("Linking Words", "She passed the test ___ not studying.", "despite", ["although", "but", "because"],
     "Despite + V-ing."),
    ("Phrasal Verbs", "We ran ___ of milk, so I went to the shop.", "out", ["off", "away", "up"],
     "run out of — tugab qolmoq."),
    ("Phrasal Verbs", "The meeting was called ___ because of the storm.", "off", ["out", "down", "away"],
     "call off — bekor qilmoq."),
    ("Phrasal Verbs", "I can't ___ his rude behaviour any more.", "put up with", ["put up", "put on with", "put off with"],
     "put up with — chidamoq."),
    ("Word Formation", "He gave a very ___ answer.", "convincing", ["convince", "convincingly", "convinced"],
     "Otdan oldin sifat kerak: convincing."),
    ("Word Formation", "The ___ of the new software was a success.", "introduction", ["introduce", "introductory", "introduced"],
     "the dan keyin ot: introduction."),
    ("Quantifiers", "Hardly ___ people came to the party.", "any", ["some", "no", "few"],
     "hardly any — deyarli hech qancha."),
    ("Linking Verbs", "The soup tastes ___.", "terrible", ["terribly", "in terrible", "terrified"],
     "taste kabi bog'lovchi fe'llardan keyin sifat."),
    ("Used to/Would", "When we were kids, we ___ go fishing every summer.", "would", ["used", "were", "had"],
     "O'tmishdagi takrorlanuvchi harakat — would + V1."),
    ("Subjunctive", "It's important that he ___ on time.", "be", ["is", "will be", "being"],
     "It's important that + ega + V1 (subjunctive)."),
    ("Preferences", "I'd rather you ___ here.", "didn't smoke", ["don't smoke", "won't smoke", "not smoke"],
     "would rather + ega + Past Simple."),
    ("It's time", "It's time we ___ home.", "went", ["going", "will go", "to go"],
     "It's time + ega + Past Simple."),
]

_BANK_C1 = [
    ("Inversion", "Rarely ___ such a beautiful sunset.", "have I seen", ["I have seen", "I seen", "did I seen"],
     "Rarely boshda kelsa — yordamchi fe'l ega oldiga o'tadi."),
    ("Inversion", "Hardly had she sat down ___ the phone rang.", "when", ["than", "that", "as"],
     "Hardly ... when."),
    ("Inversion", "No sooner had he left ___ it started to rain.", "than", ["then", "that", "as"],
     "No sooner ... than."),
    ("Inversion", "Under no circumstances ___ open the door.", "should you", ["you should", "do you", "will you not"],
     "Under no circumstances + inversiya."),
    ("Subjunctive", "The committee recommended that the proposal ___ rejected.", "be", ["is", "was", "would be"],
     "recommend that + ega + V1 (subjunctive)."),
    ("Conditional Inversion", "Had it not been for your advice, I ___ a terrible mistake.", "would have made", ["would make", "will make", "had made"],
     "Had it not been for = If it hadn't been for."),
    ("Conditional Inversion", "___ you need further information, please contact us.", "Should", ["Would", "Do", "Had"],
     "Should you need = If you should need (rasmiy)."),
    ("Conditional Inversion", "Were he to resign, the company ___ in trouble.", "would be", ["will be", "is", "had been"],
     "Were he to = If he were to (taxminiy vaziyat)."),
    ("Cleft Sentences", "___ I really enjoyed was the atmosphere.", "What", ["That", "Which", "It"],
     "What + gap + was ... — ta'kidlash."),
    ("Cleft Sentences", "It was not until midnight ___ the guests left.", "that", ["when", "which", "than"],
     "It was not until ... that."),
    ("Participle Clauses", "___ the report, she realised the figures were wrong.", "Having read", ["Having been read", "To have read", "Read"],
     "Avval bo'lgan ish — Having + V3."),
    ("Participle Clauses", "___ from the top of the hill, the town looks tiny.", "Seen", ["Seeing", "Having seen", "To see"],
     "Passiv ma'noli participle — V3."),
    ("Participle Clauses", "___, she remained silent.", "Not knowing what to say", ["Not to know what said", "Knowing not what said", "She did not knowing"],
     "Inkor participle: Not + V-ing."),
    ("Passive Reporting", "He is said ___ the company ten years ago.", "to have founded", ["to found", "founding", "to be founded"],
     "is said to have + V3 — o'tmishdagi ish haqida."),
    ("Passive Reporting", "The suspect is believed ___ the country.", "to have left", ["to leave", "having left", "leaving"],
     "is believed to have + V3."),
    ("Causative", "I need to have my laptop ___.", "repaired", ["repair", "repairing", "to repair"],
     "have + narsa + V3."),
    ("Wish", "I wish I ___ so much money on that watch last year.", "hadn't spent", ["didn't spend", "haven't spent", "wouldn't spend"],
     "O'tmishdagi afsus: wish + Past Perfect."),
    ("Wish", "If only I ___ you earlier!", "had told", ["told", "would tell", "have told"],
     "If only + Past Perfect — o'tmishdagi afsus."),
    ("Preferences", "I'd sooner you ___ anything about it.", "didn't say", ["don't say", "hadn't say", "not say"],
     "would sooner + ega + Past Simple."),
    ("Modals", "She ___ have left already; her coat is still here.", "can't", ["mustn't", "shouldn't", "wouldn't"],
     "O'tmish haqida kuchli inkor taxmin — can't have + V3."),
    ("Dependent Prepositions", "The decision was made ___ pressure from shareholders.", "under", ["on", "by", "with"],
     "under pressure."),
    ("Dependent Prepositions", "He was accused ___ stealing the money.", "of", ["for", "with", "about"],
     "accuse somebody of."),
    ("Dependent Prepositions", "I'm not in favour ___ changing the rules.", "of", ["for", "with", "to"],
     "in favour of."),
    ("Dependent Prepositions", "He prides himself ___ his punctuality.", "on", ["in", "for", "of"],
     "pride oneself on."),
    ("Dependent Prepositions", "She is renowned ___ her generosity.", "for", ["as", "of", "with"],
     "renowned for."),
    ("Quantifiers", "___ the students passed the exam, but a few failed.", "Most of", ["Most", "Almost", "The most"],
     "Most of + the + ot."),
    ("Agreement", "The number of applicants ___ increased this year.", "has", ["have", "are", "were"],
     "The number of + ko'plik ot -> birlik fe'l."),
    ("Agreement", "A number of problems ___ been reported.", "have", ["has", "is", "was"],
     "A number of + ko'plik ot -> ko'plik fe'l."),
    ("Inversion", "So exhausted ___ that she fell asleep immediately.", "was she", ["she was", "did she", "she were"],
     "So + sifat boshda kelsa — inversiya."),
    ("Inversion", "Little ___ he know that the police were watching him.", "did", ["does", "had", "was"],
     "Little did he know — inversiya."),
    ("Inversion", "Only after the meeting ___ the truth.", "did she learn", ["she learned", "she did learn", "learned she"],
     "Only after boshda kelsa — inversiya."),
    ("Hedging", "The results ___ to suggest that the treatment is effective.", "appear", ["are appeared", "appearing", "are appearing"],
     "appear to + V1 — ehtiyotkor ifoda (hedging)."),
    ("Idioms", "It goes ___ saying that honesty matters.", "without", ["by", "with", "beyond"],
     "It goes without saying — gapirmasa ham ma'lum."),
    ("Idioms", "I'm ___ the weather today; I think I'll stay in.", "under", ["over", "below", "beneath"],
     "under the weather — o'zini yomon his qilmoq."),
    ("Idioms", "At the end of the day, it ___ down to personal choice.", "comes", ["goes", "falls", "puts"],
     "come down to — oxir-oqibat ... ga bog'liq."),
    ("Linking Words", "The plan is ambitious; ___, it is not impossible.", "nevertheless", ["whereas", "moreover", "consequently"],
     "Qarama-qarshilik — nevertheless."),
    ("Linking Words", "___ the fact that he was exhausted, he kept going.", "Notwithstanding", ["Whereas", "Provided", "Unless"],
     "Notwithstanding = despite (rasmiy)."),
    ("Linking Words", "He was reluctant to accept, ___ he eventually agreed.", "though", ["despite", "owing to", "in case"],
     "though + to'liq gap."),
    ("Linking Words", "You can borrow my car ___ you return it by six.", "provided that", ["even if", "unless", "whereas"],
     "provided that = faqat shart bilan."),
    ("Linking Words", "She studied hard. ___ she failed the exam.", "Nevertheless", ["Despite", "Although", "Because"],
     "Alohida gapni qarama-qarshilik bilan bog'laydi."),
    ("Subjunctive", "I insist that she ___ present at the meeting.", "be", ["is", "will be", "was"],
     "insist that + ega + V1."),
    ("Time Expressions", "It is high time the government ___ action.", "took", ["takes", "will take", "taking"],
     "It's high time + Past Simple."),
    ("Quantifiers", "There is hardly ___ evidence to support the claim.", "any", ["few", "many", "some"],
     "hardly any + sanalmaydigan ot."),
    ("Comparatives", "The more he explained, ___ confused we became.", "the more", ["more", "the most", "most"],
     "The more ..., the more ..."),
    ("Word Formation", "The company's ___ growth surprised analysts.", "unprecedented", ["unprecedently", "unprecedent", "precedented"],
     "growth oldidan sifat kerak."),
    ("Word Formation", "She was praised for her ___ to detail.", "attention", ["attentive", "attentively", "attend"],
     "her dan keyin ot — attention."),
    ("Collocations", "He made a ___ attempt to hide his disappointment.", "valiant", ["valuable", "valid", "valued"],
     "valiant attempt — jasoratli urinish."),
    ("Gerund", "I can't help ___ that he's lying.", "thinking", ["to think", "think", "thought"],
     "can't help + V-ing — o'zini tuta olmaslik."),
    ("Gerund", "It's no use ___ over spilt milk.", "crying", ["to cry", "cry", "cried"],
     "It's no use + V-ing."),
    ("Gerund", "She admitted ___ the vase.", "breaking", ["to break", "break", "having to break"],
     "admit + V-ing."),
    ("Gerund", "He denied ___ anything about the theft.", "knowing", ["to know", "know", "to have known"],
     "deny + V-ing."),
    ("Relative Clauses", "The report, ___ was published last week, caused controversy.", "which", ["that", "what", "whose"],
     "Non-defining clause'da which."),
    ("Relative Clauses", "The reason ___ he left remains unclear.", "why", ["for", "what", "where"],
     "the reason why."),
]


def _build_bank_questions():
    """Bankdan SEED formatidagi savollarni yasaydi (variantlar aralashtiriladi, har bir savol uchun bir xil tartib)."""
    import zlib
    levels = (("A2", 2, _BANK_A2), ("B1", 4, _BANK_B1), ("B2", 6, _BANK_B2), ("C1", 8, _BANK_C1))
    out = []
    for cefr, diff, items in levels:
        for tag, text, right, wrong, expl in items:
            opts = [right] + list(wrong)[:2]   # faqat A, B, C variantlar
            random.Random(zlib.crc32(text.encode("utf-8"))).shuffle(opts)
            letters = "ABCD"[:len(opts)]
            options = dict(zip(letters, opts))
            correct = letters[opts.index(right)]
            out.append(("Grammar", 1, cefr, "General", "Multiple Choice", diff, tag, text, options, correct, expl))
    return out


SEED_QUESTIONS += _build_bank_questions()


def normalize_phone(phone):
    """Telefon raqamni '+998901234567' ko'rinishiga keltiradi (Telegram ba'zan '+' siz yuboradi)."""
    digits = re.sub(r"\D", "", str(phone or ""))
    return f"+{digits}" if digits else ""


def init_db():
    q_exec("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        age INTEGER,
        state TEXT DEFAULT 'new',
        referrer_id INTEGER,
        ref_count INTEGER DEFAULT 0,
        ref_rewarded INTEGER DEFAULT 0,
        created_at INTEGER)""")
    q_exec("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, name TEXT, data TEXT, ts INTEGER)""")
    # Tasdiqlangan (anti-fraud'dan o'tgan) referallar — Leaderboard shu jadvaldan hisoblanadi
    q_exec("""CREATE TABLE IF NOT EXISTS referrals (
        invited_id INTEGER PRIMARY KEY,
        referrer_id INTEGER, contest_no INTEGER,
        score INTEGER, total INTEGER, seconds INTEGER, created_at INTEGER)""")
    q_exec("CREATE INDEX IF NOT EXISTS ix_referrals_contest ON referrals(contest_no, referrer_id)")
    q_exec("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    q_exec("""CREATE TABLE IF NOT EXISTS questions (
        question_id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill TEXT, part INTEGER, cefr_level TEXT, topic TEXT,
        question_type TEXT, difficulty INTEGER, grammar_tag TEXT,
        text TEXT, options TEXT, correct_answer TEXT, explanation TEXT)""")

    # AI tekshiruvlar tarixi (kunlik limit shu jadvaldan hisoblanadi)
    q_exec("""CREATE TABLE IF NOT EXISTS ai_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, skill TEXT, task TEXT, score INTEGER, level TEXT, day INTEGER, ts INTEGER)""")
    q_exec("CREATE INDEX IF NOT EXISTS ix_ai_checks_user_day ON ai_checks(user_id, day)")

    q_exec("UPDATE users SET state='ready' WHERE state='waiting_check'")

    # Telefon raqamlarda yo'qolgan «+» belgisini tiklash (Telegram ba'zan raqamni «+»siz beradi)
    for r in q_all("SELECT user_id, phone FROM users WHERE phone IS NOT NULL AND phone != ''"):
        fixed = normalize_phone(r["phone"])
        if fixed != r["phone"]:
            q_exec("UPDATE users SET phone=? WHERE user_id=?", (fixed, r["user_id"]))

    # Savollarni qayta yuklash (eski variantlar yangilansin)
    q_exec("DELETE FROM questions WHERE skill='Grammar'")
    for s in SEED_QUESTIONS:
        if not q_one("SELECT 1 FROM questions WHERE text=?", (s[7],)):
            q_exec("""INSERT INTO questions (skill,part,cefr_level,topic,question_type,difficulty,
                      grammar_tag,text,options,correct_answer,explanation) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   (*s[:8], json.dumps(s[8], ensure_ascii=False), s[9], s[10]))


init_db()


# =========================
# 🧰 YORDAMCHI FUNKSIYALAR
# =========================

def now():
    return int(time.time())


def date_str(ts):
    return time.strftime("%d.%m.%Y", time.localtime(ts))


def track(user_id, name, data=None):
    """Event tracking: user_started_test, q uestion_answered, test_completed,premium_clicked ..."""
    q_exec("INSERT INTO events (user_id,name,data,ts) VALUES (?,?,?,?)",
           (user_id, name, json.dumps(data or {}, ensure_ascii=False), now()))


def get_user(user_id):
    return q_one("SELECT * FROM users WHERE user_id=?", (user_id,))


def set_user(user_id, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    q_exec(f"UPDATE users SET {keys} WHERE user_id=?", (*fields.values(), user_id))


def registered_count():
    return q_one("SELECT COUNT(*) c FROM users WHERE state='ready'")["c"]


def active_users():
    """(oylik faol, bugungi faol) — events jadvalidan."""
    mau = q_one("SELECT COUNT(DISTINCT user_id) c FROM events WHERE ts>?", (now() - 30 * 86400,))["c"]
    dau = q_one("SELECT COUNT(DISTINCT user_id) c FROM events WHERE ts>?", (now() - 86400,))["c"]
    return mau, dau


def ref_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


def min_correct(total):
    return math.ceil(total * REFERRAL_MIN_PERCENT / 100)


def min_seconds(total):
    """Testga ketishi shart bo'lgan minimal vaqt (savollar 25 tadan kam bo'lsa, mutanosib kamayadi)."""
    return math.ceil(REFERRAL_MIN_SECONDS * min(total, GRAMMAR_QUESTIONS_PER_TEST) / GRAMMAR_QUESTIONS_PER_TEST)


def is_subscribed(user_id):
    try:
        st = bot.get_chat_member(KANAL_ID, user_id).status
        return st in ("member", "administrator", "creator")
    except Exception as e:
        print("Obunani tekshirish xatosi:", e)
        return False


def safe_send(chat_id, text, **kw):
    try:
        return bot.send_message(chat_id, text, **kw)
    except Exception as e:
        print("Yuborishda xato:", e)


# =========================
# 🧹 OSHIQCHA XABARLARNI AVTO-O'CHIRISH
# =========================
# Qoida: har bir foydalanuvchida bitta "ekran" xabari bo'ladi. Tugma bosilganda xabar
# o'sha joyida tahrirlanadi, yangi xabar kerak bo'lsa eskisi o'chadi. Foydalanuvchi yozgan
# ism/telefon/yosh va keraksiz xabarlar o'chiriladi, ogohlantirishlar bir necha soniyada yo'qoladi.

_screens = {}   # user_id -> oxirgi "ekran" xabar id


def tdelete(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def temp(chat_id, text, ttl=5, **kw):
    """Vaqtinchalik xabar: ttl soniyadan keyin o'zi o'chadi."""
    m = safe_send(chat_id, text, **kw)
    if m:
        t = threading.Timer(ttl, tdelete, (chat_id, m.message_id))
        t.daemon = True
        t.start()
    return m


def screen(uid, text, **kw):
    """Yangi ekran yuboradi va oldingisini o'chiradi (private chatda chat_id == user_id)."""
    old = _screens.pop(uid, None)
    m = safe_send(uid, text, **kw)
    if m:
        _screens[uid] = m.message_id
    if old:
        tdelete(uid, old)
    return m


def edit(chat_id, message_id, text, kb=None):
    """Xabarni joyida tahrirlaydi. Muvaffaqiyatli bo'lsa True."""
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        return True
    except Exception as e:
        if "not modified" in str(e):
            return True
        print("Tahrirlashda xato:", e)
        return False


def show(call, text, kb=None):
    """Tugma bosilganda: xabarni joyida almashtiradi (yangi xabar yaratmaydi)."""
    uid = call.from_user.id
    chat, mid = call.message.chat.id, call.message.message_id
    if edit(chat, mid, text, kb):
        _screens[uid] = mid
    else:
        screen(uid, text, reply_markup=kb)
        tdelete(chat, mid)


# =========================
# 🏆 PESHQADAMLAR (eng ko'p do'st taklif qilganlar)
# =========================

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}


def get_setting(key, default=None):
    r = q_one("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key, value):
    q_exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def leaderboard_rows():
    """Reyting: ko'p do'st -> avval shu songa yetgan -> ID. Faqat anti-fraud'dan o'tgan referallar sanaladi."""
    return q_all(
        """SELECT r.referrer_id AS user_id, COUNT(*) AS friends, MAX(r.created_at) AS last_ts,
                  u.full_name, u.username
           FROM referrals r LEFT JOIN users u ON u.user_id = r.referrer_id
           GROUP BY r.referrer_id
           ORDER BY friends DESC, last_ts ASC, r.referrer_id ASC""")


def my_position(rows, uid):
    """(o'rin, do'stlar soni); reytingda bo'lmasa (None, 0)."""
    for i, r in enumerate(rows, 1):
        if r["user_id"] == uid:
            return i, r["friends"]
    return None, 0


def display_name(row):
    """'Ism (@username)' ko'rinishi (HTML-xavfsiz)."""
    full = " ".join((row["full_name"] or "").split()) or "Foydalanuvchi"
    uname = f" (@{row['username']})" if row["username"] else ""
    return html.escape(full + uname)


def friends_count(uid):
    """Tasdiqlangan do'stlar soni — referrals jadvalidan (reyting bilan har doim bir xil)."""
    return q_one("SELECT COUNT(*) c FROM referrals WHERE referrer_id=?", (uid,))["c"]


def leaderboard_text(uid, with_rules=False):
    rows = leaderboard_rows()
    pos, _ = my_position(rows, uid)
    # Reyting jadvali cheklangan yoki yangilanayotgan paytda ham foydalanuvchi
    # o'zining referrals jadvalidagi haqiqiy sonni ko'rishi kerak.
    mine = friends_count(uid)
    out = [f"👑 <b>TOP-{LEADERBOARD_SIZE} Peshqadamlar</b> 👑",
           "(Eng ko'p do'st taklif qilganlar ro'yxati)", ""]
    if not rows:
        out.append("Hali hech kim do'st taklif qilmagan. Birinchi bo'ling! 🚀")
    for i, r in enumerate(rows[:LEADERBOARD_SIZE], 1):
        me = " 👈 <b>siz</b>" if r["user_id"] == uid else ""
        out.append(f"{MEDALS.get(i, f'{i}.')} {display_name(r)} — {r['friends']} ta do'st{me}")

    out += ["", "📊 <b>Sizning Reyting Ko'rsatkichlaringiz:</b>", "",
            f"👤 O'rningiz: <b>{pos}-o'rin</b>" if pos else "👤 O'rningiz: <b>Top-dan tashqarida</b>",
            f"👥 Taklif qilingan do'stlar: <b>{mine}</b> nafar"]

    if pos == 1:
        step = "📈 Oldinga siljish: 🔥 Siz 1-o'rindasiz! Yetakchilikni qo'ldan bermang."
    elif pos:
        above = rows[pos - 2]
        gap = above["friends"] - mine
        who = f"@{html.escape(above['username'])}" if above["username"] else display_name(above)
        if gap > 0:
            step = (f"{pos - 1}-o'rindagi {who}dan {gap} ta kamroq do'stingiz bor. "
                    f"O'zib ketish uchun yana {gap + 1} ta taklif qiling!")
        else:   # do'stlar soni teng, lekin u avvalroq yetgan
            step = (f"{pos - 1}-o'rindagi {who} bilan do'stlaringiz soni teng, lekin u avvalroq yetgan. "
                    "O'zib ketish uchun yana 1 ta taklif qiling!")
        step = "📈 Oldinga siljish: " + step
    else:
        threshold = rows[LEADERBOARD_SIZE - 1]["friends"] if len(rows) >= LEADERBOARD_SIZE else 0
        step = (f"📈 Oldinga siljish: TOP-{LEADERBOARD_SIZE} ga kirish uchun yana "
                f"{max(1, threshold - mine + 1)} ta do'st taklif qiling!")
    out.append(step)

    if with_rules:
        out += ["", f"ℹ️ Do'st sanalishi uchun u kanalga obuna bo'lib, Grammar Testni kamida {REFERRAL_MIN_SECONDS} "
                    f"soniya diqqat bilan yechib, {min_correct(GRAMMAR_QUESTIONS_PER_TEST)}/{GRAMMAR_QUESTIONS_PER_TEST} "
                    f"({REFERRAL_MIN_PERCENT}%) to'g'ri javob topishi kerak."]
    out += ["", "👉 Do'stlaringizni taklif qiling, bilim ulashing va reytingda birinchi bo'ling! 🚀"]
    return "\n".join(out)


def send_long(chat_id, lines, limit=3800):
    """Uzun ro'yxatni Telegram limitiga sig'adigan bo'laklarga bo'lib yuboradi."""
    chunk = ""
    for ln in lines:
        if chunk and len(chunk) + len(ln) + 1 > limit:
            safe_send(chat_id, chunk)
            chunk = ""
        chunk += ln + "\n"
    if chunk.strip():
        safe_send(chat_id, chunk)


# =========================
# 📝 MATNLAR
# =========================

def welcome_body(first_name):
    return (
        f"👋 Salom, {html.escape(first_name or 'do‘st')}!\n\n"
        "🎯 Solution X Bot’ga xush kelibsiz — Multilevel (CEFR) imtihonida B2/C1 darajaga erishishda "
        "sizning shaxsiy AI yordamchingiz! 🎓📚\n\n"
        "🎁 Platformaning barcha imkoniyatlari hozircha "
        "TO‘LIQ BEPUL!\n\n"
        "🚀 Bu yerda siz:\n"
        "• 🎯 AI Diagnostika orqali zaif nuqtalaringizni 15 daqiqada aniqlaysiz\n"
        "• 📅 14 kunlik shaxsiy o‘quv rejasiga (Personal Exam Plan) ega bo‘lasiz\n"
        "• ⚡️ Grammar Test va bo‘limlar bo‘yicha mashqlarni bajarib ballingizni oshirasiz\n"
        "• 🏆 Do‘stlaringizni taklif qilib, Peshqadamlar reytingida yuqori o‘rinlarni egallaysiz!"
    )


def welcome_ready(first_name):
    return welcome_body(first_name) + "\n\n👇 Hoziroq diagnostikadan o‘ting va tayyorgarlikni boshlang:"


ASK_NAME = ("\n\n📝 Iltimos, ism va familiyangizni kiriting "
            "(kiritgan nomingiz bilan sizni eslab qolamiz):")
NAME_TOO_SHORT = "⚠️ Ismingiz juda qisqa! Iltimos, ismingizni to‘liq kiriting."
NAME_TOO_LONG = "⚠️ Ism juda uzun! Iltimos, {n} belgidan oshirmay kiriting."
NAME_BAD_CHARS = "⚠️ Ismda faqat harflar bo‘lishi kerak (raqam va belgilarsiz)."
NAME_MIN_LETTERS = 3
NAME_MAX_LEN = 60
PHONE_BTN = "📲 Telefon raqamni ulashish"

READING_TEXT = (
    "🌟 <b>READING BO‘LIMI (O‘QISH)</b>\n\n"
    "Multilevel formatidagi matnlar bilan ishlash ko‘nikmangizni yangi bosqichga chiqaring! 📖\n\n"
    "✨ <b>Imtihon Formati:</b>\n\n"
    "🔹 Qismlar soni: 5 ta qism\n"
    "🔹 Savollar soni: 35 ta savol\n"
    "🔹 Asosiy maqsad: Kalit so‘zlarni tez va aniq topish, matnning mantiqiy mazmunini tushunish.\n\n"
    "📌 <b>Format Xususiyatlari:</b>\n\n"
    "• Har bir qism turlicha mavzular va savol turlarini qamrab oladi.\n"
    "• Javoblarni vaqt taqsimotiga rioya qilgan holda belgilang.\n\n"
    "💡 <b>Muvaffaqiyat Sirlari:</b>\n\n"
    "🎯 Matnni to‘liq o‘qishdan oldin savollar bilan tanishib chiqing.\n"
    "⏳ Vaqtni nazorat qiling — har bir qismga ajratilgan daqiqalarga e’tiborli bo‘ling."
)

LISTENING_TEXT = (
    "🎧 <b>LISTENING BO‘LIMI (TINGLAB TUSHUNISH)</b>\n\n"
    "Audio materiallar orqali xorijiy tilni idrok etish qobiliyatingizni sinovdan o‘tkazing! 🎧\n\n"
    "✨ <b>Imtihon Formati:</b>\n\n"
    "🔹 Qismlar soni: 6 ta qism\n"
    "🔹 Savollar soni: 35 ta savol\n"
    "🔹 Audio takrori: Har bir audiofayl 2 martadan eshittiriladi.\n\n"
    "📌 <b>Format Xususiyatlari:</b>\n\n"
    "• Avtentik va yarim avtentik materiallar.\n"
    "• Asosiy fikrlar, detallar va yashirin ma’nolarni aniqlash.\n\n"
    "💡 <b>Muvaffaqiyat Sirlari:</b>\n\n"
    "🎧 Audio boshlanishidan oldin berilgan 15-30 soniya ichida savollarni tezda ko‘zdan kechiring.\n"
    "🎯 Kalit so‘zlarga urg‘u bering va chalg‘ituvchi variantlarga berilmang."
)

SPEAKING_TEXT = (
    "🗣 <b>SPEAKING BO‘LIMI (OG‘ZAKI NUTQ)</b>\n\n"
    "AI yordamida nutqingizni va talaffusingizni sinovdan o‘tkazing! 🎙\n\n"
    "📌 <b>Format Xususiyatlari:</b>\n\n"
    "• Bot savol beradi, siz javobingizni ovozli xabar ko‘rinishida yuborasiz.\n"
    "• Tizim javobingizni matnga o‘girib, Multilevel mezonlari bo‘yicha baholaydi.\n\n"
    "⚠️ Ball — AI bergan taxminiy baho, rasmiy imtihon natijasi emas."
)

WRITING_TEXT = (
    "✍️ <b>WRITING BO‘LIMI (YOZMA NUTQ)</b>\n\n"
    "Topshiriqlarni bajaring va yozma nutqingizni professional darajada tekshirtiring! 📝\n\n"
    "📌 <b>Format Xususiyatlari:</b>\n\n"
    "• Bot sizga topshiriq beradi, siz matn ko‘rinishida javob yuborasiz.\n"
    "• AI matningizni tekshirib, xatolaringizni tushuntiradi.\n\n"
    "⚠️ Ball — AI bergan taxminiy baho, rasmiy imtihon natijasi emas."
)

SECTIONS = {
    "reading": ("📖 Reading", READING_TEXT),
    "writing": ("✍️ Writing", WRITING_TEXT),
    "speaking": ("🗣 Speaking", SPEAKING_TEXT),
    "listening": ("🎧 Listening", LISTENING_TEXT),
}


PART_SKILLS = ("reading", "listening")
PARTS_COUNT = {"reading": 5, "listening": 6}   # Reading — 5 ta part, Listening — 6 ta part
SKILL_NAME = {"reading": "Reading", "listening": "Listening"}
PART_PICK_HINT = ("\n\n👇 Partlarni tanlang. Bir nechtasini belgilash mumkin — "
                  "belgilangan partni qayta bossangiz belgi o‘chadi.")
part_sel = {}         # (uid, skill) -> {part_no, ...} — foydalanuvchi belgilagan partlar (saqlanib turadi)
exam_sessions = {}    # uid -> Reading/Listening mashq sessiyasi (xotirada)
_mat_cache = {}       # (skill, part) -> [material, ...]
_mat_seen = {}        # (uid, skill, part) -> ko'rilgan material fayllari (takrorlanmasligi uchun)

esc = html.escape


# ---------------------------------------------------------------------------
# 📂 MATERIALLAR (materials/<skill>/part<N>/*.json)
# ---------------------------------------------------------------------------

def question_options(mat, q):
    """Savolning variantlari: o'zining 'options' i yoki partning umumiy 'bank' i."""
    return q.get("options") or mat.get("bank") or {}


def _check_material(d, where):
    qs = d.get("questions")
    if not isinstance(qs, list) or not qs:
        raise ValueError("'questions' bo'sh")
    for i, q in enumerate(qs, 1):
        opts = question_options(d, q)
        if q.get("answer") not in opts:
            raise ValueError(f"{i}-savol: 'answer' variantlar ichida yo'q")
    if d.get("script") and not d.get("audio"):
        raise ValueError("'script' bor, lekin 'audio' fayl nomi yo'q")


def load_materials(skill, part):
    """Part papkasidagi barcha to'g'ri materiallar. Natija keshlanadi (/reload_materials bilan yangilanadi)."""
    key = (skill, part)
    if key in _mat_cache:
        return _mat_cache[key]
    folder = os.path.join(MATERIALS_DIR, skill, f"part{part}")
    items = []
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, fn), encoding="utf-8") as f:
                    d = json.load(f)
                _check_material(d, fn)
                d["_dir"], d["_file"] = folder, fn
                items.append(d)
            except Exception as e:
                print(f"Materialni o'qishda xato ({skill}/part{part}/{fn}):", e)
    _mat_cache[key] = items
    return items


def part_qcount(skill, part):
    items = load_materials(skill, part)
    return len(items[0]["questions"]) if items else 0


def pick_material(uid, skill, part):
    """Foydalanuvchiga hali ko'rsatilmagan materialni beradi (hammasi ko'rilsa, qaytadan boshlanadi)."""
    items = load_materials(skill, part)
    if not items:
        return None
    seen = _mat_seen.setdefault((uid, skill, part), set())
    fresh = [m for m in items if m["_file"] not in seen]
    if not fresh:
        seen.clear()
        fresh = items
    m = random.choice(fresh)
    seen.add(m["_file"])
    return m


# ---------------------------------------------------------------------------
# ☑️ PART TANLASH EKRANI
# ---------------------------------------------------------------------------

def chosen_parts(uid, skill):
    return part_sel.setdefault((uid, skill), set())


def parts_kb(skill, chosen):
    """Part tugmalari (Reading — 5 ta, Listening — 6 ta; 3 tadan qatorda). Har bir part mustaqil belgilanadi (✅). Pastda
    «Boshlash» va «Asosiy menyu»."""
    m = types.InlineKeyboardMarkup(row_width=3)
    m.add(*[types.InlineKeyboardButton(("✅ " if n in chosen else "") + f"Part {n}",
                                       callback_data=f"pp_{skill}_{n}")
            for n in range(1, PARTS_COUNT[skill] + 1)])
    start = "▶️ Boshlash" + (f" ({len(chosen)} ta part)" if chosen else "")
    m.row(types.InlineKeyboardButton(start, callback_data=f"pgo_{skill}"))
    m.row(types.InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_home"))
    return m


def picker_text(skill, chosen):
    text = SECTIONS[skill][1]
    if chosen:
        nums = sorted(chosen)
        total = sum(part_qcount(skill, n) for n in nums)
        text += (f"\n\n✅ <b>Tanlangan:</b> {', '.join('Part ' + str(n) for n in nums)} "
                 f"· jami <b>{total}</b> ta savol")
    else:
        text += "\n\n☑️ Hali part tanlanmagan."
    return text + PART_PICK_HINT


def grammar_intro_text(user):
    text = (
        "⚡️ <b>Grammar Test</b>\n\n"
        "Grammatika bilimingizni tezkor sinab ko‘ring! 🎯\n\n"
        "📋 <b>Test haqida:</b>\n"
        f"• ❓ Savollar soni: {GRAMMAR_QUESTIONS_PER_TEST} ta\n"
        f"• ⏱️ Vaqt: {GRAMMAR_MINUTES} daqiqa\n"
        "• 📶 Darajalar: A2 → B1 → B2 → C1 & C2\n\n"
        f"💡 Eslatma: Do‘stingizni taklif qilganingizda ochko berilishi uchun u ushbu testni kamida "
        f"{REFERRAL_MIN_SECONDS} soniya diqqat bilan yechib, "
        f"{min_correct(GRAMMAR_QUESTIONS_PER_TEST)} ta ({REFERRAL_MIN_PERCENT}%) to‘g‘ri javob topishi kerak."
    )
    return text + "\n\n👇 Avval darajangizni tanlang:"


def test_status_note(u):
    if not u["referrer_id"]:
        return ""
    if u["ref_rewarded"]:
        return "✅ Test natijangiz sizni taklif qilgan do'stingizga ochko keltirdi!"
    return (f"⏳ Sizni taklif qilgan do'stingizga ochko berilishi uchun Grammar Testni kamida "
            f"{REFERRAL_MIN_SECONDS} soniya diqqat bilan yechib, "
            f"{min_correct(GRAMMAR_QUESTIONS_PER_TEST)} ta ({REFERRAL_MIN_PERCENT}%) to'g'ri javob toping.")


def completed_tests(uid):
    """Yakunlangan testlar: Grammar, Reading, Listening va AI (Writing/Speaking) tekshiruvlari."""
    return q_one("SELECT COUNT(*) c FROM events WHERE user_id=? AND name IN ('test_completed','ai_check')",
                 (uid,))["c"]


def profile_text(u, uid):
    uname = f"@{html.escape(u['username'])}" if u["username"] else "—"
    note = test_status_note(u)
    return (
        "👤 <b>Profilingiz Ma'lumotlari</b>\n\n"
        f"🆔 Ism: <b>{html.escape(u['full_name'] or '')}</b>\n"
        f"ℹ️ Username: {uname}\n"
        f"🆔 ID: <code>{uid}</code>\n\n"
        "📈 <b>Umumiy yutuqlar:</b>\n"
        f"📚 Jami yechilgan testlar: <b>{completed_tests(uid)}</b> ta (25 talik to'liq bosqichlar)\n\n"
        "🎁 <b>Referral Tizimi Holati:</b>\n"
        f"👥 Taklif qilingan do'stlar: <b>{friends_count(uid)}</b> nafar\n"
        f"🔗 Shaxsiy havolangiz: <code>{ref_link(uid)}</code>"
        + (f"\n\n{note}" if note else "")
    )


# =========================
# 🎨 KLAVIATURALAR
# =========================

def main_menu(uid=None):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("📖 Reading", callback_data="reading"),
        types.InlineKeyboardButton("✍️ Writing", callback_data="writing"),
        types.InlineKeyboardButton("🗣 Speaking", callback_data="speaking"),
        types.InlineKeyboardButton("🎧 Listening", callback_data="listening"),
        types.InlineKeyboardButton("⚡️ Grammar Test", callback_data="grammar"),
        types.InlineKeyboardButton("🎁 Referal", callback_data="referral"),
        types.InlineKeyboardButton("👤 Profil", callback_data="profile"),               
    )
    return m


def back_btn(data="back_home", text="🔙 Asosiy menyu"):
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton(text, callback_data=data))
    return m


def phone_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    m.add(types.KeyboardButton(PHONE_BTN, request_contact=True))
    return m


# =========================
# 🚦 OBUNA + RO'YXATDAN O'TISH OQIMI
# =========================

def send_sub_message(uid):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=KANAL_HAVOLA),
          types.InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub"))
    screen(uid,
           "🔒 <b>Botdan foydalanish uchun kanalimizga obuna bo'ling!</b>\n\n"
           "1️⃣ Kanalga kiring.\n2️⃣ Obuna bo'ling.\n"
           "3️⃣ «✅ Obunani tekshirish» tugmasini bosing.",
           reply_markup=m)


def proceed(uid, first_name=None):
    """Foydalanuvchini keyingi bosqichga olib boradi (obuna -> ism -> telefon -> yosh -> menyu)."""
    if not is_subscribed(uid):
        send_sub_message(uid)
        return
    u = get_user(uid)
    state = u["state"]
    if state in ("new", "ism"):
        set_user(uid, state="ism")
        screen(uid, welcome_body(first_name) + ASK_NAME, reply_markup=types.ReplyKeyboardRemove())
    elif state == "telefon":
        screen(uid, "📲 Pastdagi «Telefon raqamni ulashish» tugmasini bosing 👇", reply_markup=phone_kb())
    elif state == "yosh":
        screen(uid, "🎂 Yoshingizni kiriting.\n📝 Masalan: 16", reply_markup=types.ReplyKeyboardRemove())
    else:
        screen(uid, welcome_ready(first_name), reply_markup=main_menu(uid))


def finish_registration(uid):
    u = get_user(uid)
    set_user(uid, state="ready")
    track(uid, "registration_completed")

    # Guruhga xabar
    try:
        bot.send_message(
            GROUP_ID,
            "🎉 <b>YANGI FOYDALANUVCHI!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Ism-familiya:</b> {html.escape(u['full_name'])}\n"
            f"📱 <b>Telefon:</b> {html.escape(normalize_phone(u['phone']))}\n"
            f"🎂 <b>Yosh:</b> {u['age']}\n"
            f"🔗 <b>Taklif qilgan:</b> {u['referrer_id'] or '—'}\n\n"
            "━━━━━━━━━━━━━━━━━━\n✅ Ro'yxatdan o'tish yakunlandi!")
    except Exception as e:
        print("Guruhga yuborishda xato:", e)

    # Referal mukofoti bu yerda berilmaydi — do'st Grammar Testda yetarli ball olganda beriladi.
    screen(uid,
           f"🎊 Tabriklaymiz, <b>{html.escape(u['full_name'])}</b>!\n\n"
           "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n"
           "🎁 Hozircha barcha bo'limlar <b>to'liq bepul</b>!\n\n"
           "👥 Do'stlaringizni taklif qilib, Peshqadamlar reytingida yuqoriga ko'tariling!",
           reply_markup=main_menu(uid))


# =========================
# 🚀 /start
# =========================

@bot.message_handler(commands=["start"], chat_types=["private"])
def cmd_start(message):
    uid = message.from_user.id
    tdelete(message.chat.id, message.message_id)
    parts = message.text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if not get_user(uid):
        referrer = None
        if arg.startswith("ref_") and arg[4:].isdigit():
            r = int(arg[4:])
            if r != uid and get_user(r):   # o'zini o'zi taklif qila olmaydi
                referrer = r
        q_exec("INSERT INTO users (user_id, username, state, referrer_id, created_at) VALUES (?,?,?,?,?)",
               (uid, message.from_user.username, "new", referrer, now()))
        track(uid, "user_started", {"referrer": referrer})

    proceed(uid, message.from_user.first_name)


# =========================
# 📝 RO'YXATDAN O'TISH BOSQICHLARI
# =========================

def state_is(*states):
    def check(m):
        u = get_user(m.from_user.id)
        return bool(u) and u["state"] in states
    return check


@bot.message_handler(content_types=["text"], chat_types=["private"],
                     func=lambda m: state_is("ism")(m) and not (m.text or "").startswith("/"))
def on_name(message):
    uid = message.from_user.id
    tdelete(message.chat.id, message.message_id)
    name = " ".join((message.text or "").split())
    letters = sum(ch.isalpha() for ch in name)
    if letters < NAME_MIN_LETTERS:
        temp(uid, NAME_TOO_SHORT)
        return
    if len(name) > NAME_MAX_LEN:
        temp(uid, NAME_TOO_LONG.format(n=NAME_MAX_LEN))
        return
    if any(not (ch.isalpha() or ch in " '`‘’ʻʼ.-") for ch in name):
        temp(uid, NAME_BAD_CHARS)
        return
    set_user(uid, full_name=name, state="telefon")
    screen(uid, "Ajoyib! ✅\n\n📲 Endi pastdagi «Telefon raqamni ulashish» tugmasini bosing 👇", reply_markup=phone_kb())


@bot.message_handler(content_types=["contact"], chat_types=["private"], func=state_is("telefon"))
def on_contact(message):
    uid = message.from_user.id
    tdelete(message.chat.id, message.message_id)
    if message.contact.user_id is not None and message.contact.user_id != uid:
        temp(uid, "⚠️ Iltimos, o'zingizning raqamingizni ulashing.")
        return
    set_user(uid, phone=normalize_phone(message.contact.phone_number), state="yosh")
    screen(uid, "📱 Qabul qilindi ✅\n\n🎂 Yoshingizni kiriting.\n📝 Masalan: 16",
           reply_markup=types.ReplyKeyboardRemove())


@bot.message_handler(content_types=["text"], chat_types=["private"],
                     func=lambda m: state_is("yosh")(m) and not (m.text or "").startswith("/"))
def on_age(message):
    uid = message.from_user.id
    tdelete(message.chat.id, message.message_id)
    t = message.text.strip()
    if not t.isdigit() or not 5 <= int(t) <= 100:
        temp(uid, "⚠️ Yoshni 5 dan 100 gacha raqam bilan kiriting.")
        return
    set_user(uid, age=int(t))
    finish_registration(uid)


# =========================
# 🔘 TUGMALAR (callback)
# =========================

def ack(call, text=None, alert=False):
    """Callback so'roviga bir marta javob beradi (ikkinchi chaqiruv e'tiborsiz qoldiriladi)."""
    if getattr(call, "_acked", False):
        return
    call._acked = True
    try:
        bot.answer_callback_query(call.id, text, show_alert=alert)
    except Exception as e:
        print("answer_callback_query xatosi:", e)


# =========================
# 📝 READING / LISTENING MASHQ SESSIYASI
# =========================
# Oqim: partlarni belgilash -> «Boshlash» -> materiallar (matn/savollar, listeningda audio tugmasi)
#       -> «Tugatish» -> javoblar varag'i (har bir partdagi savollar soni bo'yicha variant tanlanadi)
#       -> natija + xatolar tahlili (listeningda transcript ham).

_pick_lock = threading.Lock()
_exam_lock = threading.Lock()
MSG_LIMIT = 3800


def fmt_secs(sec):
    m, s = divmod(int(sec), 60)
    return f"{m} daq {s} soniya" if m else f"{s} soniya"


def plain(text, n=55):
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n - 1] + "…"


def _split_long(text, limit):
    """Juda uzun blokni xatboshi / gap chegarasida bo'laklaydi."""
    out = []
    for para in text.split("\n\n"):
        while len(para) > limit:
            cut = para.rfind(". ", 0, limit)
            cut = cut + 1 if cut > 0 else limit
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def chunk_blocks(blocks, limit=MSG_LIMIT):
    """Bloklarni Telegram limitiga (4096) sig'adigan xabarlarga yig'adi."""
    out, cur = [], ""
    for b in blocks:
        for piece in ([b] if len(b) <= limit else _split_long(b, limit)):
            if cur and len(cur) + len(piece) + 2 > limit:
                out.append(cur)
                cur = ""
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


def is_gap(mat):
    """Part 1 (gap filling): javob harfi emas, so'z tanlanadi (ochiladigan ro'yxat kabi)."""
    return mat.get("answer_style") == "dropdown"


def opt_text(mat, q, k):
    """Variant matni (gap / True-False uchun faqat so'z, boshqalarda 'A) matn')."""
    v = question_options(mat, q).get(k, "")
    if mat.get("answer_style") in ("dropdown", "words"):
        return v
    return f"{k}) {v}" if v else str(k)


def gap_sentence(mat, k, fill=None):
    """Matndagi (k) ______ bo'shliq turgan gapni qaytaradi (fill berilsa, bo'shliq shu so'z bilan to'ldiriladi)."""
    marker = re.compile(rf"\({k}\)\s*_+")
    for b in mat.get("blocks", []):
        for sent in re.split(r"(?<=[.!?])\s+", (b.get("text") or "").replace("\n", " ")):
            if marker.search(sent):
                new = f"<b>{esc(fill)}</b>" if fill else "<b>[ ______ ]</b>"
                return marker.sub(new, esc(sent.strip()))
    return ""


def material_blocks(skill, n, mat, off=0):
    icon = "📖" if skill == "reading" else "🎧"
    nq = len(mat["questions"])
    head = (f"{icon} <b>{SKILL_NAME[skill].upper()} · PART {n}</b>\n"
            f"Questions {off + 1}–{off + nq}  ·  Time: ~{mat.get('minutes', '?')} min")
    if mat.get("title") and not mat.get("blocks"):
        head += f"\n<b>{esc(mat['title'])}</b>"
    if mat.get("instructions"):
        head += f"\n\n<i>{esc(mat['instructions'])}</i>"
    if skill == "listening":
        head += (f"\n\n🎧 Read the questions first, then press «▶️ Audio». "
                 f"Each recording is played {AUDIO_MAX_PLAYS} times only.")
    blocks = [head]
    for b in mat.get("blocks", []):
        text = esc(b.get("text", ""))
        blocks.append(f"<b>{esc(b['title'])}</b>\n{text}" if b.get("title") else text)
    bank = mat.get("bank")
    gap = is_gap(mat)
    if bank and not mat.get("hide_bank"):
        title = esc(mat.get("bank_title") or "Options")
        if gap:
            blocks.append(f"<b>{title}</b>\n" + "\n".join(f"▫️ {esc(v)}" for v in bank.values()))
        else:
            blocks.append(f"<b>{title}</b>\n" + "\n".join(f"<b>{k}.</b> {esc(v)}" for k, v in bank.items()))
    if not gap:                                   # gap filling'da savollar matn ichida (1)–(6) bo'shliqlar
        qlines = [f"<b>Questions {off + 1}–{off + nq}</b>"]
        for i, q in enumerate(mat["questions"], 1):
            qlines.append(f"\n<b>{off + i}.</b> {esc(q['q'])}")
            for k, v in (q.get("options") or {}).items():
                qlines.append(f"    <b>{k})</b> {esc(v)}")
        blocks.append("\n".join(qlines))
    return blocks


def send_material(uid, s, n):
    for chunk in chunk_blocks(material_blocks(s["skill"], n, s["mats"][n], s["off"].get(n, 0))):
        m = safe_send(uid, chunk, disable_web_page_preview=True)
        if m:
            s["msgs"].append(m.message_id)


def panel_text(s):
    skill, parts = s["skill"], s["parts"]
    total = sum(len(s["mats"][p]["questions"]) for p in parts)
    mins = sum(int(s["mats"][p].get("minutes") or 0) for p in parts)
    icon = "📖" if skill == "reading" else "🎧"
    text = (f"{icon} <b>{SKILL_NAME[skill].upper()}</b> — {', '.join('Part ' + str(p) for p in parts)}\n"
            f"Questions: <b>{total}</b>  ·  Recommended time: ~{mins} min\n\n")
    if skill == "reading":
        text += "Read the texts above carefully. When you are ready, press «📝 Answer sheet»."
    else:
        text += (f"Read the questions, then press «▶️ Audio» (each recording is played {AUDIO_MAX_PLAYS} times). "
                 "When you have finished listening, press «📝 Answer sheet».")
    if s.get("skipped"):
        text += f"\n\n⚠️ No material yet for Part {', '.join(map(str, s['skipped']))} — skipped."
    return text


def panel_kb(s):
    skill = s["skill"]
    m = types.InlineKeyboardMarkup()
    for p in s["parts"]:
        if skill == "listening":
            left = AUDIO_MAX_PLAYS - s["plays"].get(p, 0)
            label = f"▶️ Part {p} audio ({left} left)" if left > 0 else f"🔇 Part {p} audio (finished)"
            m.row(types.InlineKeyboardButton(label, callback_data=f"ex_play_{skill}_{p}"),
                  types.InlineKeyboardButton("📄 Questions", callback_data=f"ex_mat_{skill}_{p}"))
        else:
            m.row(types.InlineKeyboardButton(f"📄 Part {p} text & questions", callback_data=f"ex_mat_{skill}_{p}"))
    m.row(types.InlineKeyboardButton("📝 Answer sheet", callback_data=f"ex_fin_{skill}"))
    m.row(types.InlineKeyboardButton("🔙 Back to parts", callback_data=skill))
    return m


def send_panel(uid, s):
    """Boshqaruv panelini eng pastda qayta chiqaradi (eskisi o'chadi)."""
    screen(uid, panel_text(s), reply_markup=panel_kb(s))


def end_exam(uid):
    """Sessiyani yopadi va yuborilgan material/audio xabarlarini o'chiradi."""
    s = exam_sessions.pop(uid, None)
    if s:
        for mid in s["msgs"]:
            tdelete(uid, mid)


def start_exam(call, skill):
    uid = call.from_user.id
    chosen = sorted(chosen_parts(uid, skill))
    if not chosen:
        ack(call, "⚠️ Avval kamida bitta part tanlang!", True)
        return
    ack(call)
    mats, skipped = {}, []
    for n in chosen:
        m = pick_material(uid, skill, n)
        if m:
            mats[n] = m
        else:
            skipped.append(n)
    if not mats:
        show(call, "🚧 Tanlangan partlar uchun materiallar hali qo‘shilmagan.",
             back_btn(skill, "🔙 Partlarga qaytish"))
        return
    end_exam(uid)
    offs = {n: 0 for n in mats}             # har bir part 1 dan boshlanadi (topshiriqdagi "(1–6)" bilan mos)
    s = {"skill": skill, "parts": sorted(mats), "mats": mats, "skipped": skipped,
         "ans": {p: {} for p in mats}, "plays": {}, "msgs": [], "t0": time.time(),
         "cur": min(mats), "done": False, "off": offs}
    exam_sessions[uid] = s
    track(uid, "daily_practice_started", {"skill": skill, "parts": s["parts"]})
    for p in s["parts"]:
        send_material(uid, s, p)
    send_panel(uid, s)                                   # eski «part tanlash» xabari shu yerda o'chadi
    tdelete(call.message.chat.id, call.message.message_id)


def send_part_audio(uid, s, n):
    """Part audiosini yuboradi. Birinchi yuborishdan keyin Telegram file_id saqlanadi (keyingilari tez)."""
    mat = s["mats"][n]
    path = os.path.join(mat["_dir"], mat.get("audio") or "")
    if not mat.get("audio") or not os.path.isfile(path):
        safe_send(uid, "⚠️ Bu part uchun audio fayl topilmadi. Iltimos, adminga xabar bering.")
        return False
    cap = (f"🎧 <b>Listening · Part {n}</b> — {esc(mat.get('title', ''))}\n"
           f"▶️ Eshittirish: {s['plays'].get(n, 0) + 1}/{AUDIO_MAX_PLAYS}")
    key = f"fid:{os.path.relpath(path, BASE_DIR)}:{int(os.path.getmtime(path))}"
    fid = get_setting(key)
    msg = None
    if fid:
        try:
            msg = bot.send_audio(uid, fid, caption=cap, title=mat.get("title"), performer="Solution X")
        except Exception as e:
            print("file_id bilan yuborib bo'lmadi, fayl qayta yuklanadi:", e)
    if msg is None:
        try:
            with open(path, "rb") as f:
                msg = bot.send_audio(uid, f, caption=cap, title=mat.get("title"), performer="Solution X")
            if msg and msg.audio:
                set_setting(key, msg.audio.file_id)
        except Exception as e:
            print("Audio yuborishda xato:", e)
            safe_send(uid, "⚠️ Audioni yuborib bo'lmadi. Birozdan keyin qayta urinib ko'ring.")
            return False
    s["msgs"].append(msg.message_id)
    return True


# ---- javoblar varag'i ----

def sheet_text(s):
    p = s["cur"]
    mat = s["mats"][p]
    qs, ans, off = mat["questions"], s["ans"][p], s["off"].get(p, 0)
    style = mat.get("answer_style")
    lines = [f"📝 <b>ANSWER SHEET</b> — {SKILL_NAME[s['skill']].upper()}",
             f"<b>Part {p}</b> · Questions {off + 1}–{off + len(qs)} · answered: <b>{len(ans)}/{len(qs)}</b>", ""]
    for i, q in enumerate(qs, 1):
        opts = question_options(mat, q)
        mark = ""
        if i in ans:
            mark = f" → <b>{esc(opts.get(ans[i], '')) if style else ans[i]}</b>"
        label = f"Gap {i}" if style == "dropdown" else esc(plain(q["q"], 60))
        lines.append(f"<b>{off + i}.</b> {label}{mark}")
    lines += ["", "👆 Tap a gap number to choose a word." if style == "dropdown"
              else "👆 Choose an answer. Tap it again to remove it."]
    if len(s["parts"]) > 1:
        done = sum(len(a) for a in s["ans"].values())
        total = sum(len(m["questions"]) for m in s["mats"].values())
        lines.append(f"📊 Total answered: {done}/{total}")
    return "\n".join(lines)


def sheet_kb(s):
    skill, p = s["skill"], s["cur"]
    mat = s["mats"][p]
    off = s["off"].get(p, 0)
    style = mat.get("answer_style")
    m = types.InlineKeyboardMarkup()
    if len(s["parts"]) > 1:
        m.row(*[types.InlineKeyboardButton(
            ("🔹" if q == p else "") + f"P{q} {len(s['ans'][q])}/{len(s['mats'][q]['questions'])}",
            callback_data=f"at_{skill}_{q}") for q in s["parts"]])
    for i, q in enumerate(mat["questions"], 1):
        cur = s["ans"][p].get(i)
        opts = question_options(mat, q)
        if style == "dropdown":
            label = f"{off + i}.  " + (opts[cur] if cur in opts else "▾ choose a word")
            m.row(types.InlineKeyboardButton(("✅ " if cur in opts else "") + label,
                                             callback_data=f"dd_{skill}_{p}_{i}"))
            continue
        btns = [types.InlineKeyboardButton(("✅" if k == cur else "") + (v if style == "words" else k),
                                           callback_data=f"an_{skill}_{p}_{i}_{k}")
                for k, v in opts.items()]
        num = types.InlineKeyboardButton(f"{off + i}.", callback_data="noop")
        if len(btns) <= 6:
            m.row(num, *btns)
        else:                         # 7-8 ta variant (A–H) bitta qatorga sig'maydi
            m.row(num)
            m.row(*btns)
    m.row(types.InlineKeyboardButton("🏁 Finish", callback_data=f"ex_done_{skill}"))
    m.row(types.InlineKeyboardButton("↩️ Back to materials", callback_data=f"ex_back_{skill}"))
    return m


def dropdown_text(s, p, i):
    mat = s["mats"][p]
    off = s["off"].get(p, 0)
    cur = s["ans"][p].get(i)
    opts = question_options(mat, mat["questions"][i - 1])
    text = f"📝 <b>Part {p} · Gap {off + i}</b>\n\n"
    sent = gap_sentence(mat, i, opts.get(cur) if cur in opts else None)
    if sent:
        text += f"{sent}\n\n"
    return text + "Choose the word that best fits the gap."


def dropdown_kb(s, p, i):
    skill = s["skill"]
    mat = s["mats"][p]
    cur = s["ans"][p].get(i)
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(*[types.InlineKeyboardButton(("✅ " if k == cur else "") + v, callback_data=f"an_{skill}_{p}_{i}_{k}")
            for k, v in question_options(mat, mat["questions"][i - 1]).items()])
    m.row(types.InlineKeyboardButton("↩️ Answer sheet", callback_data=f"at_{skill}_{p}"))
    return m


def unanswered(s):
    return sum(len(s["mats"][p]["questions"]) - len(s["ans"][p]) for p in s["parts"])


def grade_exam(s):
    per, tot_c, tot_q = {}, 0, 0
    for p in s["parts"]:
        qs = s["mats"][p]["questions"]
        wrong = [(i, q, s["ans"][p].get(i)) for i, q in enumerate(qs, 1) if s["ans"][p].get(i) != q["answer"]]
        c = len(qs) - len(wrong)
        per[p] = (c, len(qs), wrong)
        tot_c += c
        tot_q += len(qs)
    return per, tot_c, tot_q


def verdict(pct):
    if pct >= 85:
        return "🔥 Ajoyib natija!"
    if pct >= 65:
        return "👍 Yaxshi, shu tempda davom eting!"
    if pct >= 40:
        return "💪 Yomon emas — xatolarni tahlil qilib, yana urinib ko‘ring."
    return "📚 Ko‘proq mashq kerak. Xatolar tahlilini o‘qib chiqing."


def finish_exam(call, s):
    uid = call.from_user.id
    skill = s["skill"]
    s["done"] = True
    elapsed = time.time() - s["t0"]
    per, tot_c, tot_q = grade_exam(s)
    track(uid, "test_completed", {"skill": SKILL_NAME[skill], "parts": s["parts"], "score": tot_c,
                                  "total": tot_q, "seconds": round(elapsed)})
    for mid in s["msgs"]:                 # material va audio xabarlari endi kerak emas
        tdelete(uid, mid)
    s["msgs"] = []

    # 1) xatolar tahlili (alohida xabarlar): savol, sizning javobingiz, to'g'ri javob va sababi
    review = []
    for p in s["parts"]:
        mat, (c, t, wrong) = s["mats"][p], per[p]
        if not wrong:
            continue
        off = s["off"].get(p, 0)
        review.append(f"<b>Part {p}</b> — xatolar ({len(wrong)} ta):\n")
        for i, q, a in wrong:
            right = q["answer"]
            if is_gap(mat):
                body = gap_sentence(mat, i, question_options(mat, q).get(right)) or f"Gap {i}"
            else:
                body = esc(plain(q["q"], 160))
            mine = esc(opt_text(mat, q, a)) if a else "javob berilmagan"
            review.append(f"❌ <b>{off + i}.</b> {body}\n"
                          f"   🔸 Sizning javobingiz: {mine}\n"
                          f"   ✅ To‘g‘ri javob: <b>{esc(opt_text(mat, q, right))}</b>\n"
                          f"   💡 <b>Tushuntirish:</b> {esc(q.get('why', '') or '—')}\n")
    parts_line = " · ".join(f"Part {p}: <b>{per[p][0]}/{per[p][1]}</b>" for p in s["parts"])
    send_long(uid, [f"🔍 <b>Xatolar tahlili — {SKILL_NAME[skill]}</b>", f"📌 {parts_line}", ""]
              + (review or ["🎉 Barcha javoblar to‘g‘ri!"]))

    # 2) natija ekrani (shablon) — partlar bo'yicha natija xatolar tahlilida ham ko'rsatiladi
    pct = round(tot_c * 100 / tot_q) if tot_q else 0
    lines = [completion_text(SKILL_NAME[skill], tot_c, tot_q, pct)]
    kb = types.InlineKeyboardMarkup(row_width=3)
    if skill == "listening":
        kb.add(*[types.InlineKeyboardButton(f"📜 Part {p} transcript", callback_data=f"ex_tr_{skill}_{p}")
                 for p in s["parts"]])
    kb.row(types.InlineKeyboardButton("🔁 Qayta urinish", callback_data=f"pgo_{skill}"))
    kb.row(types.InlineKeyboardButton("🔙 Partlarga qaytish", callback_data=skill))
    kb.row(types.InlineKeyboardButton("🏠 Asosiy menyu", callback_data="back_home"))
    screen(uid, "\n".join(lines), reply_markup=kb)        # javoblar varag'i xabari shu yerda o'chadi


def transcript_lines(mat):
    out = []
    for seg in mat.get("script", []):
        t, v = seg.get("t"), seg.get("v", "N")
        if not t:
            continue
        if v == "N":
            out.append(f"🔊 <i>{esc(t)}</i>\n")
        else:
            out.append(("👩 " if v.startswith("F") else "👨 ") + esc(t) + "\n")
    return out


def exam_cb(call, data):
    """ex_* / at_* / an_* tugmalari (mashq sessiyasi)."""
    uid = call.from_user.id
    p = data.split("_")
    kind = p[0]
    if kind == "ex":
        action, skill, arg = p[1], p[2], (p[3] if len(p) > 3 else None)
    else:
        action, skill, arg = kind, p[1], p[2:]
    s = exam_sessions.get(uid)

    # Natijadan keyin transcript (sessiya "done" holatida)
    if kind == "ex" and action == "tr":
        n = int(arg) if arg and arg.isdigit() else 0
        if not s or s["skill"] != skill or not s["done"] or n not in s["mats"] or not s["mats"][n].get("script"):
            ack(call, "⌛️ Transcript topilmadi.", True)
            return
        ack(call)
        send_long(uid, [f"📜 <b>Listening · Part {n} — transcript</b>\n"] + transcript_lines(s["mats"][n]))
        return

    if not s or s["skill"] != skill or s["done"] or skill not in PART_SKILLS:
        ack(call, "⌛️ Sessiya topilmadi. Partlarni tanlab, qaytadan boshlang.", True)
        return
    chat, mid = call.message.chat.id, call.message.message_id

    if kind == "dd":
        try:
            part, i = int(arg[0]), int(arg[1])
            s["mats"][part]["questions"][i - 1]
        except (ValueError, KeyError, IndexError):
            ack(call)
            return
        if i < 1:
            ack(call)
            return
        ack(call)
        edit(chat, mid, dropdown_text(s, part, i), dropdown_kb(s, part, i))
        return

    if kind == "an":
        try:
            part, i, letter = int(arg[0]), int(arg[1]), arg[2]
            mat = s["mats"][part]
            q = mat["questions"][i - 1]
        except (ValueError, KeyError, IndexError):
            ack(call)
            return
        if i < 1 or letter not in question_options(mat, q):
            ack(call)
            return
        ack(call)
        with _exam_lock:
            cur = s["ans"][part]
            if cur.get(i) == letter:
                del cur[i]                    # qayta bosildi -> belgi o'chadi
            else:
                cur[i] = letter
            s["cur"] = part
            edit(chat, mid, sheet_text(s), sheet_kb(s))
        return

    if kind == "at":
        n = int(arg[0]) if arg and arg[0].isdigit() else 0
        ack(call)
        if n in s["mats"]:
            s["cur"] = n
            edit(chat, mid, sheet_text(s), sheet_kb(s))
        return

    # --- ex_<action>_... ---
    n = int(arg) if arg and arg.isdigit() else None
    if action == "play":
        if skill != "listening" or n not in s["mats"]:
            ack(call)
            return
        if s["plays"].get(n, 0) >= AUDIO_MAX_PLAYS:
            ack(call, f"🔇 As in the real exam, each recording is played only {AUDIO_MAX_PLAYS} times.", True)
            return
        ack(call, "🎧 Audio yuborilmoqda…")
        if send_part_audio(uid, s, n):
            s["plays"][n] = s["plays"].get(n, 0) + 1
        send_panel(uid, s)
    elif action == "mat":
        ack(call)
        if n in s["mats"]:
            send_material(uid, s, n)
            send_panel(uid, s)
    elif action == "fin":
        ack(call)
        if s["cur"] not in s["mats"]:
            s["cur"] = s["parts"][0]
        show(call, sheet_text(s), sheet_kb(s))
    elif action == "back":
        ack(call)
        show(call, panel_text(s), panel_kb(s))
    elif action == "done":
        ack(call)
        left = unanswered(s)
        if left == 0:
            finish_exam(call, s)
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("✅ Yes, finish", callback_data=f"ex_ok_{skill}"),
               types.InlineKeyboardButton("↩️ Back to answers", callback_data=f"ex_fin_{skill}"))
        show(call, f"⚠️ <b>{left} question(s)</b> not answered.\n\n"
                   "Unanswered questions count as incorrect. Finish anyway?", kb)
    elif action == "ok":
        ack(call)
        finish_exam(call, s)
    else:
        ack(call)


def refresh_picker(call, skill):
    chosen = chosen_parts(call.from_user.id, skill)
    edit(call.message.chat.id, call.message.message_id, picker_text(skill, chosen), parts_kb(skill, chosen))


# =========================
# 🗓 KUN HISOBI (AI kunlik limiti uchun)
# =========================

def today_key():
    return (now() + TZ_OFFSET_HOURS * 3600) // 86400


# =========================
# 🏆 PESHQADAMLAR TUGMALARI
# =========================

def lb_kb(uid, referral=False):
    m = types.InlineKeyboardMarkup(row_width=1)
    if not referral:
        m.add(types.InlineKeyboardButton("🔗 Do'stlarni taklif qilish", callback_data="referral"))
    # Telegram foydalanuvchiga chatni tanlatadi va tayyor taklif xabarini yuboradi.
    # Shuning uchun havolani qo'lda copy qilish shart emas.
    if referral:
        share_text = (
            "SolutionX botida ingliz tilini mashq qilamiz! 🚀\n\n"
            "Botga shu havola orqali qo'shiling: " + ref_link(uid)
        )
        m.add(types.InlineKeyboardButton("📤 Do'stlarga ulashish", switch_inline_query=share_text))
    m.add(types.InlineKeyboardButton("🔄 Yangilash", callback_data="referral"),
          types.InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_home"))
    return m


@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def cb_check_sub(call):
    uid = call.from_user.id
    if not get_user(uid):
        q_exec("INSERT INTO users (user_id, username, state, created_at) VALUES (?,?,?,?)",
               (uid, call.from_user.username, "new", now()))
    if is_subscribed(uid):
        bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi!")
        proceed(uid, call.from_user.first_name)
        tdelete(call.message.chat.id, call.message.message_id)   # «obuna bo'ling» xabari endi kerak emas
    else:
        bot.answer_callback_query(call.id, "❌ Avval kanalga obuna bo'ling!", show_alert=True)


# ---- Grammar test sessiyalari (xotirada) ----
grammar_sessions = {}   # uid -> {"qids": [...], "i": 0, "score": 0, "last": "", "mid": msg_id}
_gs_lock = threading.Lock()


def level_grade(pct, base=None):
    """Natija foiziga qarab 'Daraja Bahosi' nomi. base — tanlangan daraja (Grammar), bo'lmasa umumiy baho."""
    if base:
        tail = ("A'lo" if pct >= 80 else "Yaxshi" if pct >= 60 else
                "O'rtacha" if pct >= 40 else "Mustahkamlash kerak")
        return f"{base} — {tail}"
    if pct >= 80:
        return "C1 — Ilg'or"
    if pct >= 60:
        return "B2 — Yuqori o'rta"
    if pct >= 40:
        return "B1 — O'rta"
    return "A2 — Boshlang'ich"


def recommendation(pct):
    if pct >= 85:
        return "Ajoyib natija! Endi murakkabroq darajaga yoki boshqa bo'limga o'ting."
    if pct >= 65:
        return "Yaxshi natija! Xatolaringizni ko'rib chiqing — keyingi safar yanada yuqori ball olasiz."
    if pct >= 40:
        return "Yomon emas! Xatolar tahlilini o'qib, mavzularni takrorlang va qayta urinib ko'ring."
    return "Hali boshlanish — bu normal! Asosiy mavzularni takrorlab, har kuni mashq qiling."


def completion_text(module, correct, total, pct, base_level=None):
    """Test yakuni xabari (shablon)."""
    return (f"Tabriklaysiz, <b>{html.escape(module)}</b> testi yakunlandi! 🎉\n\n"
            f"📊 Natijangiz: {total} savoldan <b>{correct}</b> tasdiqlandi.\n"
            f"🌟 Daraja Bahosi: <b>{html.escape(level_grade(pct, base_level))}</b>\n"
            f"💡 Tavsiya: {recommendation(pct)}\n\n"
            "🚀 Davom etish: Boshqa ko'nikmalarni sinash yoki rivojlantirish uchun asosiy menyuga o'ting!")


def reward_referrer_if_qualified(uid, score, total, elapsed=None):
    """Anti-fraud: do'st quyidagilarni bajargandagina taklif qilganga ochko beriladi:
      1) majburiy kanalga obuna bo'lgan,
      2) testni kamida REFERRAL_MIN_SECONDS soniyada yechgan (tavakkal bosmagan),
      3) kamida REFERRAL_MIN_PERCENT (8/25) to'g'ri topgan.
    Foydalanuvchiga ko'rsatiladigan izoh matnini qaytaradi."""
    u = get_user(uid)
    ref = u["referrer_id"]
    if not ref or u["ref_rewarded"] or ref == uid:
        return ""
    if elapsed is not None and elapsed < min_seconds(total):
        track(uid, "referral_rejected", {"reason": "too_fast", "seconds": round(elapsed), "score": score})
        return ("\n\n⚠️ Siz testni o'ta tez yechdingiz. Referral ochkosi hisoblanishi uchun "
                "testni diqqat bilan o'qib yechish talab etiladi.")
    if score < min_correct(total):
        track(uid, "referral_rejected", {"reason": "low_score", "score": score})
        return (f"\n\nℹ️ Sizni taklif qilgan do'stingizga ochko berilishi uchun kamida "
                f"{min_correct(total)} ta to'g'ri javob kerak. Yana urinib ko'ring!")
    if not is_subscribed(uid):
        track(uid, "referral_rejected", {"reason": "not_subscribed"})
        return ("\n\n⚠️ Taklif qilgan do'stingizga ochko berilishi uchun majburiy kanalga obuna bo'lib turishingiz "
                "kerak. Obuna bo'lib, testni qayta yeching.")
    if not get_user(ref):
        return ""
    cur = q_exec("UPDATE users SET ref_rewarded=1 WHERE user_id=? AND ref_rewarded=0", (uid,))
    if cur.rowcount != 1:
        return ""
    q_exec("INSERT OR IGNORE INTO referrals (invited_id, referrer_id, contest_no, score, total, seconds, created_at) "
           "VALUES (?,?,?,?,?,?,?)",
           (uid, ref, 0, score, total, int(elapsed or 0), now()))
    q_exec("UPDATE users SET ref_count=ref_count+1 WHERE user_id=?", (ref,))
    track(ref, "referral_rewarded", {"invited": uid, "score": score, "total": total,
                                     "seconds": round(elapsed or 0)})
    pos, friends = my_position(leaderboard_rows(), ref)
    msg = (f"🎉 Do'stingiz <b>{html.escape(u['full_name'] or '')}</b> Grammar Testdan muvaffaqiyatli o'tdi!\n"
           f"➕ Peshqadamlar reytingida sizga <b>+1 do'st</b> qo'shildi.\n\n"
           f"🏆 Sizning o'rningiz: <b>{pos}-o'rin</b> ({friends} ta do'st)")
    safe_send(ref, msg)
    return "\n\n🎉 Natijangiz sizni taklif qilgan do'stingizga ochko keltirdi!"


def render_grammar(uid, chat_id, mid):
    s = grammar_sessions[uid]
    total = len(s["qids"])

    # Test tugagach, yakuniy natijani alohida xabar qilib yuboramiz.
    if s["i"] >= total:
        track(uid, "test_completed", {"skill": "Grammar", "level": s.get("level"),
                                      "score": s["score"], "total": total,
                                      "seconds": round(time.time() - s["t0"]) if s.get("t0") else None})
        elapsed = time.time() - s.get("t0", 0) if s.get("t0") else None
        note = reward_referrer_if_qualified(uid, s["score"], total, elapsed)
        del grammar_sessions[uid]
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("🔄 Yana test", callback_data="grammar"),
               types.InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_home"))
        percent = round(s["score"] * 100 / total) if total else 0
        base = s.get("level")
        module = f"Grammar ({base})" if base else "Grammar"
        text = completion_text(module, s["score"], total, percent, base) + note
        safe_send(chat_id, text, reply_markup=kb)
        return

    q = q_one("SELECT * FROM questions WHERE question_id=?", (s["qids"][s["i"]],))
    opts = json.loads(q["options"])
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(*[types.InlineKeyboardButton(k, callback_data=f"gq_{q['question_id']}_{k}")
             for k in opts])
    body = "\n".join(f"<b>{k}.</b> {html.escape(v)}" for k, v in opts.items())
    text = (f"❓ <b>Savol {s['i'] + 1}/{total}</b>  "
            f"<i>({q['cefr_level']} · {html.escape(q['grammar_tag'] or '')})</i>\n\n"
            f"{html.escape(q['text'])}\n\n{body}")

    # Birinchi savolda daraja menyusidagi xabarni savolga aylantiramiz.
    # Keyingi savollar esa alohida yangi xabar bo'lib keladi.
    if s["i"] == 0 and mid:
        if not edit(chat_id, mid, text, kb):
            safe_send(chat_id, text, reply_markup=kb)
    else:
        safe_send(chat_id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("gq_"))
def cb_grammar_answer(call):
    uid = call.from_user.id
    _, qid, letter = call.data.split("_")
    qid = int(qid)
    with _gs_lock:
        session = grammar_sessions.get(uid)
        if not session or session["i"] >= len(session["qids"]) or session["qids"][session["i"]] != qid:
            bot.answer_callback_query(call.id, "Bu savol eskirgan. Testni qaytadan boshlang.")
            return

        q = q_one("SELECT * FROM questions WHERE question_id=?", (qid,))
        correct = letter == q["correct_answer"]
        track(uid, "question_answered" if correct else "question_failed",
              {"question_id": qid, "skill": q["skill"], "grammar_tag": q["grammar_tag"],
               "cefr_level": q["cefr_level"], "answer": letter})
        bot.answer_callback_query(call.id, "✅ To'g'ri!" if correct else "❌ Xato")

        # Javob tanlangach, eski savol tugmalarini o'chirib qo'yamiz.
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                          reply_markup=None)
        except Exception as e:
            print("Grammar tugmalarini o'chirishda xato:", e)

        if correct:
            session["score"] += 1
            feedback = "✅ <b>To'g'ri!</b>"
        else:
            opts = json.loads(q["options"])
            correct_letter = q["correct_answer"]
            correct_text = opts.get(correct_letter, "")
            feedback = (f"❌ <b>Xato!</b> To'g'ri javob: <b>{correct_letter}) "
                        f"{html.escape(correct_text)}</b>")

        if q["explanation"]:
            feedback += f"\n💡 {html.escape(q['explanation'])}"

        # Izoh savoldan alohida xabar bo'lib yuboriladi.
        safe_send(call.message.chat.id, feedback)
        session["i"] += 1
        render_grammar(uid, call.message.chat.id, None)


@bot.callback_query_handler(func=lambda c: True)
def cb_main(call):
    try:
        _cb_main(call)
    finally:
        ack(call)          # har qanday holatda tugma "aylanib" qolmasin


SELF_ACK = ("pgo_", "ex_", "an_", "at_", "dd_", "ai_pick_")   # bu tugmalar o'zi ack qiladi (ogohlantirish ko'rsatishi mumkin)


def _cb_main(call):
    uid = call.from_user.id
    data = call.data
    u = get_user(uid)

    if not u or u["state"] != "ready":
        ack(call, "Avval /start orqali ro'yxatdan o'ting!", True)
        return
    if not data.startswith(SELF_ACK):
        ack(call)
    if not (data.startswith("ai_") or data in AI_SKILLS):
        ai_sessions.pop(uid, None)      # boshqa bo'limga o'tildi — AI javob kutishi bekor

    if data == "back_home":
        grammar_sessions.pop(uid, None)
        end_exam(uid)
        show(call, welcome_ready(call.from_user.first_name), main_menu(uid))

    elif data == "noop":
        pass

    # ---------- PROFIL ----------
    elif data == "profile":
        show(call, profile_text(u, uid), back_btn())

    # ---------- REFERAL ----------
    elif data == "referral":
        track(uid, "referral_opened")
        show(call, leaderboard_text(uid, with_rules=True), lb_kb(uid, referral=True))

    # ---------- GRAMMAR TEST ----------
    elif data == "grammar":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(*[types.InlineKeyboardButton(f"📶 {label}", callback_data=f"gl_{code}")
                 for code, (label, _) in GRAMMAR_LEVELS.items()])
        kb.row(types.InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_home"))
        show(call, grammar_intro_text(u), kb)

    elif data.startswith("gl_") and data[3:] in GRAMMAR_LEVELS:
        code = data[3:]
        label, db_levels = GRAMMAR_LEVELS[code]
        marks = ",".join("?" * len(db_levels))
        ids = [r["question_id"] for r in q_all(
            f"SELECT question_id FROM questions WHERE skill='Grammar' AND cefr_level IN ({marks})", db_levels)]
        if not ids:
            show(call, "🚧 Bu daraja uchun savollar hali qo'shilmagan.", back_btn("grammar", "🔙 Darajalar"))
            return
        random.shuffle(ids)
        with _gs_lock:
            grammar_sessions[uid] = {"qids": ids[:GRAMMAR_QUESTIONS_PER_TEST], "i": 0, "score": 0,
                                     "last": "", "mid": call.message.message_id, "level": label,
                                     "t0": time.time()}
            _screens[uid] = call.message.message_id
            track(uid, "user_started_test", {"skill": "Grammar", "level": label})
            render_grammar(uid, call.message.chat.id, call.message.message_id)

    # ---------- READING / LISTENING ----------
    elif data in PART_SKILLS:
        track(uid, "daily_practice_opened", {"skill": data})
        end_exam(uid)
        chosen = chosen_parts(uid, data)
        show(call, picker_text(data, chosen), parts_kb(data, chosen))

    elif data.startswith("pp_"):
        # pp_<skill>_<n>: har bir part mustaqil: bosilsa ✅, qayta bosilsa belgi o'chadi
        try:
            _, skill, n = data.split("_")
            n = int(n)
        except ValueError:
            return
        if skill not in PART_SKILLS or not 1 <= n <= PARTS_COUNT[skill]:
            return
        with _pick_lock:
            chosen_parts(uid, skill).symmetric_difference_update({n})
            refresh_picker(call, skill)

    elif data.startswith("pgo_"):
        skill = data[4:]
        if skill not in PART_SKILLS:
            ack(call)
            return
        start_exam(call, skill)

    elif data.startswith(("ex_", "an_", "at_", "dd_")):
        exam_cb(call, data)

    elif data in AI_SKILLS or data.startswith(("ai_pick_", "ai_cancel_")):
        ai_callback(call, u, data)         # Writing / Speaking — AI tekshiruv

    elif data in SECTIONS:
        title, text = SECTIONS[data]
        track(uid, "daily_practice_started", {"skill": data})
        show(call, text, back_btn())


# =========================
# 🛠 ADMIN BUYRUQLARI
# =========================

def admin_only(fn):
    def wrapper(message):
        if message.from_user.id not in ADMIN_IDS:
            return
        fn(message)
    return wrapper


@bot.message_handler(commands=["reload_materials"], chat_types=["private"])
@admin_only
def cmd_reload_materials(message):
    _mat_cache.clear()
    _mat_seen.clear()
    _ai_cache.clear()
    _ai_seen.clear()
    lines = ["♻️ Materiallar qayta yuklandi:"]
    for skill in PART_SKILLS:
        lines.append(f"{SKILL_NAME[skill]}: " + ", ".join(
            f"P{n}={len(load_materials(skill, n))}" for n in range(1, PARTS_COUNT[skill] + 1)))
    lines.append("AI: " + ", ".join(f"{c}={len(ai_load(c))}" for c in AI_TASKS))
    safe_send(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["admin"], chat_types=["private"])
@admin_only
def cmd_admin(message):
    safe_send(message.chat.id,
              "🛠 <b>Admin buyruqlari</b>\n\n"
              "/stats — statistika\n"
              "/broadcast — biror xabarga reply qilib yozing, hammaga yuboriladi\n"
              "/reload_materials — materials/ papkasidagi o'zgarishlarni qayta yuklash\n"
              "/ai_test — Gemini (Writing/Speaking AI) ulanishini tekshirish")


@bot.message_handler(commands=["stats"], chat_types=["private"])
@admin_only
def cmd_stats(message):
    total = q_one("SELECT COUNT(*) c FROM users")["c"]
    ready = q_one("SELECT COUNT(*) c FROM users WHERE state='ready'")["c"]
    refs = q_one("SELECT COUNT(*) c FROM referrals")["c"]
    mau, dau = active_users()
    safe_send(message.chat.id,
              f"📊 <b>Statistika</b>\n\n👥 Jami: {total}\n✅ Ro'yxatdan o'tgan: {ready}\n"
              f"📅 Oylik faol (30 kun): {mau}\n🔥 Bugun faol: {dau}\n🔗 Tasdiqlangan referallar: {refs}")


@bot.message_handler(commands=["broadcast"], chat_types=["private"])
@admin_only
def cmd_broadcast(message):
    src = message.reply_to_message
    if not src:
        safe_send(message.chat.id, "Yubormoqchi bo'lgan xabarga (matn/rasm/video) reply qilib /broadcast yozing.")
        return
    sent = failed = 0
    for r in q_all("SELECT user_id FROM users WHERE state='ready'"):
        try:
            bot.copy_message(r["user_id"], src.chat.id, src.message_id)
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.05)   # Telegram limitiga tushmaslik uchun
    safe_send(message.chat.id, f"📣 Yuborildi: {sent}, xato: {failed}")


# =========================
# 🧹 KERAKSIZ XABARLAR (eng oxirida ro'yxatdan o'tadi)
# =========================

# =========================
# 🤖 AI TEKSHIRUV: WRITING & SPEAKING (Gemini — ai_grader.py)
# =========================
# Oqim: Writing/Speaking -> topshiriq turi -> bot topshiriq beradi -> foydalanuvchi matn / ovozli xabar yuboradi
#       -> Gemini (speakingda avval ovozni matnga aylantiradi) -> Multilevel bo'yicha ball (0–75) + daraja + tahlil.
# Topshiriqlar: materials/writing/<task1_1|task1_2|task2>/*.json,
# materials/speaking/<part1_1|part1_2|part2|part3>/*.json

AI_SKILLS = ("writing", "speaking")
AI_TASKS = {
    "w11": {"skill": "writing", "dir": "task1_1", "btn": "✉️ Task 1.1 — Informal letter",
            "title": "Writing · Task 1.1 (informal letter / email)", "min_words": 50, "max_words": None},
    "w12": {"skill": "writing", "dir": "task1_2", "btn": "📨 Task 1.2 — Formal letter",
            "title": "Writing · Task 1.2 (formal letter / email)", "min_words": 120, "max_words": 150},
    "w2": {"skill": "writing", "dir": "task2", "btn": "📝 Task 2 — Essay",
           "title": "Writing · Task 2 (essay)", "min_words": 180, "max_words": 200},
    "s11": {"skill": "speaking", "dir": "part1_1", "btn": "💬 Part 1.1",
            "title": "Speaking · Part 1.1", "expected_seconds": 90},
    "s12": {"skill": "speaking", "dir": "part1_2", "btn": "🖼 Part 1.2",
            "title": "Speaking · Part 1.2", "expected_seconds": 90},
    "s2": {"skill": "speaking", "dir": "part2", "btn": "🗣 Part 2 — Long turn",
           "title": "Speaking · Part 2 (long turn)", "expected_seconds": 120},
    "s3": {"skill": "speaking", "dir": "part3", "btn": "⚖️ Part 3 — For & against",
           "title": "Speaking · Part 3 (for and against)", "expected_seconds": 120},
}
# materials/ papkasida fayl bo'lmasa ishlatiladigan zaxira topshiriqlar
AI_FALLBACK = {
    "w11": {"id": "fb-w11", "title": "A new hobby", "level": "B1",
            "instructions": "You have recently started a new hobby. Write an email to a friend. In your email:\n"
                            "- tell him/her what the hobby is;\n- explain why you enjoy it;\n"
                            "- invite your friend to try it with you."},
    "w12": {"id": "fb-w12", "title": "Faulty headphones", "level": "B2",
            "instructions": "You bought a pair of headphones online, but they stopped working after one week. "
                            "Write an email to the customer service manager. In your email:\n"
                            "- explain what the problem is;\n- say what you have already done to solve it;\n"
                            "- tell the manager what you would like the company to do."},
    "w2": {"id": "fb-w2", "title": "Working from home", "level": "C1",
           "instructions": "More and more people now work or study from home instead of going to an office or school.\n"
                           "What are the advantages and disadvantages of this trend?"},
    "s11": {"id": "fb-s11", "title": "Part 1.1", "questions": [
        "What do you usually do in your free time?", "Tell me about the town or city where you live.",
        "What kind of food do you like to eat, and why?"]},
    "s12": {"id": "fb-s12", "title": "Part 1.2", "questions": [
        "What can you see in the picture?", "What are the people doing?",
        "Would you like to be there? Why or why not?"]},
    "s2": {"id": "fb-s2", "title": "Part 2", "topic": "Describe a teacher who helped you a lot.",
           "points": ["who the teacher was", "what subject they taught", "how they helped you",
                      "why you still remember them"], "prep_seconds": 60},
    "s3": {"id": "fb-s3", "title": "Part 3", "statement": "Should children be allowed to use smartphones at school?",
           "points": ["arguments FOR", "arguments AGAINST", "your own opinion and conclusion"], "prep_seconds": 60},
}
AI_CODE_SKILL = {c: t["skill"] for c, t in AI_TASKS.items()}
ai_sessions = {}      # uid -> {"code", "mat", "ts", "mid"}: foydalanuvchi hozir javob kutilayotgan topshiriq
ai_busy = set()       # hozir tekshirilayotgan foydalanuvchilar (ikki marta yuborishdan himoya)
_ai_cache = {}        # code -> [material, ...]
_ai_seen = {}         # (uid, code) -> ko'rilgan material id lari
AI_SKILL_LABEL = {"writing": "✍️ Writing", "speaking": "🗣 Speaking"}


def ai_load(code):
    if code in _ai_cache:
        return _ai_cache[code]
    t = AI_TASKS[code]
    folder = os.path.join(MATERIALS_DIR, t["skill"], t["dir"])
    items = []
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, fn), encoding="utf-8") as f:
                    d = json.load(f)
                ai_prompt_text(code, d)            # tuzilma noto'g'ri bo'lsa shu yerda xato beradi
                d.setdefault("id", f"{code}-{fn}")
                items.append(d)
            except Exception as e:
                print(f"AI materialini o'qishda xato ({t['skill']}/{t['dir']}/{fn}):", e)
    _ai_cache[code] = items or [AI_FALLBACK[code]]
    return _ai_cache[code]


def ai_pick(uid, code):
    items = ai_load(code)
    seen = _ai_seen.setdefault((uid, code), set())
    fresh = [m for m in items if m["id"] not in seen]
    if not fresh:
        seen.clear()
        fresh = items
    m = random.choice(fresh)
    seen.add(m["id"])
    return m


def ai_prompt_text(code, mat):
    """Topshiriq matni (inglizcha) — o'quvchiga ham, AI ga ham shu ko'rsatiladi."""
    if code in ("w11", "w12", "w2"):
        return str(mat["instructions"]).strip()
    if code in ("s11", "s12"):
        return "\n".join(f"{i}. {q}" for i, q in enumerate(mat["questions"], 1))
    if code == "s2":
        pts = "\n".join(f"- {p}" for p in mat.get("points", []))
        return f"{mat['topic']}\nYou should say:\n{pts}".strip()
    if code == "s3":
        pts = "\n".join(f"- {p}" for p in mat.get("points", []))
        return f"{mat['statement']}\nYou should talk about:\n{pts}".strip()
    raise KeyError(code)


def ai_menu_text(uid, skill):
    body = SECTIONS[skill][1]
    note = ""
    if not ai_grader.is_configured():
        note = ("\n\n⚙️ <i>AI tekshiruv hali ulanmagan (GEMINI_API_KEY kiritilmagan).</i>" if uid in ADMIN_IDS
                else "\n\n⚙️ <i>AI tekshiruv tez orada ishga tushadi.</i>")
    hint = ("\n\n👇 Topshiriq turini tanlang:" if skill == "writing" else "\n\n👇 Part ni tanlang:")
    return body + note + hint


def ai_menu_kb(skill):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for code, t in AI_TASKS.items():
        if t["skill"] == skill:
            kb.add(types.InlineKeyboardButton(t["btn"], callback_data=f"ai_pick_{code}"))
    kb.add(types.InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_home"))
    return kb


def ai_task_text(code, mat):
    t = AI_TASKS[code]
    head = f"<b>{esc(t['title'])}</b>" + (f"  ·  {esc(mat['level'])}" if mat.get("level") else "")
    prompt = esc(ai_prompt_text(code, mat))
    if t["skill"] == "writing":
        lo = mat.get("min_words", t.get("min_words"))
        hi = mat.get("max_words", t.get("max_words"))
        size = f"{lo}–{hi} so'z" if lo and hi else (f"kamida {lo} so'z" if lo else "erkin hajm")
        return (f"✍️ {head}\n\n{prompt}\n\n📏 Hajmi: <b>{size}</b>\n\n"
                "✏️ Javobingizni <b>bitta xabar</b> qilib shu chatga yuboring.")
    prep = mat.get("prep_seconds")
    exp = mat.get("expected_seconds", t["expected_seconds"])
    timing = (f"⏱ Tayyorlanish: ~{prep} soniya · " if prep else "⏱ ") + f"Gapirish: ~{exp} soniya"
    return (f"🗣 {head}\n\n{prompt}\n\n{timing}\n\n"
            f"🎤 Tayyor bo'lgach, javobingizni <b>bitta ovozli xabar</b> qilib yuboring "
            f"(eng ko'pi bilan {AI_MAX_VOICE_SEC // 60} daqiqa).")


def send_task_image(uid, code, mat):
    """Part 1.2 JSON dagi materials/ ga nisbiy image faylini xavfsiz yuboradi."""
    if code != "s12" or not mat.get("image"):
        return
    root = os.path.abspath(MATERIALS_DIR)
    path = os.path.abspath(os.path.join(root, str(mat["image"])))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        print(f"Speaking Part 1.2 rasmi topilmadi: {mat.get('image')}")
        return
    try:
        with open(path, "rb") as image:
            bot.send_photo(uid, image, caption="🖼 <b>Speaking · Part 1.2 rasmi</b>")
    except Exception as e:
        print("Speaking rasmi yuborishda xato:", e)


def ai_cancel_kb(skill):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔙 Boshqa topshiriq", callback_data=skill),
           types.InlineKeyboardButton("🏠 Asosiy menyu", callback_data="back_home"))
    return kb


def ai_callback(call, u, data):
    """Writing / Speaking bo'limi tugmalari (callback: writing, speaking, ai_pick_<kod>, ai_cancel_<skill>)."""
    uid = call.from_user.id
    skill = data if data in AI_SKILLS else None
    if data.startswith("ai_pick_"):
        code = data[len("ai_pick_"):]
        if code not in AI_TASKS:
            return
        skill = AI_TASKS[code]["skill"]
    elif data.startswith("ai_cancel_"):
        skill = data[len("ai_cancel_"):]
        if skill not in AI_SKILLS:
            return
    if not skill:
        return
    if data.startswith("ai_pick_"):
        if not ai_grader.is_configured():
            ack(call, "⚙️ AI tekshiruv hali ulanmagan." if uid in ADMIN_IDS else
                "⚙️ AI tekshiruv tez orada ishga tushadi.", True)
            return
        if uid in ai_busy:
            ack(call, "⏳ Oldingi javobingiz tekshirilmoqda, biroz kuting.", True)
            return
        mat = ai_pick(uid, code)
        show(call, ai_task_text(code, mat), ai_cancel_kb(skill))
        send_task_image(uid, code, mat)
        ai_sessions[uid] = {"code": code, "mat": mat, "ts": now(), "mid": _screens.get(uid)}
        track(uid, "ai_task_started", {"task": code, "id": mat.get("id")})
    else:                                   # menyu (yoki bekor qilish)
        ai_sessions.pop(uid, None)
        if data == skill:
            track(uid, "daily_practice_started", {"skill": skill})
        show(call, ai_menu_text(uid, skill), ai_menu_kb(skill))


def _ai_waiting(message, skill):
    s = ai_sessions.get(message.from_user.id)
    return bool(s) and AI_CODE_SKILL[s["code"]] == skill and now() - s["ts"] < AI_SESSION_TTL


def _ai_precheck(uid):
    """Tekshiruvga yuborishdan oldin shartlar. Muammo bo'lsa foydalanuvchiga ko'rsatiladigan matn qaytaradi."""
    u = get_user(uid)
    if not u or u["state"] != "ready":
        return "Avval /start orqali ro'yxatdan o'ting!"
    if not ai_grader.is_configured():
        return "⚙️ AI tekshiruv hozircha ulanmagan."
    if uid in ai_busy:
        return "⏳ Oldingi javobingiz tekshirilmoqda, biroz kuting."
    return None


def _ai_send(uid, text, kb=None):
    """Natijani yuboradi; HTML xato bersa, teglarsiz oddiy matn sifatida qayta urinadi."""
    try:
        return bot.send_message(uid, text, reply_markup=kb)
    except Exception as e:
        print("AI natijasini yuborishda xato (HTML):", e)
        plain_text = html.escape(html.unescape(re.sub(r"<[^>]+>", "", text)), quote=False)
        try:
            return bot.send_message(uid, plain_text, reply_markup=kb)
        except Exception as e2:
            print("AI natijasini yuborishda xato:", e2)


def _ai_send_lines(uid, lines, limit=3800):
    chunk = ""
    for ln in lines:
        if chunk and len(chunk) + len(ln) + 1 > limit:
            _ai_send(uid, chunk)
            chunk = ""
        chunk += ln + "\n"
    if chunk.strip():
        _ai_send(uid, chunk)


def ai_result_lines(res, code, mat):
    t = AI_TASKS[code]
    writing = t["skill"] == "writing"
    keys = ai_grader.WRITING_KEYS if writing else ai_grader.SPEAKING_KEYS
    lines = [f"{'✍️' if writing else '🗣'} <b>{esc(t['title'])}</b> — natija", "━━━━━━━━━━━━━━━━━━", "",
             f"🎯 Taxminiy ball: <b>{res['score']} / 75</b>  →  <b>{esc(res['level'])}</b>"]
    if writing:
        lo = mat.get("min_words", t.get("min_words"))
        hi = mat.get("max_words", t.get("max_words"))
        need = f" (kerak: {lo}–{hi})" if lo and hi else (f" (kamida {lo})" if lo else "")
        lines.append(f"🔤 So'zlar soni: <b>{res['words']}</b>{need}")
    else:
        sec = res.get("seconds")
        lines.append(f"🕒 Davomiyligi: <b>{sec} soniya</b> · so'zlar: <b>{res['words']}</b>" if sec
                     else f"🔤 So'zlar: <b>{res['words']}</b>")
    if res["off_topic"]:
        lines.append("⚠️ Javob topshiriq mavzusiga mos kelmadi, shuning uchun ball past.")
    lines += ["", "📊 <b>Mezonlar</b> (0–9):"]
    for k in keys:
        c = res["comments"].get(k)
        lines.append(f"• <b>{ai_grader.CRITERIA_NAMES[k]}</b>: {res['scores'][k]:g}/9"
                     + (f"\n   <i>{esc(c)}</i>" if c else ""))
    if not writing:
        tr = " ".join(res["transcript"].split())[:1500]
        lines += ["", "📝 <b>Transcript</b> (AI eshitgani):", f"<blockquote expandable>{esc(tr)}</blockquote>"]
    if res["strengths"]:
        lines += ["", "✅ <b>Kuchli tomonlar</b>"] + [f"• {esc(s)}" for s in res["strengths"]]
    if res["mistakes"]:
        lines += ["", "❌ <b>Asosiy xatolar</b>"]
        for i, m in enumerate(res["mistakes"], 1):
            ex = f"\n   💬 {esc(m['explanation'])}" if m["explanation"] else ""
            lines.append(f"{i}. <i>{esc(m['original'])}</i>\n   ➜ <b>{esc(m['correction'])}</b>{ex}")
    if res.get("pron"):
        lines += ["", "🔊 <b>Talaffuz</b>"] + [f"• {esc(p)}" for p in res["pron"]]
    if res["tips"]:
        lines += ["", "💡 <b>Maslahatlar</b>"] + [f"• {esc(x)}" for x in res["tips"]]
    lines += ["", "ℹ️ <i>Bu AI bergan taxminiy baho (0–75 shkala). Rasmiy Multilevel natijasi emas.</i>"]
    return lines


def _ai_next_kb(code):
    skill = AI_TASKS[code]["skill"]
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔁 Yana shu turdagi topshiriq", callback_data=f"ai_pick_{code}"),
           types.InlineKeyboardButton("📋 Boshqa topshiriq", callback_data=skill),
           types.InlineKeyboardButton("🏠 Asosiy menyu", callback_data="back_home"))
    return kb


def _ai_fail(uid, wait_mid, text, skill):
    kb = ai_cancel_kb(skill)
    body = f"{esc(text)}\n\n<i>Javobingizni qayta yuborishingiz mumkin.</i>"
    if wait_mid and edit(uid, wait_mid, body, kb):
        return
    _ai_send(uid, body, kb)


def _ai_job(uid, s, wait_mid, text=None, file_id=None, mime=None, seconds=None):
    """Fon oqimida: Gemini bilan ishlaydi (botning asosiy oqimini bloklamaslik uchun)."""
    code, mat = s["code"], s["mat"]
    t = AI_TASKS[code]
    try:
        if t["skill"] == "writing":
            task = {"title": t["title"], "instructions": ai_prompt_text(code, mat),
                    "min_words": mat.get("min_words", t.get("min_words")),
                    "max_words": mat.get("max_words", t.get("max_words"))}
            res = ai_grader.grade_writing(task, text)
        else:
            audio = bot.download_file(bot.get_file(file_id).file_path)
            task = {"title": t["title"], "prompt_text": ai_prompt_text(code, mat),
                    "expected_seconds": mat.get("expected_seconds", t["expected_seconds"])}
            res = ai_grader.grade_speaking(task, audio, mime, seconds)
    except ai_grader.AIError as e:
        print(f"AI xatosi (user {uid}, {code}):", e.detail)
        _ai_fail(uid, wait_mid, e.user_msg, t["skill"])
        return
    except Exception as e:
        print(f"AI kutilmagan xato (user {uid}, {code}):", repr(e))
        _ai_fail(uid, wait_mid, "⚠️ Kutilmagan xato yuz berdi. Birozdan keyin qayta urinib ko'ring.", t["skill"])
        return
    finally:
        ai_busy.discard(uid)

    q_exec("INSERT INTO ai_checks (user_id, skill, task, score, level, day, ts) VALUES (?,?,?,?,?,?,?)",
           (uid, t["skill"], code, res["score"], res["level"], today_key(), now()))
    track(uid, "ai_check", {"skill": t["skill"], "task": code, "score": res["score"],
                            "level": res["level"], "model": res["model"]})
    if ai_sessions.get(uid) is s:
        ai_sessions.pop(uid, None)
    if wait_mid:
        tdelete(uid, wait_mid)
    _ai_send_lines(uid, ai_result_lines(res, code, mat))
    screen(uid, "👇 Davom etamizmi?",
           reply_markup=_ai_next_kb(code))


def _ai_launch(uid, s, **payload):
    ai_busy.add(uid)
    wait = safe_send(uid, "⏳ <b>AI tekshirmoqda…</b>\nBu 10–40 soniya olishi mumkin, kuting.")
    threading.Thread(target=_ai_job, args=(uid, s, wait.message_id if wait else None),
                     kwargs=payload, daemon=True).start()


@bot.message_handler(content_types=["text"], chat_types=["private"],
                     func=lambda m: _ai_waiting(m, "writing") and not (m.text or "").startswith("/"))
def on_ai_writing(message):
    uid = message.from_user.id
    s = ai_sessions.get(uid)
    if not s:
        return
    err = _ai_precheck(uid)
    if err:
        temp(uid, err, ttl=8)
        return
    text = (message.text or "").strip()
    words = ai_grader.count_words(text)
    if words < AI_MIN_WORDS_ABS:
        temp(uid, f"⚠️ Javob juda qisqa ({words} so'z). Kamida {AI_MIN_WORDS_ABS} so'zli javob yozing.", ttl=8)
        return
    if len(text) > AI_MAX_TEXT_CHARS:
        temp(uid, f"⚠️ Javob juda uzun (eng ko'pi bilan {AI_MAX_TEXT_CHARS} belgi). Qisqartirib yuboring.", ttl=8)
        return
    _ai_launch(uid, s, text=text)


@bot.message_handler(content_types=["voice", "audio"], chat_types=["private"],
                     func=lambda m: _ai_waiting(m, "speaking"))
def on_ai_speaking(message):
    uid = message.from_user.id
    s = ai_sessions.get(uid)
    if not s:
        return
    err = _ai_precheck(uid)
    if err:
        temp(uid, err, ttl=8)
        return
    media = message.voice or message.audio
    secs = int(getattr(media, "duration", 0) or 0)
    size = int(getattr(media, "file_size", 0) or 0)
    mime = getattr(media, "mime_type", None) or "audio/ogg"
    if secs and secs < AI_MIN_VOICE_SEC:
        temp(uid, f"⚠️ Ovoz juda qisqa ({secs} soniya). Kamida {AI_MIN_VOICE_SEC} soniya gapiring.", ttl=8)
        return
    if secs > AI_MAX_VOICE_SEC:
        temp(uid, f"⚠️ Ovoz juda uzun ({secs} soniya). Eng ko'pi bilan {AI_MAX_VOICE_SEC} soniya.", ttl=8)
        return
    if size > AI_MAX_AUDIO_BYTES:
        temp(uid, "⚠️ Audio fayl juda katta. Qisqaroq ovozli xabar yuboring.", ttl=8)
        return
    if not ai_grader.normalize_mime(mime):
        temp(uid, "⚠️ Bu audio formati qo'llab-quvvatlanmaydi. Telegram'da ovozli xabar (🎤) yuboring.", ttl=8)
        return
    _ai_launch(uid, s, file_id=media.file_id, mime=mime, seconds=secs or None)


@bot.message_handler(commands=["ai_test"], chat_types=["private"])
@admin_only
def cmd_ai_test(message):
    chat = message.chat.id
    if not ai_grader.is_configured():
        safe_send(chat, "❌ GEMINI_API_KEY topilmadi. .env fayliga qo'shing va botni qayta ishga tushiring.")
        return
    wait = safe_send(chat, "⏳ Gemini tekshirilmoqda…")

    def run():
        try:
            res = ai_grader.grade_writing(
                {"title": "Test", "instructions": "Write 2-3 sentences about your last weekend.",
                 "min_words": 20, "max_words": None},
                "Last weekend I visit my friend. We play football and eat pizza. It was very good day.")
            txt = (f"✅ Gemini ishlayapti\nModel: {res['model']}\nTest balli: {res['score']}/75 ({res['level']})\n"
                   f"Modellar zanjiri: {', '.join(ai_grader.models())}")
        except ai_grader.AIError as e:
            txt = f"❌ {e.user_msg}\nSabab: {e.detail}"
        except Exception as e:
            txt = f"❌ {type(e).__name__}: {e}"
        if wait:
            tdelete(chat, wait.message_id)
        safe_send(chat, esc(txt))

    threading.Thread(target=run, daemon=True).start()


STRAY_HINTS = {
    "ism": "⚠️ Iltimos, ism va familiyangizni matn bilan yozing.",
    "telefon": "⚠️ Telefon raqamni pastdagi «📲 Telefon raqamni ulashish» tugmasi orqali ulashing.",
    "yosh": "⚠️ Yoshingizni raqam bilan yozing.",
}


@bot.message_handler(content_types=["text", "photo", "audio", "document", "video", "voice", "sticker",
                                    "animation", "video_note", "contact", "location", "poll"],
                     chat_types=["private"])
def cleanup_stray(message):
    """Boshqa hech qaysi handlerga tushmagan xabarlarni o'chiradi (adminlarniki bundan mustasno)."""
    uid = message.from_user.id
    s = ai_sessions.get(uid)
    ai_hint = None
    if s and now() - s["ts"] < AI_SESSION_TTL:       # AI javob kutilmoqda, lekin noto'g'ri turdagi xabar keldi
        ai_hint = ("🎤 Bu topshiriq uchun <b>ovozli xabar</b> (🎤) yuboring." if AI_CODE_SKILL[s["code"]] == "speaking"
                   else "✍️ Bu topshiriq uchun javobni <b>matn</b> ko'rinishida yuboring.")
    if uid in ADMIN_IDS:
        if ai_hint:
            temp(uid, ai_hint)
        return
    tdelete(message.chat.id, message.message_id)
    if ai_hint:
        temp(uid, ai_hint)
        return
    u = get_user(uid)
    if u and u["state"] in STRAY_HINTS:
        temp(uid, STRAY_HINTS[u["state"]])


# =========================
# ▶️ ISHGA TUSHIRISH
# =========================

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-T" \
        "ype", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    _start_health_server()
    print(f"🚀 Multi-Level Academy bot ishga tushdi! @{BOT_USERNAME}")

    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60,
                logger_level=20
            )

        except Exception as e:
            print(f"⚠️ Telegram bilan aloqa uzildi: {e}")
            print("🔄 Qayta ulanishga urinish...")
            time.sleep(5)