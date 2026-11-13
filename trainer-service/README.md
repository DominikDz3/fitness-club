# Trainer Service — LAB1 i LAB2

Druga usługa w systemie zarządzania klubem fitness. Obsługuje trenerów, ich bloki dostępności oraz treningi personalne (trener + karnet członka + termin). Dane są zapisywane w SQLite, a odczyt pojedynczego trenera korzysta z cache Redis.

## Uruchomienie i testy

Wymagania: Python 3.12 lub nowszy, PowerShell. Otwórz terminal w katalogu `trainer-service`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8102
```

W drugim terminalu: `Invoke-RestMethod http://localhost:8102/health`. Dokumentacja: [Swagger UI](http://localhost:8102/docs). Zatrzymanie serwera: `Ctrl+C`. Konfiguracja bazy i Redis (LAB2) - sekcja „Uruchomienie” w części LAB2 na końcu pliku.

## 1. Problem i granice

### 1.1. Problem
Członkowie klubu chcą umawiać treningi personalne, a trenerzy pracują w różnych godzinach. Bez jednego miejsca z grafikiem trenerów dochodzi do podwójnych rezerwacji tego samego trenera, umawiania treningów poza godzinami jego pracy i przypisywania zajęć trenerom, którzy już nie pracują w klubie.

### 1.2. Użytkownicy
Trener (zgłasza bloki dostępności), recepcja i członek klubu (umawiają i odwołują treningi personalne), manager (dodaje trenerów, aktywuje i dezaktywuje ich), inne usługi systemu (Class Service sprawdza trenera przy planowaniu zajęć grupowych).

### 1.3. Usługa odpowiada za
- dane trenerów i ich status (`active` / `inactive`),
- bloki dostępności trenerów (kiedy trener może pracować),
- treningi personalne: termin, trener, karnet członka, status.

### 1.4. Usługa nie odpowiada za
- karnety i ich ważność (Membership Service - przechowujemy tylko `membership_id`),
- zajęcia grupowe i zapisy na nie (Class Service, Booking Service),
- płatności i dane osobowe członków.

### 1.5. Pojęcia domenowe
- **Trener** - osoba prowadząca treningi, z jedną główną specjalizacją; aktywny albo nieaktywny.
- **Blok dostępności** - przedział czasu (do 12 h), w którym trener może prowadzić treningi, bloki jednego trenera się nie nakładają.
- **Trening personalny (sesja)** - spotkanie trenera z członkiem trwające 30–120 min, mieszczące się w jednym bloku dostępności.
- **Kolizja** - dwa przedziały czasu nakładające się choć o minutę; przedziały stykające się końcami (10:00–11:00 i 11:00–12:00) nie kolidują.
- **Czas lokalny klubu** - wszystkie daty bez strefy czasowej, np. `2026-11-16T09:00:00`.

| Planowana usługa                                                  | Odpowiedzialność                          | Własne dane                                       | Operacje                                                                                                                | Potrzebne informacje od innej usługi                                            |
|-------------------------------------------------------------------|-------------------------------------------|---------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| Pierwsza - **Membership Service** (port 8101, gotowa w LAB1/LAB2) | karnety członków i ich ważność            | karnety: `member_id`, typ, okres ważności, status | lista, szczegóły, założenie, zawieszenie, wznowienie                                                                    | brak                                                                            |
| Druga - implementowana teraz: **Trainer Service** (port 8102)     | trenerzy, dostępność, treningi personalne | trenerzy, bloki dostępności, sesje                | lista i szczegóły trenera, dodanie trenera, zmiana statusu, dodanie i lista bloków, umówienie, odczyt i odwołanie sesji | w LAB3: czy karnet `membership_id` istnieje i jest aktywny (Membership Service) |

### 1.6. Granice i właściciele danych
Tabele `trainers`, `availability_blocks` i `training_sessions` zapisuje wyłącznie Trainer Service. Status trenera zmienia manager, bloki dostępności trener, sesje recepcja lub członek. Karnet należy do Membership Service - Trainer Service zapisuje tylko jego identyfikator, bez klucza obcego, bo nie ma dostępu do bazy innej usługi. Podział wynika z odpowiedzialności: Membership odpowiada na pytanie *czy członek ma prawo korzystać z klubu*, Trainer Service - *czy trener ma wolny termin*.

### 1.7. Przyszłe wywołanie HTTP (LAB3, przez Eurekę)
- nadawca: Trainer Service, odbiorca: Membership Service (nazwa logiczna `MEMBERSHIP-SERVICE`),
- kiedy: przy `POST /sessions`, przed zapisem sesji,
- metoda i ścieżka: `GET /memberships/{membership_id}`, np. `GET /memberships/M-002`,
- żądanie: bez body,
- odpowiedź 200:
  ```json
  {"id": "M-002", "member_id": "U-200", "type": "morning", "valid_from": "2026-09-01", "valid_to": "2026-11-30", "status": "suspended", "suspended_until": "2026-10-25"}
  ```
- karnet `active` -> sesja jest tworzona, karnet `suspended` lub `expired` -> 409, sesja nie powstaje,
- Membership zwraca 404 -> Trainer Service zwraca 404 „Membership not found”,
- inny błąd HTTP Membership -> 502, brak połączenia lub timeout 3 s → 503. W obu przypadkach sesja nie powstaje.

Na LAB2 sprawdzany jest tylko format `membership_id` (`M-` i co najmniej trzy cyfry).

