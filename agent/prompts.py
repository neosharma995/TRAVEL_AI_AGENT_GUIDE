# agent/prompts.py — All LLM prompt templates

INTENT_EXTRACTION_PROMPT = """You are a travel booking intent extractor.

Given a user message and today's date, extract as much info as possible.

Return ONLY valid JSON (no markdown, no explanation):
{{
  "service_type": "hotel" | "package" | null,
  "city": "primary city name" | null,
  "cities": ["city1", "city2", "city3"] | [],
  "check_in": "YYYY-MM-DD" | null,
  "check_out": "YYYY-MM-DD" | null,
  "guests": integer | null,
  "confidence": "high" | "medium" | "low",
  "confirm_booking": true | false,
  "possible_city": "raw word if it might be a misspelled city" | null
}}

Rules:
- Today is {today}. Convert relative dates like "14 may", "this friday", "next week", "12 to 16 june", "after 10 days" to YYYY-MM-DD.
- If month not specified, assume current year current month. If date has passed, assume next month.
- IMPORTANT: A single date like "12 june" or "june 12" or "12" → set ONLY check_in, leave check_out null.
- "14 to 20 may" → check_in: this year's May 14, check_out: this year's May 20
- "10 people" or "10 guests" or "for 10" or "party of 10" → guests: 10
- A bare integer like "4" or "just 4" or "only 3" almost certainly means the number of guests → set guests to that integer.
- A message that is ONLY a number (e.g. "4", "2", "10") → guests: that number.
- If message mentions hotel/room/stay/accommodation → service_type: "hotel"
- If message mentions package/tour/trip/vacation → service_type: "package"
- If message contains "book now", "confirm", "yes book", "okay book", "proceed", "finalize", "done book", "book it", "yes confirm" → confirm_booking: true
- If a word looks like it could be a city name (proper noun, place-like) but you are not sure it is real, put it in possible_city.
- city should only be set if you are confident it is a real, correctly spelled city.
- MULTI-CITY RULE: If the user mentions multiple cities/destinations (e.g. "shimla manali", "shimla to manali", "shimla manali kinnaur", "shimla spiti manali"), extract ALL of them into the "cities" array AND set "city" to the first one. Fix common misspellings (spiti=Spiti, manlai=Manali, kinnaut=Kinnaur). For packages, always populate "cities" even if only one city is mentioned.
- Return null for anything not mentioned — do NOT guess.

User message: "{message}"
"""

PKG_DATE_EXTRACTION_PROMPT = """You are a travel date extractor. Today is {today}.

The user wants to provide a STARTING DATE for a travel package.

Extract the starting date from: "{message}"

Rules:
- A bare number like "12" means day 12 of the current month ({current_month_name}).
- "12 june" or "june 12" → June 12 of current year {current_year}.
- "tomorrow" → {tomorrow}.
- "after 4 days" → {after_4_days}.
- "next week" → {next_week}.
- If a date resolves to today or past → it is INVALID.
- If no clear date found → null.

Return ONLY valid JSON:
{{
  "start_date": "YYYY-MM-DD" | null,
  "is_past": true | false,
  "error": "reason if invalid" | null
}}
"""

CITY_VALIDATION_PROMPT = """The user is trying to book travel and typed: "{city}"

Is this a real city, town, hill station, or tourist destination anywhere in the world?
OR is it a misspelling/typo of a real place?

Return ONLY valid JSON:
{{
  "valid": true,
  "corrected": "correct name if different from input, else null",
  "message": null
}}
OR if not valid and not a recognizable misspelling:
{{
  "valid": false,
  "corrected": null,
  "message": "friendly short message explaining you don't recognize this place"
}}
OR if it looks like a misspelling:
{{
  "valid": false,
  "corrected": "the real place name you think they meant",
  "message": "Did you mean [place]? Please confirm or type the correct city name."
}}

Be generous — include small towns, pilgrimage sites, hill stations, villages etc.
Be smart about common misspellings: shila=Shimla, mnsali=Manali, dlehi=Delhi, goa=Goa (valid), mumbai=Mumbai (valid).
Always return the message field — it will be shown directly to the user."""