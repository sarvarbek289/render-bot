# Materiallar

materials/<reading (part1-5)|listening (part1-6)>/*.json — har bir part papkasiga bir nechta JSON qo'shsangiz, bot ularni navbat bilan beradi.
Listening: JSON ichida "audio": "test1.mp3" va "script" (audio skripti) bo'ladi; mp3 shu papkada turadi.

Yangi/o'zgargan materialni botga /reload_materials (admin) bilan yuklang.

Audioni qayta yaratish (ixtiyoriy): tools/ papkasida `npm i echogarden`, so'ng `node build_audio.mjs` (ffmpeg kerak).
Ovoz sifati Flite (robot-ga yaqin). Tabiiyroq ovoz kerak bo'lsa, shu skriptlardan boshqa TTS bilan mp3 yasab, xuddi shu nomda almashtiring.

## Writing / Speaking (AI tekshiruvi)

Papkalar: `writing/task1_1` (informal letter), `writing/task1_2` (formal letter), `writing/task2` (essay);
`speaking/part1_1` (Part 1.1), `speaking/part1_2` (rasmli Part 1.2), `speaking/part2` (long turn), `speaking/part3` (for & against).
Har bir papkaga xohlagancha `.json` qo'shing — bot ularni takrorlamay navbat bilan beradi. Yangilarini `/reload_materials` bilan yuklang.

Writing:
```json
{"id": "writing-2-04", "title": "Mavzu nomi", "level": "C1",
 "instructions": "Topshiriq matni (inglizcha)...", "min_words": 180, "max_words": 200}
```
(`max_words` ni `null` qilsangiz, faqat minimum so'z soni talab qilinadi.)

Speaking:
```json
Part 1.1: {"id": "speaking-1-1-04", "title": "Part 1.1", "questions": ["savol 1", "savol 2", "savol 3"], "expected_seconds": 90}
Part 1.2: {"id": "speaking-1-2-04", "title": "Part 1.2", "image": "speaking/part1_2/part1_2.jpg", "questions": ["savol 1", "savol 2", "savol 3"], "expected_seconds": 90}
Part 2: {"id": "speaking-2-04", "title": "Part 2", "topic": "Describe ...", "points": ["...", "..."], "prep_seconds": 60, "expected_seconds": 120}
Part 3: {"id": "speaking-3-04", "title": "Part 3", "statement": "Should ...?", "points": ["arguments FOR", "arguments AGAINST", "your opinion"], "prep_seconds": 60, "expected_seconds": 120}
```
Part 1.2 uchun `image` qiymati `materials/` papkasiga nisbiy rasm yo'li bo'ladi. Masalan, yuqoridagi yo'l uchun rasm faylini `materials/speaking/part1_2/part1_2.jpg` ga joylang.

## Reading / Listening qo'shimcha maydonlar
- `"answer_style": "dropdown"` — gap filling (Part 1): javob harfi emas, ro'yxatdan so'z tanlanadi; savollar matn ichidagi `(1) ______` bo'shliqlar.
- `"answer_style": "words"` — tugmalarda harf o'rniga variant matni (masalan True / False / Not Given). `"hide_bank": true` bilan birga ishlatiladi.
- Topshiriq shartlari (`instructions`, `bank_title`, `q`) inglizcha yoziladi; `why` (xato tushuntirishi) o'zbekcha bo'lib, natijadan keyin ko'rsatiladi.