## 2. Model i reguła biznesowa

Model `Trainer`:
- `id` - `str`, nadaje serwer, `T-001`, `T-002`, ...,
- `name` - `str`, wymagane, 1–100 znaków,
- `specialization` - `str`, wymagane, 1–50 znaków,
- `status` - `active` / `inactive`, nowy trener ma `active`.

Model `Availability` (blok dostępności):
- `id` - nadaje serwer: `A-001`, ...,
- `trainer_id` - z adresu (`/trainers/{trainer_id}/availability`),
- `starts_at`, `ends_at` - data i godzina bez strefy, wymagane, `ends_at` po `starts_at`, maksymalnie 12 h.

Model `Session` (trening personalny):
- `id` - nadaje serwer: `S-001`, ...,
- `trainer_id` - `str`, wymagane,
- `membership_id` - `str`, wymagane, format `M-001`,
- `starts_at`, `ends_at` - data i godzina bez strefy, wymagane, czas trwania 30–120 min,
- `status` - `scheduled` / `cancelled`, nowa sesja ma `scheduled`.

Dane początkowe (wstawiane tylko do pustej bazy):
- `T-001` - Anna Nowak, `strength`, `active`; `T-002` - Piotr Kowalski, `yoga`, `inactive`,
- `A-001` - T-001, 2026-11-16 08:00–12:00; `A-002` - T-001, 2026-11-16 16:00–20:00,
- `S-001` - T-001, karnet M-001, 2026-11-16 09:00–10:00, `scheduled`.

**Reguła biznesowa — termin treningu personalnego:** sesja musi mieścić się w całości w jednym bloku dostępności trenera i nie może nakładać się na inną zaplanowaną sesję tego trenera. Odwołana sesja zwalnia termin.
- dozwolone: `POST /sessions` dla T-001, 10:00–11:00 → 201 (mieści się w A-001, nie koliduje z S-001),
- niedozwolone: 11:30–12:30 → 409 „Session is outside trainer availability” (A-001 kończy się o 12:00),
- niedozwolone: 09:30–10:30 → 409 „Trainer already has a session at this time” (koliduje z S-001).

Pozostałe reguły:
- bloki dostępności trenera nie nakładają się -> 409,
- nieaktywny trener nie dostaje nowych bloków ani sesji -> 409,
- trenera z zaplanowanymi sesjami nie można dezaktywować -> 409 (najpierw trzeba odwołać sesje),
- odwołać można tylko sesję `scheduled` -> inaczej 409.

Wszystkie warunki są sprawdzane w jednej transakcji przed zapisem; wyjątek powoduje rollback, więc odrzucona operacja nie zmienia danych.

## 3. Kontrakt API

| Metoda | Ścieżka                               | Znaczenie                                     | Sukces           | Błędy         |
|--------|---------------------------------------|-----------------------------------------------|------------------|---------------|
| GET    | `/health`                             | Status i nazwa usługi                         | 200              | -             |
| GET    | `/trainers`                           | Lista trenerów                                | 200              | -             |
| GET    | `/trainers/{trainer_id}`              | Szczegóły trenera (cache, nagłówek `X-Cache`) | 200              | 404           |
| POST   | `/trainers`                           | Dodanie trenera                               | 201              | 422           |
| PATCH  | `/trainers/{trainer_id}/status`       | Aktywacja / dezaktywacja                      | 200              | 404, 409, 422 |
| GET    | `/trainers/{trainer_id}/availability` | Bloki dostępności trenera                     | 200 (także `[]`) | 404           |
| POST   | `/trainers/{trainer_id}/availability` | Dodanie bloku dostępności                     | 201              | 404, 409, 422 |
| GET    | `/sessions`                           | Lista treningów personalnych                  | 200              | -             |
| GET    | `/sessions/{session_id}`              | Szczegóły treningu                            | 200              | 404           |
| POST   | `/sessions`                           | Umówienie treningu                            | 201              | 404, 409, 422 |
| PATCH  | `/sessions/{session_id}/cancel`       | Odwołanie treningu                            | 200              | 404, 409      |

Pola żądań:
- `POST /trainers` - `name` (`str`, 1–100), `specialization` (`str`, 1–50).
- `PATCH /trainers/{id}/status` - `status` (`active` | `inactive`). Ustawienie obecnego statusu jest dozwolone i nic nie zmienia.
- `POST /trainers/{id}/availability` - `starts_at`, `ends_at` (data i godzina bez strefy, maks. 12 h).
- `POST /sessions` - `trainer_id` (`str`), `membership_id` (`M-` + cyfry), `starts_at`, `ends_at` (30–120 min).
- `PATCH /sessions/{id}/cancel` - bez body.

`GET /trainers/T-001` -> 200, nagłówek `x-cache: MISS` / `HIT` / `BYPASS`
```json
{"id": "T-001", "name": "Anna Nowak", "specialization": "strength", "status": "active"}
```

`POST /trainers` z `{"name": "Ewa Zielinska", "specialization": "pilates"}` -> 201
```json
{"id": "T-003", "name": "Ewa Zielinska", "specialization": "pilates", "status": "active"}
```

`POST /trainers/T-001/availability` z `{"starts_at": "2026-11-17T08:00:00", "ends_at": "2026-11-17T14:00:00"}` -> 201
```json
{"id": "A-003", "trainer_id": "T-001", "starts_at": "2026-11-17T08:00:00", "ends_at": "2026-11-17T14:00:00"}
```

