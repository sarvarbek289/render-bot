# Multi-Level Academy bot (solutionX)

## Ishga tushirish
```
pip install -r requirements.txt
# .env faylda GEMINI_API_KEY allaqachon kiritilgan (kerak bo'lsa o'zgartiring)
python solutionX.py
```
Bot ishga tushgach, admin akkauntidan **/ai_test** yuboring — Gemini ulanganini tekshiradi.

## ✍️🗣 Writing va Speaking AI tekshiruvi (Gemini)
- Foydalanuvchi **Writing** yoki **Speaking** ni tanlaydi, bot topshiriq beradi.
- Writing: javob **matn** bilan yuboriladi. Speaking: **ovozli xabar** (🎤) yuboriladi — AI uni avval matnga aylantiradi (transcript), keyin baholaydi.
- Natija: Multilevel shkalasida **ball (0–75)** va **daraja (B1 / B2 / C1)**, 4 mezon bo'yicha tahlil, xatolar va tuzatishlar, maslahatlar.
  - Writing mezonlari: Task Achievement, Coherence & Cohesion, Lexical Resource, Grammar.
  - Speaking mezonlari: Fluency & Coherence, Lexical Resource, Grammar, Pronunciation.
  - Har bir mezon 0–9, jami xom ball 36 dan; keyin 0–75 ga o'tkaziladi (38 = B1, 51 = B2, 65 = C1 boshi).
- Bu **taxminiy** baho — rasmiy imtihon natijasi emas.
- Kod: `ai_grader.py` (Gemini bilan ishlash, ball hisoblash) va `solutionX.py` dagi "AI TEKSHIRUV" bloki.

### Sozlamalar (.env)
| O'zgaruvchi | Ma'nosi |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio kaliti (majburiy) |
| `GEMINI_MODELS` | Modellar zanjiri (vergul bilan) |
| `AI_DAILY_LIMIT` | Foydalanuvchiga kuniga tekshiruvlar soni (standart 5) |
| `AI_RPM` | Daqiqada ko'pi bilan so'rovlar (standart 8) |
| `AI_CONCURRENCY` | Bir vaqtdagi so'rovlar (standart 3) |

Bepul tarif limitlari loyihaga qarab farq qiladi va o'zgarib turadi; limit tugasa bot foydalanuvchiga "keyinroq urinib ko'ring" deydi va tekshiruvni limitdan ayirmaydi.
Eslatma: bepul tarifda yuborilgan ma'lumotlardan Google o'z mahsulotlarini yaxshilashda foydalanishi mumkin.

### Topshiriqlarni qo'shish
`materials/writing/<task1_1|task1_2|task2>/*.json` va `materials/speaking/<part1|part2|part3>/*.json` ga yangi fayl qo'shing, so'ng admin `/reload_materials` yuboradi. Formatlar `materials/README.md` da.