`POST /sessions` z body:
```json
{"trainer_id": "T-001", "membership_id": "M-002", "starts_at": "2026-11-16T10:00:00", "ends_at": "2026-11-16T11:00:00"}
```
-> 201
```json
{"id": "S-002", "trainer_id": "T-001", "membership_id": "M-002", "starts_at": "2026-11-16T10:00:00", "ends_at": "2026-11-16T11:00:00", "status": "scheduled"}
```

`PATCH /sessions/S-001/cancel` -> 200, w odpowiedzi `"status": "cancelled"`.

Błędy:

`GET /trainers/T-999` -> 404
```json
{"detail": "Trainer not found"}
```

`POST /sessions` z 11:30–12:30 -> 409
```json
{"detail": "Session is outside trainer availability"}
```

`POST /sessions` z 09:30–10:30 -> 409
```json
{"detail": "Trainer already has a session at this time"}
```

`POST /trainers/T-001/availability` z 2026-11-16 11:00–13:00 -> 409
```json
{"detail": "Availability block overlaps an existing block"}
```

`PATCH /trainers/T-001/status` z `{"status": "inactive"}` -> 409
```json
{"detail": "Trainer has scheduled sessions and cannot be deactivated"}
```

`PATCH /sessions/S-001/cancel` drugi raz -> 409
```json
{"detail": "Cannot cancel session with status 'cancelled'"}
```

`POST /sessions` z 10:00–10:15 -> 422
```json
{"detail": [{"type": "value_error", "loc": ["body"], "msg": "Value error, session must last from 30 to 120 minutes", "input": {"trainer_id": "T-001", "membership_id": "M-002", "starts_at": "2026-11-16T10:00:00", "ends_at": "2026-11-16T10:15:00"}, "ctx": {"error": {}}}]}
```

**Format `detail`:** błędy domenowe (404, 409) mają w `detail` tekst. Repozytorium zgłasza wyjątki `NotFound` i `Conflict`, a dwa handlery `@app.exception_handler` w `main.py` zamieniają je na odpowiedź JSON, dzięki temu endpointy nie powtarzają bloków `try/except`. Błędy walidacji Pydantic (422) mają w `detail` listę obiektów z polami `type`, `loc`, `msg`, `input`.

**Dobór kodów:**
- 201 - utworzono nowy zasób z nowym `id`,  200 - odczyt lub zmiana istniejącego,
- 404 - brak zasobu z adresu albo trenera wskazanego w body (`trainer_id`),
- 422 - dane same w sobie są złe: brak pola, zły format, koniec przed początkiem, blok > 12 h, sesja spoza 30–120 min, data ze strefą czasowąm, wynik nie zależy od stanu bazy,
- 409 - dane są poprawne, ale kolidują z aktualnym stanem: termin zajęty, poza dostępnością, trener nieaktywny, sesja już odwołana.

## 4. Testy i stan danych

Testy: `test_health.py` (1), `test_trainers.py` (8), `test_availability.py` (10), `test_sessions.py` (11), `test_persistence_and_cache.py` (8). Fixture `client` z `conftest.py` tworzy dla każdego testu nową bazę w `tmp_path`, pusty `MemoryRedis` i aplikację `with TestClient(create_app(...))`, więc każdy test zaczyna od danych początkowych i nie zależy od kolejności.

| Scenariusz                                          | Stan początkowy i dokładne żądanie                                                                                             | Oczekiwany status, treść i stan                                   | Wynik rzeczywisty                                                                                                           | Reset danych             |
|-----------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|--------------------------|
| Health                                              | świeża aplikacja; `GET /health`                                                                                                | 200, `{"status": "ok", "service": "trainer-service"}`             | zgodny - `test_health`                                                                                                      | nowa aplikacja z fixture |
| Lista i szczegóły                                   | dane początkowe; `GET /trainers`, `GET /trainers/T-001`                                                                        | 200; T-001 i T-002; T-001 z pełnymi polami                        | zgodny - `test_trainers.py::test_list_and_details`                                                                          | nowa aplikacja z fixture |
| Zapis → odczyt                                      | dane początkowe; `POST /sessions` T-001 10:00–11:00, potem `GET /sessions/S-002`                                               | 201, `S-002`; GET -> 200, `scheduled`, `starts_at` 10:00          | zgodny - `test_book_session_inside_availability_then_read`                                                                  | nowa aplikacja z fixture |
| Brak zasobu                                         | dane początkowe; `GET /trainers/T-999`, `GET /sessions/S-999`                                                                  | 404, `Trainer not found` / `Session not found`                    | zgodny - `test_unknown_trainer_returns_404`, `test_unknown_session_returns_404`                                             | nowa aplikacja z fixture |
| Błędne dane                                         | dane początkowe; `POST /sessions` 10:00–10:15                                                                                  | 422, komunikat o 30–120 min; nadal 1 sesja                        | zgodny - `test_too_short_session_returns_422_and_keeps_state`                                                               | nowa aplikacja z fixture |
| Konflikt                                            | dane początkowe; `POST /sessions` T-001 09:30–10:30                                                                            | 409, `Trainer already has a session at this time`; nadal 1 sesja  | zgodny - `test_session_overlapping_another_returns_409_and_keeps_state`                                                     | nowa aplikacja z fixture |
| Reguła biznesowa: dozwolona i niedozwolona operacja | dane początkowe; sesja 10:00–11:00; sesja 11:30–12:30                                                                          | 201; 409 `Session is outside trainer availability`, nadal 1 sesja | zgodny - `test_book_session_inside_availability_then_read`, `test_session_outside_availability_returns_409_and_keeps_state` | nowa aplikacja z fixture |
| Restart                                             | Uvicorn na 8102; `POST /trainers` (T-003), `POST /sessions` (S-002), `Ctrl+C`, ponowny start, `GET /trainers`, `GET /sessions` | po restarcie nadal 3 trenerów i 2 sesje                           | zgodny - dane z `trainer.db` (szczegóły w części LAB2, „Dowody”)                                                            | usunięcie `trainer.db`   |

Wynik testów (`.\.venv\Scripts\python.exe -m pytest -q`): `38 passed`.

## 5. Porównanie architektur

Monolit:
```
Klient
  |
  v
+-------------------------------------------------+
| Aplikacja klubu (1 proces)                      |
|  karnety, trenerzy, dostępność, sesje, zajęcia  |
|  sprawdzenie karnetu = wywołanie funkcji        |
+-------------------------------------------------+
  |
  v
Jedna baza danych
```

Modularny monolit:
```
Klient
  |
  v
+-----------------------------------------------+
| Aplikacja klubu (1 proces)                    |
|  [Membership]  [Trainer]  [Class]  [Booking]  |
|       ^           |                           |
|       +- wywołanie w kodzie: czy karnet aktywny
+-----------------------------------------------+
  |
  v
Jedna baza (tabele logicznie przypisane do modułów)
```

Mikrousługi:
```
Klient
  |
  v
API Gateway
  |
  +--> Membership Service (8101) --> membership.db: karnety
  +--> Trainer Service    (8102) --> trainer.db: trenerzy, bloki, sesje
  |          |
  |          +-- HTTP (LAB3, Eureka): GET /memberships/{id} --> Membership Service
  +--> Class Service      (8103) --> zajęcia, limity
  +--> Booking Service    (8104) --> zapisy, lista rezerwowa
```

1. **Dlaczego usługa może być mikrousługą i czym różni się od klasy/modułu?** Ma spójną odpowiedzialność (grafik trenerów), własne dane i bazę, osobny proces i port. Grafik zmienia się często (codzienne rezerwacje), karnety rzadko przez to usługi mogą być rozwijane i restartowane niezależnie. Moduł działałby w tym samym procesie i sprawdzałby karnet wywołaniem funkcji.
2. **Jak wyglądałby system jako monolit?** Jedna aplikacja i baza; tabela sesji mogłaby mieć klucz obcy do tabeli karnetów, a reguła „karnet aktywny” byłaby zwykłym zapytaniem z `JOIN`.
3. **Co zmieni podział na usługi?** Trainer Service nie może zrobić `JOIN` z karnetami ponieważ w LAB3 musi zapytać Membership Service przez sieć. Dochodzą opóźnienia, timeouty i decyzja, co zrobić przy niedostępności Membership (odmówić z 503 zamiast tworzyć sesję bez sprawdzenia). Awaria Trainer Service nie wpływa na karnety.
4. **Którą architekturę wybrałbyś dla obecnej skali?** Dla jednego klubu wystarczyłby modularny monolit. Mikrousługi stosujemy, bo są celem przedmiotu a  uzasadniałaby je sieć klubów z dużym ruchem rezerwacji.

## 6. Dokumentacja wykorzystana podczas pracy

| Odnośnik do fragmentu                                                                                                                                                                                          | Rozwiązywany problem                                                                       | Co zastosowano w kodzie                                                                                                                                    | Jak sprawdzono działanie                                                                                                                                               |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [FastAPI — Handling Errors: Install custom exception handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/#install-custom-exception-handlers)                                                       | te same `try/except` dla 404 i 409 powtarzane w każdym endpoincie                          | `@app.exception_handler(NotFound)` -> 404 i `@app.exception_handler(Conflict)` -> 409 w `main.py`; repozytorium zgłasza wyjątki domenowe                   | `test_unknown_trainer_returns_404`, `test_session_outside_availability_returns_409_and_keeps_state`; ręcznie `curl.exe -i http://localhost:8102/trainers/T-999` -> 404 |
| [Pydantic — Validators: model validators](https://docs.pydantic.dev/latest/concepts/validators/#model-validators) i [field validators](https://docs.pydantic.dev/latest/concepts/validators/#field-validators) | reguły obejmujące kilka pól (koniec po początku, czas trwania) i odrzucenie daty ze strefą | `TimeRange` z `@field_validator` (brak strefy) i `@model_validator(mode="after")`; `AvailabilityCreate` i `SessionCreate` dziedziczą i dodają limity czasu | `test_block_ending_before_start_returns_422`, `test_block_with_timezone_returns_422`, `test_too_short_session_returns_422_and_keeps_state`                             |

## 7. Ograniczenia, autorzy i AI

Ograniczenia:
- w LAB2 usługa nie sprawdza, czy karnet `membership_id` istnieje i jest aktywny — to wymaga wywołania Membership Service (LAB3, sekcja 1.7),
- reguły kolizji (sprawdzenie -> zapis) nie są chronione przed dwoma równoczesnymi żądaniami na ten sam termin; SQLite i jedna instancja ograniczają ryzyko, ale nie usuwają go,
- usunięcie bloku dostępności nie jest możliwe, a dodanie bloku nie sprawdza, czy obejmuje istniejące sesje (bloki tylko się dodaje),
- odwołanie sesji nie ma limitu czasu (np. najpóźniej 24 h przed),
- czasy są lokalne, bez strefy - klub działa w jednej strefie czasowej,
- `create_all` nie zmienia istniejących tabel, zmiana schematu wymaga usunięcia `trainer.db` albo migracji.

# Uzupełnienie README — LAB2

## Zmiany i decyzje

- **Co zachowano z LAB1:** Trainer Service powstał po LAB2, więc nie miał wersji z danymi w pamięci. Z wymagań LAB1 zachowano cały zakres opisany w sekcjach 1–7 czyli domenę i granice usługi, kontrakt API (endpointy, identyfikatory `T-001` / `A-001` / `S-001`, JSON, kody 200/201/404/409/422, treść komunikatów), regułę terminu treningu, fabrykę `create_app()` oraz testy domenowe w stylu LAB1. W porównaniu z planem z README Membership Service usługa dostała dodatkowo treningi personalne, bo w LAB3 to one będą sprawdzać karnet w Membership Service.
- **Co zmieniono i dlaczego:** zamiast słownika w pamięci dane są w SQLite przez SQLAlchemy 2.0, żeby trenerzy, bloki i sesje przetrwały restart procesu. Kod podzielono na moduły:
  - `app/models.py` - modele Pydantic (kontrakt API),
  - `app/db_models.py` - tabele ORM,
  - `app/database.py` - silnik i fabryka sesji (z paczki LAB2),
  - `app/repository.py` - operacje na bazie i reguły w transakcjach,
  - `app/cache.py` - adapter Redis `JsonCache` (z paczki LAB2),
  - `app/main.py` - `create_app(database_url=None, redis_client=None)` z `lifespan` oraz endpointy.
- **Właściciel danych oraz granice drugiej usługi:** tabele `trainers`, `availability_blocks` i `training_sessions` zapisuje wyłącznie Trainer Service. Karnety należą do Membership Service, Trainer Service przechowuje tylko `membership_id` i nie czyta ani nie zapisuje tabeli `memberships`. w LAB3 zapyta o karnet przez HTTP (sekcja 1.7). Class Service i Booking Service także nie piszą do tabel Trainer Service.
- **Model tabel, klucze, powiązania i ograniczenia:**

  | Tabela                | Kolumny                                                               | Klucze i ograniczenia                                                                                                     |
  |-----------------------|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
  | `trainers`            | `id`, `name`, `specialization`, `status`                              | PK `id`; `CHECK status IN ('active','inactive')`                                                                          |
  | `availability_blocks` | `id`, `trainer_id`, `starts_at`, `ends_at`                            | PK `id`; FK `trainer_id → trainers.id` (indeks); `CHECK ends_at > starts_at`                                              |
  | `training_sessions`   | `id`, `trainer_id`, `membership_id`, `starts_at`, `ends_at`, `status` | PK `id`; FK `trainer_id → trainers.id` (indeks); `CHECK ends_at > starts_at`; `CHECK status IN ('scheduled','cancelled')` |

  Powiązania: trener 1 -> N bloków, trener 1 -> N sesji. `membership_id` nie ma klucza obcego, bo karnety są w bazie innej usługi. Klucze obce są egzekwowane przez `PRAGMA foreign_keys=ON` w `database.py`. Baza chroni unikalność `id`, istnienie trenera i podstawowe wartości; kolizje terminów i status trenera sprawdza repozytorium. Na 409 zamieniane jest tylko naruszenie unikalności (`UNIQUE constraint failed`). Inne błędy bazy, np. naruszenie `CHECK`, nie są maskowane jako konflikt.
- **Zachowana reguła biznesowa, operacja dozwolona i odrzucona:** sesja musi mieścić się w bloku dostępności i nie może nakładać się na inną zaplanowaną sesję trenera. Dozwolone: `POST /sessions` T-001 10:00–11:00 -> 201 `S-002`. Odrzucone: 11:30–12:30 -> 409 `Session is outside trainer availability`; 09:30–10:30 -> 409 `Trainer already has a session at this time`. Sprawdzenie i zapis są w jednej transakcji `with sessions.begin()`, więc odrzucenie nie zostawia częściowej zmiany.
- **Odczyt objęty cache, uzasadnienie, dopuszczalna nieaktualność:** `GET /trainers/{trainer_id}`. Dane trenera są odczytywane często (podgląd w recepcji, w przyszłości Class Service), a zmieniają się rzadko tylko przy zmianie statusu. Listy, bloki i sesje nie są cache'owane, bo zmieniają się przy każdej rezerwacji, a reguła kolizji musi zawsze czytać aktualne dane z bazy. Przy udanym unieważnieniu nieaktualność nie występuje a po nieudanym `DEL` stary status trenera może być widoczny w `GET /trainers/{id}` do 60 s.
- **Prefiks, klucz, TTL, unieważnianie po zapisie:** klucz `{CACHE_PREFIX}:trainer:{id}`, np. `lab2:131428:trainer-service:trainer:T-001`; TTL 60 s (`CACHE_TTL_SECONDS`). Po udanym `PATCH /trainers/{id}/status` najpierw commit w bazie, potem `DEL` klucza. `POST /trainers` nie unieważnia cache, bo tworzy nowe `id`. Odpowiedzi 404 nie są zapisywane w cache. Adapter ma timeout 0,3 s bez ponowień: błąd `GET` lub `SET` -> odpowiedź z bazy z `X-Cache: BYPASS`; błąd `DEL` -> zmiana w bazie zostaje zatwierdzona, w logu ostrzeżenie `Invalidation failed; old value may survive until TTL`.

## Uruchomienie

Wymagania: Python 3.12 lub nowszy, PowerShell, Docker Desktop (Redis 7). Bez sekretów bo wszystkie adresy są lokalne.

```powershell
cd trainer-service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

docker run --name lab2-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine   # później: docker start lab2-redis
docker exec lab2-redis redis-cli ping                                    # PONG

$env:DATABASE_URL = 'sqlite:///./trainer.db'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CACHE_PREFIX = 'lab2:131428:trainer-service'
$env:CACHE_TTL_SECONDS = '60'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8102

.\.venv\Scripts\python.exe -m pytest -q      # testy, w drugim terminalu
```

| Zmienna             | Domyślnie                           | Znaczenie                                         |
|---------------------|-------------------------------------|---------------------------------------------------|
| `DATABASE_URL`      | `sqlite:///./trainer.db`            | baza w pliku `trainer.db` w katalogu uruchomienia |
| `REDIS_URL`         | `redis://localhost:6379/0`          | adres Redis                                       |
| `CACHE_PREFIX`      | `lab2:fitness-club:trainer-service` | prefiks kluczy                                    |
| `CACHE_TTL_SECONDS` | `60`                                | czas życia wpisu w cache                          |

Port API: 8102. Schemat tworzy `Base.metadata.create_all()` w `lifespan` przy starcie; dane początkowe (sekcja 2) są wstawiane tylko do pustej bazy. Reset danych: zatrzymaj Uvicorna i usuń `trainer.db`; reset cache: `docker exec lab2-redis redis-cli DEL <klucz>`. Zmiana zmiennych wymaga ponownego uruchomienia Uvicorna.

## Dowody

Ręczne próby z rzeczywistym Redis który uruchamia Redis. Środowisko: Redis 7 w Dockerze (`lab2-redis`), Uvicorn na 8102 bez `--reload`, prefiks `lab2:131428:trainer-service`, TTL 60 s (w ostatnim scenariuszu tymczasowo 300 s).

| Scenariusz                                | Stan początkowy i żądanie                                                                                                                                                                                                                                                                              | Oczekiwany wynik                                                                                                                                                                    | Wynik rzeczywisty                                                                                                                                                                                                                                                                                                                                                                       | Reset                                                                   |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| Zapis i odczyt po restarcie bez cache     | usunięty `trainer.db`; start z `REDIS_URL=redis://127.0.0.1:9999/0` (brak Redis); `POST /trainers` (Ewa Zielinska), `POST /sessions` T-001 10:00–11:00, `Ctrl+C`, ponowny start, `GET /trainers`, `GET /sessions`                                                                                      | po restarcie T-003 i S-002 nadal są (odczyt z pliku bazy)                                                                                                                           | zgodny: 201 `T-003`, 201 `S-002`; po restarcie `GET /trainers` zwraca 3 trenerów, `GET /sessions` 2 sesje                                                                                                                                                                                                                                                                               | usunięcie `trainer.db`                                                  |
| Reguła: sukces i odrzucenie bez zmiany    | dane początkowe; `POST /sessions` T-001 10:00–11:00; 11:30–12:30; 09:30–10:30; `GET /sessions`                                                                                                                                                                                                         | 201; 409 poza dostępnością; 409 kolizja; lista ma tylko S-001 i S-002                                                                                                               | zgodny: 201 `S-002`; 409 `Session is outside trainer availability`; 409 `Trainer already has a session at this time`; lista: S-001, S-002                                                                                                                                                                                                                                               | usunięcie `trainer.db`                                                  |
| MISS → HIT, liczba odczytów bazy          | pusty cache; 2× `GET /trainers/T-001`; `redis-cli TTL $key`                                                                                                                                                                                                                                            | MISS, HIT, ta sama treść; TTL ≤ 60; baza czytana raz                                                                                                                                | zgodny: MISS, HIT, identyczna treść; TTL = 57 (odczyt po kilku sekundach). Liczbę odczytów bazy potwierdza test `test_miss_then_hit_reads_database_once` (licznik `repository.get_trainer` = 1)                                                                                                                                                                                         | `redis-cli DEL $key`                                                    |
| Wygaśnięcie TTL                           | T-001 w cache; odczekanie 65 s; `TTL $key`; GET                                                                                                                                                                                                                                                        | TTL = -2; GET -> MISS                                                                                                                                                               | zgodny: TTL = -2; GET -> 200 MISS                                                                                                                                                                                                                                                                                                                                                       | samoczynnie                                                             |
| Zmiana i unieważnienie                    | T-002 `inactive` w cache (MISS, HIT); `PATCH /trainers/T-002/status {"status": "active"}`; `redis-cli EXISTS`; GET                                                                                                                                                                                     | PATCH 200; EXISTS = 0; GET -> MISS, `active`                                                                                                                                        | zgodny: PATCH 200 `active`; EXISTS = 0; GET -> 200 MISS, `active`                                                                                                                                                                                                                                                                                                                       | usunięcie `trainer.db`                                                  |
| Awaria GET, SET, DELETE cache             | Redis niedostępny: `docker stop lab2-redis` albo usługa uruchomiona z `REDIS_URL=redis://127.0.0.1:9999/0`; `GET /trainers/T-001`; `PATCH /sessions/S-001/cancel`; `PATCH /trainers/T-001/status {"status": "inactive"}`                                                                               | GET -> 200 `BYPASS`; zapisy → 200; ostrzeżenia w logu; brak błędu 500                                                                                                               | zgodny: GET 200 `BYPASS` (log `Cache unavailable; reading database`); PATCH S-001 -> 200 `cancelled`; PATCH T-001 → 200 `inactive`, `DEL` nieudany (log `Invalidation failed; old value may survive until TTL`). Awarii samego `SET` (przy działającym `GET`) nie da się wywołać ręcznie odłączeniem Redis — sprawdza ją test `test_cache_set_failure_returns_database_value_as_bypass` | `docker start lab2-redis`, przywrócenie `REDIS_URL`                     |
| Przywrócenie Redis, możliwa stara wartość | TTL 300; usługa z działającym Redis: `GET /trainers/T-001` (MISS, `active` w cache, TTL 300); restart usługi z `REDIS_URL=redis://127.0.0.1:9999/0`: GET, `PATCH /trainers/T-001/status {"status": "inactive"}`; restart z poprawnym `REDIS_URL`: GET, `redis-cli TTL $key`, `redis-cli DEL $key`, GET | GET przy odłączeniu -> `BYPASS`; PATCH -> 200 (`inactive` w bazie, `DEL` nieudany); po przywróceniu HIT ze starym `active` aż do `DEL` lub końca TTL; po `DEL` -> MISS z `inactive` | zgodny: GET 200 `BYPASS`; PATCH 200 `inactive`; po przywróceniu GET → 200 **HIT, `active`** (stara wartość, w bazie `inactive`), TTL = 292; `DEL` = 1; GET → 200 MISS, `inactive`. Wcześniej, po samym `docker stop` / `docker start`, odczyt T-001 też był HIT — Redis zapisał snapshot przy łagodnym zatrzymaniu, więc restart serwera nie usuwa wpisu i nie dowodzi unieważnienia    | `redis-cli DEL $key`, przywrócenie `REDIS_URL` i `CACHE_TTL_SECONDS=60` |

**Testy automatyczne (zamiennik `MemoryRedis`, baza w `tmp_path`, bez Dockera)** — wynik `.\.venv\Scripts\python.exe -m pytest -q`: `38 passed`.

Własne testy LAB2 (`tests/test_persistence_and_cache.py`):

| Test                                                             | Co wykazuje                                                                                                                                          |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `test_changes_survive_new_app_instance`                          | **trwałość:** zmiany z pierwszej instancji widoczne w drugiej na tym samym pliku bazy, z pustym cache (`MISS`); `seed()` nie dodaje danych drugi raz |
| `test_miss_then_hit_reads_database_once`                         | **HIT/MISS:** `MISS`, potem `HIT`; repozytorium wywołane raz; TTL = 60                                                                               |
| `test_status_change_invalidates_cache`                           | **unieważnienie:** po `PATCH status` klucz znika, następny GET -> `MISS` z nowym statusem                                                            |
| `test_redis_outage_does_not_block_read_or_write`                 | **awaria cache:** GET -> `BYPASS`, PATCH i POST działają, po powrocie Redis dane aktualne                                                            |
| `test_cache_set_failure_returns_database_value_as_bypass`        | awaria samego `SET`: odpowiedź z bazy, `BYPASS`, brak wpisu w cache                                                                                  |
| `test_failed_invalidation_can_leave_stale_value`                 | ograniczenie: po nieudanym `DEL` cache zwraca stary status                                                                                           |
| `test_missing_trainer_is_not_cached`                             | 404 nie trafia do cache                                                                                                                              |
| `test_rejected_deactivation_rolls_back_and_keeps_database_state` | rollback: odrzucona dezaktywacja nie zmienia bazy                                                                                                    |

Zachowane testy w stylu LAB1, działające teraz na bazie: `test_health.py`, `test_trainers.py` , `test_availability.py` , `test_sessions.py`  - walidacja 422, konflikty 409, brak zasobu 404 i reguła terminu z asercją „stan bez zmian”.

Ręczne próby z rzeczywistym Redis są opisane wyłącznie w tabeli powyżej; testy automatyczne nie łączą się z Redis.

## Porównanie i ograniczenia

| Cecha            | Pamięć procesu (LAB1) | SQLite (LAB2)              | Redis jako cache (LAB2)                |
|------------------|-----------------------|----------------------------|----------------------------------------|
| Rola             | stan procesu          | trwałe źródło prawdy       | odtwarzalna kopia `GET /trainers/{id}` |
| Restart Uvicorna | zmiany znikają        | `trainer.db` zostaje       | osobny proces, wpis żyje do końca TTL  |
| Brak danych      | stan utracony         | brak rekordu -> 404        | MISS - normalna sytuacja               |
| Trudność         | utrata zmian          | schemat, transakcje, błędy | aktualność, TTL, awarie                |

1. **Co zmieniło się dla klienta API, a co wewnątrz usługi?** Dla klienta tylko nagłówek `X-Cache` w `GET /trainers/{id}` i to, że dane przetrwają restart. Wewnątrz: SQLite z SQLAlchemy, repozytorium z transakcjami, cache-aside w Redis i `lifespan` przygotowujący bazę i klienta Redis.
2. **Dlaczego baza i cache nie zmieniają automatycznie aplikacji w system mikroserwisowy?** To nadal jeden proces z jedną odpowiedzialnością. O mikrousługach decydują granice odpowiedzialności, własność danych, niezależne wdrażanie i komunikacja przez sieć między usługami. Baza i cache to tylko magazyny tej jednej usługi.
3. **Czy druga usługa powinna pisać do tych samych tabel?** Nie. Właścicielem tabel trenerów, bloków i sesji jest Trainer Service. Class Service i Booking Service pytają o trenera przez HTTP. Wspólne tabele pozwoliłyby obejść regułę kolizji terminów i związałyby usługi schematem.
4. **Skutki awarii:** awaria procesu aplikacji - usługa niedostępna, dane bezpieczne w `trainer.db`. Awaria Redis - odczyty idą do bazy (`BYPASS`), zapisy działają, ryzyko starego statusu trenera do końca TTL po nieudanym `DEL`. Awaria bazy - zapisy i odczyty spoza cache kończą się błędem, a HIT może zwracać ostatnią kopię trenera.
5. **Jakie opóźnienie aktualizacji dopuszcza odbiorca?** Recepcja oglądająca profil trenera - do 60 s w razie awarii Redis. Rezerwacja sesji nie dopuszcza żadnego opóźnienia, dlatego status trenera i kolizje terminów są zawsze sprawdzane w bazie, a nie w cache.
6. **Co wymaga sprawdzenia przy zmianie SQLite na PostgreSQL?** Sterownik (np. `psycopg`), `DATABASE_URL` i hasła poza repozytorium, migracje (Alembic zamiast `create_all`), typy `TIMESTAMP`, inny komunikat błędu unikalności (warunek w `_unique_guard`), poziom izolacji transakcji oraz blokady lub ograniczenie `EXCLUDE` przeciw równoczesnym rezerwacjom, a na koniec ponowne uruchomienie wszystkich testów.

Ograniczenia:
- **Nieudane unieważnianie:** commit w bazie i `DEL` w Redis nie są jedną transakcją, bo po nieudanym `DEL` stary status trenera może być zwracany do końca TTL (test `test_failed_invalidation_can_leave_stale_value`, scenariusz „Przywrócenie Redis”).
- **Współbieżność:** reguły kolizji (sprawdzenie -> zapis) i nadawanie kolejnego `id` nie są chronione przed dwoma równoczesnymi żądaniami, dwa równoległe POST na ten sam termin mogłyby oba przejść albo zakończyć się 409 z błędu unikalności `id`. Prosty cache-aside może też zapisać do cache wartość sprzed równoległej zmiany.
- **Zmiany schematu:** `create_all` tworzy brakujące tabele, ale nie zmienia istniejących kolumn, zmiana modelu wymaga usunięcia `trainer.db` albo migracji.
- **Czy cache jest właściwy dla odbiorcy:** tak dla podglądu trenera (rzadkie zmiany, akceptowalne krótkie opóźnienie). Nie dla danych rezerwacji, dlatego bloki i sesje nie są cache'owane.
- Usługa jeszcze nie sprawdza karnetu `membership_id` w Membership Service (LAB3).

## Dokumentacja i autorzy

| Źródło                                                                                                                                                                            | Problem                                                                   | Zastosowanie                                                                                                                                                    | Weryfikacja                                                                                                                                                                    |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [SQLAlchemy — Session Basics: Framing out a begin / commit / rollback block](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#framing-out-a-begin-commit-rollback-block) | odrzucona rezerwacja lub dezaktywacja nie może zostawić częściowej zmiany | `with self.sessions.begin() as db:` w każdej operacji zapisu `TrainerRepository` — commit przy poprawnym wyjściu, rollback przy wyjątku `Conflict` / `NotFound` | `test_rejected_deactivation_rolls_back_and_keeps_database_state` i testy 409 z asercją „stan bez zmian”; ręcznie: po dwóch odrzuconych POST lista sesji ma tylko S-001 i S-002 |
| [redis-py — Connecting to Redis](https://redis.readthedocs.io/en/stable/connections.html)                                                                                         | niedostępny Redis nie może blokować API ani wydłużać odpowiedzi           | `Redis.from_url(..., socket_connect_timeout=0.3, socket_timeout=0.3, retry=Retry(NoBackoff(), 0))` w `make_redis` i łapanie `RedisError` w `JsonCache`          | `test_redis_outage_does_not_block_read_or_write`; ręcznie: przy zatrzymanym Redis GET → 200 `BYPASS`, zapisy → 200                                                             |

- **Wkład każdej osoby:** Dominik — Trainer Service: model, baza, cache, reguły, testy, ręczne scenariusze z Redis i README.
- **AI:** Claude (Anthropic) — szkic kodu endpointów, README. uruchomienie, omówienie i weryfikacja wyników
- **Kolejny etap pierwszej i planowanej drugiej usługi:** LAB3 - rejestracja Membership Service i Trainer Service w Eurece pod różnymi nazwami i portami (8101, 8102). Trainer Service przy `POST /sessions` odnajdzie `MEMBERSHIP-SERVICE` po nazwie logicznej i sprawdzi karnet (`GET /memberships/{id}`), mapując 404 -> 404, karnet nieaktywny -> 409, inne błędy HTTP -> 502, brak połączenia lub timeout -> 503
