# Class Service — LAB1 i LAB2

Trzecia usługa w systemie zarządzania klubem fitness. Obsługuje zajęcia grupowe: termin, prowadzącego trenera, limit miejsc i status zajęć. Dane są zapisywane w SQLite, a odczyt pojedynczych zajęć korzysta z cache Redis.

## Uruchomienie i testy

Wymagania: Python 3.12 lub nowszy, PowerShell. Otwórz terminal w katalogu `class-service`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8103
```

W drugim terminalu: `Invoke-RestMethod http://localhost:8103/health`. Dokumentacja: [Swagger UI](http://localhost:8103/docs). Zatrzymanie serwera: `Ctrl+C`. Konfiguracja bazy i Redis (LAB2) - sekcja „Uruchomienie” w części LAB2 na końcu pliku.

## 1. Problem i granice

### 1.1. Problem
Klub prowadzi zajęcia grupowe z ograniczoną liczbą miejsc. Bez jednego miejsca z grafikiem zajęć recepcja i system zapisów nie wiedzą, czy zajęcia nadal się odbędą, kto je prowadzi i ilu uczestników mogą przyjąć, a jednego trenera można przypisać do dwóch zajęć w tym samym czasie.

### 1.2. Użytkownicy
Manager klubu (planuje i odwołuje zajęcia), recepcja (sprawdza grafik, oznacza zajęcia jako zakończone), członek klubu (przegląda grafik), inne usługi systemu (Booking Service sprawdza, czy zajęcia są zaplanowane i jaki mają limit miejsc).

### 1.3. Usługa odpowiada za
- zajęcia grupowe: nazwę, termin i prowadzącego trenera (`trainer_id`),
- limit miejsc na zajęciach (`capacity`),
- status zajęć (`scheduled` / `finished` / `cancelled`) i dozwolone zmiany statusu.

### 1.4. Usługa nie odpowiada za
- zapisy członków na zajęcia i listę rezerwową (Booking Service),
- dane trenerów, ich dostępność i treningi personalne (Trainer Service - przechowujemy tylko `trainer_id`),
- karnety, płatności i dane osobowe członków.

### 1.5. Pojęcia domenowe
- **Zajęcia grupowe** - jednorazowe zajęcia o określonej nazwie, terminie i limicie miejsc, prowadzone przez jednego trenera.
- **Limit miejsc** - maksymalna liczba uczestników (1–50); liczbę zapisanych osób zna Booking Service.
- **Status zajęć** - `scheduled` (zaplanowane), `finished` (odbyły się), `cancelled` (odwołane); `finished` i `cancelled` są końcowe.
- **Kolizja trenera** - dwa zaplanowane zajęcia tego samego trenera nakładające się choć o minutę; przedziały stykające się końcami (17:00–18:00 i 18:00–19:00) nie kolidują.
- **Czas lokalny klubu** - wszystkie daty bez strefy czasowej, np. `2026-11-20T18:00:00`.

| Planowana usługa                                       | Odpowiedzialność                                | Własne dane                                                    | Operacje                                                       | Potrzebne informacje od innej usługi                                                                                          |
|--------------------------------------------------------|-------------------------------------------------|----------------------------------------------------------------|----------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| Pierwsza - implementowana teraz: **Class Service** (port 8103) | zajęcia grupowe, termin, limit miejsc, status   | zajęcia: nazwa, `trainer_id`, termin, limit miejsc, status     | lista, szczegóły, utworzenie zajęć, odwołanie, zakończenie     | w LAB3: czy trener `trainer_id` istnieje i jest aktywny (Trainer Service)                                                     |
| Druga - planowana: **Booking Service** (port 8104)     | zapisy członków na zajęcia, lista rezerwowa     | zapisy: `class_id`, `membership_id`, status, kolejność na liście | zapis na zajęcia, rezygnacja, lista zapisów na zajęcia         | czy zajęcia są zaplanowane i jaki mają limit (Class Service); czy karnet jest aktywny (Membership Service)                      |

### 1.6. Granice i właściciele danych
Tabelę `group_classes` zapisuje wyłącznie Class Service. Zajęcia tworzy i odwołuje manager, zakończenie oznacza recepcja. Trener należy do Trainer Service - Class Service zapisuje tylko jego identyfikator, bez klucza obcego, bo nie ma dostępu do bazy innej usługi. Zapisy na zajęcia będzie zapisywać wyłącznie Booking Service. Podział wynika z odpowiedzialności: Class Service odpowiada na pytanie *czy i kiedy odbywają się zajęcia oraz ile mogą mieć miejsc*, Booking Service - *kto jest na nie zapisany*. Grafik zmienia się rzadko (planowanie na tydzień), a zapisy wiele razy dziennie.

### 1.7. Przyszłe wywołanie HTTP (LAB3, przez Eurekę)
- nadawca: Booking Service, odbiorca: Class Service (nazwa logiczna `CLASS-SERVICE`),
- kiedy: przy zapisie członka na zajęcia, przed zapisem,
- metoda i ścieżka: `GET /classes/{class_id}`, np. `GET /classes/C-001`,
- żądanie: bez body,
- odpowiedź 200:
  ```json
  {"id": "C-001", "name": "Trening obwodowy", "trainer_id": "T-001", "starts_at": "2026-11-20T18:00:00", "ends_at": "2026-11-20T19:00:00", "capacity": 12, "status": "scheduled"}
  ```
- zajęcia `scheduled` -> Booking porównuje liczbę zapisów z `capacity` i zapisuje członka albo dopisuje go do listy rezerwowej; `finished` lub `cancelled` -> 409, zapis nie powstaje,
- Class Service zwraca 404 -> Booking Service zwraca 404 „Class not found”,
- inny błąd HTTP Class Service -> 502, brak połączenia lub timeout 3 s -> 503. W obu przypadkach zapis nie powstaje.

Na LAB2 Class Service sprawdza tylko format `trainer_id` (`T-` i co najmniej trzy cyfry).

## 2. Model i reguła biznesowa

Model `GroupClass`:
- `id` - `str`, nadaje serwer, `C-001`, `C-002`, ...,
- `name` - `str`, wymagane, 1–100 znaków,
- `trainer_id` - `str`, wymagane, format `T-001`,
- `starts_at`, `ends_at` - data i godzina bez strefy, wymagane, `ends_at` po `starts_at`, czas trwania 30–120 min,
- `capacity` - `int`, wymagane, 1–50,
- `status` - `scheduled` / `finished` / `cancelled`, nowe zajęcia mają `scheduled`.

Dane początkowe (wstawiane tylko do pustej bazy):
- `C-001` - „Trening obwodowy”, T-001, 2026-11-20 18:00–19:00, 12 miejsc, `scheduled`,
- `C-002` - „Pilates”, T-001, 2026-11-18 17:00–18:00, 10 miejsc, `cancelled` (przykład zajęć odwołanych).

**Reguła biznesowa — zmiana statusu zajęć:** status można zmienić tylko zajęciom `scheduled`: na `finished` albo `cancelled`. Odwołanych zajęć nie da się przywrócić ani zakończyć, a zakończonych odwołać.
- dozwolone: `PATCH /classes/C-001/cancel` -> 200, status `cancelled`,
- niedozwolone: `PATCH /classes/C-002/finish` -> 409 „Cannot change class status from 'cancelled' to 'finished'”,
- niedozwolone: `PATCH /classes/C-001/cancel` po zakończeniu C-001 -> 409 „Cannot change class status from 'finished' to 'cancelled'”.

Pozostałe reguły:
- trener nie może prowadzić dwóch zaplanowanych zajęć w nakładających się terminach -> 409; zajęcia odwołane i zakończone nie blokują terminu,
- limit miejsc 1–50 i czas trwania 30–120 min -> inaczej 422.

Wszystkie warunki są sprawdzane w jednej transakcji przed zapisem; wyjątek powoduje rollback, więc odrzucona operacja nie zmienia danych.

## 3. Kontrakt API

| Metoda | Ścieżka                      | Znaczenie                                     | Sukces           | Błędy    |
|--------|------------------------------|-----------------------------------------------|------------------|----------|
| GET    | `/health`                    | Status i nazwa usługi                         | 200              | -        |
| GET    | `/classes`                   | Lista zajęć                                   | 200 (także `[]`) | -        |
| GET    | `/classes/{class_id}`        | Szczegóły zajęć (cache, nagłówek `X-Cache`)   | 200              | 404      |
| POST   | `/classes`                   | Utworzenie zajęć                              | 201              | 409, 422 |
| PATCH  | `/classes/{class_id}/cancel` | Odwołanie zajęć                               | 200              | 404, 409 |
| PATCH  | `/classes/{class_id}/finish` | Oznaczenie zajęć jako zakończone              | 200              | 404, 409 |

Pola żądań:
- `POST /classes` - `name` (`str`, 1–100), `trainer_id` (`T-` + cyfry), `starts_at`, `ends_at` (data i godzina bez strefy, 30–120 min), `capacity` (`int`, 1–50).
- `PATCH /classes/{id}/cancel`, `PATCH /classes/{id}/finish` - bez body.

`GET /classes/C-001` -> 200, nagłówek `x-cache: MISS` / `HIT` / `BYPASS`
```json
{"id": "C-001", "name": "Trening obwodowy", "trainer_id": "T-001", "starts_at": "2026-11-20T18:00:00", "ends_at": "2026-11-20T19:00:00", "capacity": 12, "status": "scheduled"}
```

`POST /classes` z body:
```json
{"name": "Joga", "trainer_id": "T-001", "capacity": 15, "starts_at": "2026-11-21T09:00:00", "ends_at": "2026-11-21T10:00:00"}
```
-> 201
```json
{"id": "C-003", "name": "Joga", "trainer_id": "T-001", "starts_at": "2026-11-21T09:00:00", "ends_at": "2026-11-21T10:00:00", "capacity": 15, "status": "scheduled"}
```

`PATCH /classes/C-001/cancel` -> 200, w odpowiedzi `"status": "cancelled"`; `PATCH /classes/C-003/finish` -> 200, `"status": "finished"`.

Błędy:

`GET /classes/C-999` -> 404
```json
{"detail": "Class not found"}
```

`POST /classes` dla T-001 2026-11-20 18:30–19:30 -> 409
```json
{"detail": "Trainer already has a class at this time"}
```

`PATCH /classes/C-002/finish` -> 409
```json
{"detail": "Cannot change class status from 'cancelled' to 'finished'"}
```

`POST /classes` z `"capacity": 0` -> 422
```json
{"detail": [{"type": "greater_than_equal", "loc": ["body", "capacity"], "msg": "Input should be greater than or equal to 1", "input": 0, "ctx": {"ge": 1}}]}
```

`POST /classes` z 09:00–09:15 -> 422
```json
{"detail": [{"type": "value_error", "loc": ["body"], "msg": "Value error, class must last from 30 to 120 minutes", "input": {"name": "Joga", "trainer_id": "T-001", "capacity": 15, "starts_at": "2026-11-21T09:00:00", "ends_at": "2026-11-21T09:15:00"}, "ctx": {"error": {}}}]}
```

**Format `detail`:** błędy domenowe (404, 409) mają w `detail` tekst. Repozytorium zgłasza wyjątki `NotFound` i `Conflict`, a dwa handlery `@app.exception_handler` w `main.py` zamieniają je na odpowiedź JSON, dzięki temu endpointy nie powtarzają bloków `try/except`. Błędy walidacji Pydantic (422) mają w `detail` listę obiektów z polami `type`, `loc`, `msg`, `input`.

**Dobór kodów:**
- 201 - utworzono nowe zajęcia z nowym `id`, 200 - odczyt lub zmiana istniejących,
- 404 - brak zajęć o `id` z adresu,
- 422 - dane same w sobie są złe: brak pola, pusta nazwa, zły format `trainer_id`, limit spoza 1–50, koniec przed początkiem, czas spoza 30–120 min, data ze strefą czasową; wynik nie zależy od stanu bazy,
- 409 - dane są poprawne, ale kolidują z aktualnym stanem: trener ma już zajęcia w tym czasie, zajęcia są już odwołane lub zakończone.

## 4. Testy i stan danych

Testy: `test_health.py` (1), `test_classes.py` (12), `test_persistence_and_cache.py` (8). Fixture `client` z `conftest.py` tworzy dla każdego testu nową bazę w `tmp_path`, pusty `MemoryRedis` i aplikację `with TestClient(create_app(...))`, więc każdy test zaczyna od danych początkowych i nie zależy od kolejności.

| Scenariusz                                          | Stan początkowy i dokładne żądanie                                                                                   | Oczekiwany status, treść i stan                                     | Wynik rzeczywisty                                                                                                    | Reset danych             |
|-----------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|--------------------------|
| Health                                              | świeża aplikacja; `GET /health`                                                                                      | 200, `{"status": "ok", "service": "class-service"}`                 | zgodny - `test_health`                                                                                               | nowa aplikacja z fixture |
| Lista i szczegóły                                   | dane początkowe; `GET /classes`, `GET /classes/C-001`                                                                | 200; C-001 i C-002; C-001 z nazwą, limitem 12 i statusem `scheduled` | zgodny - `test_list_and_details`                                                                                     | nowa aplikacja z fixture |
| Zapis → odczyt                                      | dane początkowe; `POST /classes` Joga T-001 2026-11-21 09:00–10:00, potem `GET /classes/C-003`                       | 201, `C-003`, `scheduled`; GET -> 200, nazwa Joga                   | zgodny - `test_create_then_read`                                                                                     | nowa aplikacja z fixture |
| Brak zasobu                                         | dane początkowe; `GET /classes/C-999`, `PATCH /classes/C-999/cancel`                                                 | 404, `Class not found`                                              | zgodny - `test_unknown_class_returns_404`, `test_status_change_of_unknown_class_returns_404`                         | nowa aplikacja z fixture |
| Błędne dane                                         | dane początkowe; `POST /classes` z `capacity: 0`; `POST /classes` 09:00–09:15                                        | 422 (`loc` = `capacity`; komunikat o 30–120 min); nadal 2 zajęcia   | zgodny - `test_capacity_below_one_returns_422_and_keeps_store`, `test_too_short_class_returns_422_and_keeps_store`   | nowa aplikacja z fixture |
| Konflikt                                            | dane początkowe; `POST /classes` T-001 2026-11-20 18:30–19:30                                                        | 409, `Trainer already has a class at this time`; nadal 2 zajęcia    | zgodny - `test_overlapping_class_of_same_trainer_returns_409_and_keeps_store`                                        | nowa aplikacja z fixture |
| Reguła biznesowa: dozwolona i niedozwolona operacja | dane początkowe; `PATCH /classes/C-001/cancel`; `PATCH /classes/C-002/finish`; `PATCH /classes/C-002/cancel`         | 200 `cancelled`; 409 dla C-002 i zajęcia bez zmian                  | zgodny - `test_cancel_scheduled_class`, `test_cancelled_class_cannot_be_finished_or_cancelled_again`                 | nowa aplikacja z fixture |
| Restart                                             | Uvicorn na 8103; `POST /classes` (C-003), `PATCH C-001/cancel`, `PATCH C-003/finish`, `Ctrl+C`, ponowny start, `GET /classes` | po restarcie nadal 3 zajęcia ze zmienionymi statusami       | zgodny - dane z `class.db` (szczegóły w części LAB2, „Dowody”)                                                       | usunięcie `class.db`     |

Wynik testów (`.\.venv\Scripts\python.exe -m pytest -q`): `21 passed`.

## 5. Porównanie architektur

Monolit:
```
Klient
  |
  v
+-------------------------------------------------+
| Aplikacja klubu (1 proces)                      |
|  karnety, trenerzy, zajęcia, zapisy             |
|  sprawdzenie zajęć = wywołanie funkcji          |
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
|                              ^         |      |
|                              +- wywołanie w kodzie: czy zajęcia zaplanowane
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
  +--> Class Service      (8103) --> class.db: zajęcia grupowe, limity
  +--> Booking Service    (8104) --> zapisy, lista rezerwowa
             |
             +-- HTTP (LAB3, Eureka): GET /classes/{id} --> Class Service
             +-- HTTP (LAB3, Eureka): GET /memberships/{id} --> Membership Service
```

1. **Dlaczego usługa może być mikrousługą i czym różni się od klasy/modułu?** Ma spójną odpowiedzialność (grafik zajęć grupowych i ich limity), własne dane i bazę, osobny proces i port. Grafik zmienia się rzadko, a zapisy często, więc usługi mogą być rozwijane i restartowane niezależnie. Moduł działałby w tym samym procesie i podawałby limit miejsc wywołaniem funkcji.
2. **Jak wyglądałby system jako monolit?** Jedna aplikacja i baza; tabela zapisów miałaby klucz obcy do tabeli zajęć, a sprawdzenie „czy są wolne miejsca” byłoby jednym zapytaniem z `JOIN` i `COUNT`.
3. **Co zmieni podział na usługi?** Booking Service nie może zrobić `JOIN` z zajęciami - w LAB3 musi zapytać Class Service przez sieć. Dochodzą opóźnienia, timeouty i decyzja, co zrobić przy niedostępności Class Service (odmówić z 503 zamiast zapisywać bez sprawdzenia). Awaria Booking Service nie wyłącza grafiku zajęć.
4. **Którą architekturę wybrałbyś dla obecnej skali?** Dla jednego klubu wystarczyłby modularny monolit. Mikrousługi stosujemy, bo są celem przedmiotu, a uzasadniałaby je sieć klubów z dużym ruchem zapisów na popularne zajęcia.

## 6. Dokumentacja wykorzystana podczas pracy

| Odnośnik do fragmentu | Rozwiązywany problem | Co zastosowano w kodzie | Jak sprawdzono działanie |
|---|---|---|---|
| [FastAPI — Handling Errors: Install custom exception handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/#install-custom-exception-handlers) | te same `try/except` dla 404 i 409 powtarzane w każdym endpoincie | `@app.exception_handler(NotFound)` -> 404 i `@app.exception_handler(Conflict)` -> 409 w `main.py`; repozytorium zgłasza wyjątki domenowe | `test_unknown_class_returns_404`, `test_overlapping_class_of_same_trainer_returns_409_and_keeps_store`; ręcznie `curl.exe -i http://localhost:8103/classes/C-999` -> 404 |
| [Pydantic — Validators: model validators](https://docs.pydantic.dev/latest/concepts/validators/#model-validators) i [field validators](https://docs.pydantic.dev/latest/concepts/validators/#field-validators) | reguły obejmujące kilka pól (koniec po początku, czas trwania) i odrzucenie daty ze strefą | `@field_validator` (brak strefy) i `@model_validator(mode="after")` `check_times` w `GroupClassCreate`; `Field(ge=1, le=50)` dla `capacity` | `test_too_short_class_returns_422_and_keeps_store`, `test_capacity_below_one_returns_422_and_keeps_store` |

## 7. Ograniczenia, autorzy i AI

Ograniczenia:
- w LAB2 usługa nie sprawdza, czy trener `trainer_id` istnieje i jest aktywny — to wymaga wywołania Trainer Service (LAB3),
- kolizja jest sprawdzana tylko między zajęciami grupowymi; usługa nie widzi treningów personalnych ani bloków dostępności trenera w Trainer Service,
- liczby zapisanych osób nie ma w tej usłudze — należy do Booking Service,
- status `finished` jest ustawiany ręcznie; usługa nie sprawdza, czy termin zajęć już minął,
- reguła kolizji (sprawdzenie -> zapis) nie jest chroniona przed dwoma równoczesnymi żądaniami na ten sam termin,
- czasy są lokalne, bez strefy - klub działa w jednej strefie czasowej,
- `create_all` nie zmienia istniejących tabel, zmiana schematu wymaga usunięcia `class.db` albo migracji.

# Uzupełnienie README — LAB2

## Zmiany i decyzje

- **Co zachowano z LAB1:** Class Service powstał po LAB2, więc nie miał wersji z danymi w pamięci. Z wymagań LAB1 zachowano cały zakres opisany w sekcjach 1–7, czyli domenę i granice usługi, kontrakt API (endpointy, identyfikatory `C-001`, JSON, kody 200/201/404/409/422, treść komunikatów), regułę zmiany statusu, fabrykę `create_app()` oraz testy domenowe w stylu LAB1.
- **Co zmieniono i dlaczego:** zamiast słownika w pamięci dane są w SQLite przez SQLAlchemy 2.0, żeby zajęcia i ich statusy przetrwały restart procesu. Kod podzielono na moduły:
  - `app/models.py` - modele Pydantic (kontrakt API),
  - `app/db_models.py` - tabela ORM,
  - `app/database.py` - silnik i fabryka sesji (z paczki LAB2),
  - `app/repository.py` - operacje na bazie i reguły w transakcjach,
  - `app/cache.py` - adapter Redis `JsonCache` (z paczki LAB2),
  - `app/main.py` - `create_app(database_url=None, redis_client=None)` z `lifespan` oraz endpointy.
- **Właściciel danych oraz granice drugiej usługi:** tabelę `group_classes` zapisuje wyłącznie Class Service. Trenerzy należą do Trainer Service — Class Service przechowuje tylko `trainer_id` i nie czyta ani nie zapisuje tabeli `trainers`. Booking Service w LAB3 zapyta o zajęcia przez HTTP (sekcja 1.7) i nie będzie pisać do tabeli `group_classes`.
- **Model tabel, klucze, powiązania i ograniczenia:**

  | Tabela          | Kolumny                                                              | Klucze i ograniczenia                                                                                                                                  |
  |-----------------|----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
  | `group_classes` | `id`, `name`, `trainer_id`, `starts_at`, `ends_at`, `capacity`, `status` | PK `id`; indeks na `trainer_id`; `CHECK ends_at > starts_at`; `CHECK capacity BETWEEN 1 AND 50`; `CHECK status IN ('scheduled','finished','cancelled')` |

  Jedna tabela, bez kluczy obcych — `trainer_id` wskazuje trenera w bazie innej usługi. Indeks na `trainer_id` przyspiesza sprawdzanie kolizji. Baza chroni unikalność `id` i podstawowe wartości; kolizje terminów i przejścia statusu sprawdza repozytorium. Na 409 zamieniane jest tylko naruszenie unikalności (`UNIQUE constraint failed`). Inne błędy bazy, np. naruszenie `CHECK`, nie są maskowane jako konflikt.
- **Zachowana reguła biznesowa, operacja dozwolona i odrzucona:** status można zmienić tylko zajęciom `scheduled`. Dozwolone: `PATCH /classes/C-001/cancel` -> 200 `cancelled`. Odrzucone: `PATCH /classes/C-002/finish` -> 409 `Cannot change class status from 'cancelled' to 'finished'`. Sprawdzenie i zapis są w jednej transakcji `with sessions.begin()`, więc odrzucenie nie zostawia częściowej zmiany.
- **Odczyt objęty cache, uzasadnienie, dopuszczalna nieaktualność:** `GET /classes/{class_id}`. Szczegóły zajęć są odczytywane często (grafik w recepcji, w przyszłości Booking Service), a zmieniają się rzadko — tylko przy odwołaniu lub zakończeniu. Lista nie jest cache'owana, bo zmienia się przy każdych nowych zajęciach, a reguła kolizji zawsze czyta aktualne dane z bazy. Przy udanym unieważnieniu nieaktualność nie występuje, a po nieudanym `DEL` odwołane zajęcia mogą być widoczne jako `scheduled` w `GET /classes/{id}` do 60 s.
- **Prefiks, klucz, TTL, unieważnianie po zapisie:** klucz `{CACHE_PREFIX}:class:{id}`, np. `lab2:albumNUMER:class-service:class:C-001`; TTL 60 s (`CACHE_TTL_SECONDS`). Po udanym `PATCH /classes/{id}/cancel` i `/finish` najpierw commit w bazie, potem `DEL` klucza. `POST /classes` nie unieważnia cache, bo tworzy nowe `id`. Odpowiedzi 404 nie są zapisywane w cache. Adapter ma timeout 0,3 s bez ponowień: błąd `GET` lub `SET` -> odpowiedź z bazy z `X-Cache: BYPASS`; błąd `DEL` -> zmiana w bazie zostaje zatwierdzona, w logu ostrzeżenie `Invalidation failed; old value may survive until TTL`.

## Uruchomienie

Wymagania: Python 3.12 lub nowszy, PowerShell, Docker Desktop (Redis 7). Bez sekretów, bo wszystkie adresy są lokalne.

```powershell
cd class-service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

docker run --name lab2-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine   # później: docker start lab2-redis
docker exec lab2-redis redis-cli ping                                    # PONG

$env:DATABASE_URL = 'sqlite:///./class.db'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CACHE_PREFIX = 'lab2:albumNUMER:class-service'
$env:CACHE_TTL_SECONDS = '60'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8103

.\.venv\Scripts\python.exe -m pytest -q      # testy, w drugim terminalu
```

| Zmienna             | Domyślnie                         | Znaczenie                                       |
|---------------------|-----------------------------------|-------------------------------------------------|
| `DATABASE_URL`      | `sqlite:///./class.db`            | baza w pliku `class.db` w katalogu uruchomienia |
| `REDIS_URL`         | `redis://localhost:6379/0`        | adres Redis                                     |
| `CACHE_PREFIX`      | `lab2:fitness-club:class-service` | prefiks kluczy                                  |
| `CACHE_TTL_SECONDS` | `60`                              | czas życia wpisu w cache                        |

Port API: 8103. Schemat tworzy `Base.metadata.create_all()` w `lifespan` przy starcie; dane początkowe (sekcja 2) są wstawiane tylko do pustej bazy. Reset danych: zatrzymaj Uvicorna i usuń `class.db`; reset cache: `docker exec lab2-redis redis-cli DEL <klucz>`. Zmiana zmiennych wymaga ponownego uruchomienia Uvicorna.

## Dowody

Ręczne próby z rzeczywistym Redis. Środowisko: Redis 7 w Dockerze (`lab2-redis`), Uvicorn na 8103 bez `--reload`, prefiks `lab2:albumNUMER:class-service`, TTL 60 s (w ostatnim scenariuszu tymczasowo 300 s). GET przez `curl.exe -i`, POST i PATCH przez Swagger UI.

| Scenariusz                                | Stan początkowy i żądanie                                                                                                                                                                                                                       | Oczekiwany wynik                                                                                                                                       | Wynik rzeczywisty | Reset                                                                   |
|-------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------|-------------------------------------------------------------------------|
| Zapis i odczyt po restarcie bez cache     | usunięty `class.db`; `POST /classes` (Joga), `PATCH /classes/C-001/cancel`, `PATCH /classes/C-003/finish`, `Ctrl+C`, ponowny start, `redis-cli DEL` kluczy, `GET /classes`                                                                         | po restarcie C-001 `cancelled`, C-002 `cancelled`, C-003 `finished` (odczyt z pliku bazy)                                                              | zgodny: 201 `C-003`; po restarcie `GET /classes` zwraca C-001 `cancelled`, C-002 `cancelled`, C-003 `finished` | usunięcie `class.db`                                                    |
| Reguła: sukces i odrzucenie bez zmiany    | dane początkowe; `POST /classes` T-001 2026-11-20 18:30–19:30; `PATCH /classes/C-001/cancel`; `PATCH /classes/C-001/finish`; `GET /classes`                                                                                                       | 409 kolizja trenera; 200 `cancelled`; 409 zmiana statusu; lista nadal ma tylko C-001 i C-002 | WPISZ_WYNIK       | usunięcie `class.db`                                                    |
| MISS → HIT, liczba odczytów bazy          | pusty cache; 2× `GET /classes/C-001`; `redis-cli TTL $key`                                                                                                                                                                                      | MISS, HIT, ta sama treść; TTL ≤ 60; baza czytana raz                                                                                                   | WPISZ_WYNIK       | `redis-cli DEL $key`                                                    |
| Wygaśnięcie TTL                           | C-001 w cache; odczekanie 65 s; `TTL $key`; GET                                                                                                                                                                                                 | TTL = -2; GET -> MISS                                                                                                                                  | WPISZ_WYNIK       | samoczynnie                                                             |
| Zmiana i unieważnienie                    | C-001 `scheduled` w cache (MISS, HIT); `PATCH /classes/C-001/cancel`; `redis-cli EXISTS $key`; GET                                                                                                                                              | PATCH 200; EXISTS = 0; GET -> MISS, `cancelled`                                                                                                        | WPISZ_WYNIK       | usunięcie `class.db`                                                    |
| Awaria GET, SET, DELETE cache             | `docker stop lab2-redis`; `GET /classes/C-001`; `PATCH /classes/C-001/finish`; `docker start lab2-redis`                                                                                                                                         | GET -> 200 `BYPASS`; PATCH -> 200; ostrzeżenia w logu; brak błędu 500                                                                                  | WPISZ_WYNIK       | `docker start lab2-redis`                                               |
| Przywrócenie Redis, możliwa stara wartość | TTL 300; `GET /classes/C-001` (MISS, `scheduled` w cache); restart z `REDIS_URL=redis://127.0.0.1:9999/0`: GET, `PATCH /classes/C-001/cancel`; restart z poprawnym `REDIS_URL`: GET, `redis-cli TTL $key`, `redis-cli DEL $key`, GET             | GET przy odłączeniu -> `BYPASS`; PATCH -> 200 (`cancelled` w bazie, `DEL` nieudany); po przywróceniu HIT ze starym `scheduled`; po `DEL` -> MISS z `cancelled` | WPISZ_WYNIK       | `redis-cli DEL $key`, przywrócenie `REDIS_URL` i `CACHE_TTL_SECONDS=60` |

**Testy automatyczne (zamiennik `MemoryRedis`, baza w `tmp_path`, bez Dockera)** — wynik `.\.venv\Scripts\python.exe -m pytest -q`: `21 passed`.

Własne testy LAB2 (`tests/test_persistence_and_cache.py`):

| Test                                                                | Co wykazuje                                                                                                                                          |
|---------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `test_changes_survive_new_app_instance`                             | **trwałość:** zmiany z pierwszej instancji widoczne w drugiej na tym samym pliku bazy, z pustym cache (`MISS`); `seed()` nie dodaje danych drugi raz |
| `test_miss_then_hit_reads_database_once`                            | **HIT/MISS:** `MISS`, potem `HIT`; repozytorium wywołane raz; TTL = 60                                                                               |
| `test_status_change_invalidates_cache`                              | **unieważnienie:** po `PATCH cancel` klucz znika, następny GET -> `MISS` z nowym statusem                                                           |
| `test_redis_outage_does_not_block_read_or_write`                    | **awaria cache:** GET -> `BYPASS`, PATCH i POST działają, po powrocie Redis dane aktualne                                                            |
| `test_cache_set_failure_returns_database_value_as_bypass`           | awaria samego `SET`: odpowiedź z bazy, `BYPASS`, brak wpisu w cache                                                                                  |
| `test_failed_invalidation_can_leave_stale_value`                    | ograniczenie: po nieudanym `DEL` cache zwraca stary status `scheduled`, choć w bazie jest `cancelled`                                               |
| `test_missing_class_is_not_cached`                                  | 404 nie trafia do cache                                                                                                                              |
| `test_rejected_status_change_rolls_back_and_keeps_database_state`   | rollback: odrzucona zmiana statusu nie zmienia bazy                                                                                                  |

Zachowane testy w stylu LAB1, działające na bazie: `test_health.py`, `test_classes.py` - walidacja 422, konflikty 409, brak zasobu 404 i reguła zmiany statusu z asercją „stan bez zmian”.

Ręczne próby z rzeczywistym Redis są opisane wyłącznie w tabeli powyżej; testy automatyczne nie łączą się z Redis.

## Porównanie i ograniczenia

| Cecha            | Pamięć procesu (LAB1) | SQLite (LAB2)              | Redis jako cache (LAB2)               |
|------------------|-----------------------|----------------------------|---------------------------------------|
| Rola             | stan procesu          | trwałe źródło prawdy       | odtwarzalna kopia `GET /classes/{id}` |
| Restart Uvicorna | zmiany znikają        | `class.db` zostaje         | osobny proces, wpis żyje do końca TTL |
| Brak danych      | stan utracony         | brak rekordu -> 404        | MISS - normalna sytuacja              |
| Trudność         | utrata zmian          | schemat, transakcje, błędy | aktualność, TTL, awarie               |

1. **Co zmieniło się dla klienta API, a co wewnątrz usługi?** Dla klienta tylko nagłówek `X-Cache` w `GET /classes/{id}` i to, że dane przetrwają restart. Wewnątrz: SQLite z SQLAlchemy, repozytorium z transakcjami, cache-aside w Redis i `lifespan` przygotowujący bazę i klienta Redis.
2. **Dlaczego baza i cache nie zmieniają automatycznie aplikacji w system mikroserwisowy?** To nadal jeden proces z jedną odpowiedzialnością. O mikrousługach decydują granice odpowiedzialności, własność danych, niezależne wdrażanie i komunikacja przez sieć między usługami. Baza i cache to tylko magazyny tej jednej usługi.
3. **Czy druga usługa powinna pisać do tych samych tabel?** Nie. Właścicielem tabeli `group_classes` jest Class Service. Booking Service pyta o zajęcia przez HTTP. Wspólna tabela pozwoliłaby obejść regułę zmiany statusu i związałaby usługi schematem.
4. **Skutki awarii:** awaria procesu aplikacji - usługa niedostępna, dane bezpieczne w `class.db`. Awaria Redis - odczyty idą do bazy (`BYPASS`), zapisy działają, ryzyko starego statusu zajęć do końca TTL po nieudanym `DEL`. Awaria bazy - zapisy i odczyty spoza cache kończą się błędem, a HIT może zwracać ostatnią kopię zajęć.
5. **Jakie opóźnienie aktualizacji dopuszcza odbiorca?** Recepcja i członek oglądający grafik - do 60 s w razie awarii Redis. Zapis na zajęcia nie dopuszcza opóźnienia: odwołane zajęcia widoczne jako `scheduled` mogłyby przyjąć zapis, dlatego Booking Service nie powinien opierać decyzji wyłącznie na kopii z cache.
6. **Co wymaga sprawdzenia przy zmianie SQLite na PostgreSQL?** Sterownik (np. `psycopg`), `DATABASE_URL` i hasła poza repozytorium, migracje (Alembic zamiast `create_all`), typy `TIMESTAMP`, inny komunikat błędu unikalności (warunek w `_unique_guard`), poziom izolacji transakcji oraz ograniczenie `EXCLUDE` lub blokady przeciw równoczesnym kolizjom trenera, a na koniec ponowne uruchomienie wszystkich testów.

Ograniczenia:
- **Nieudane unieważnianie:** commit w bazie i `DEL` w Redis nie są jedną transakcją, więc po nieudanym `DEL` stary status zajęć może być zwracany do końca TTL (test `test_failed_invalidation_can_leave_stale_value`, scenariusz „Przywrócenie Redis”).
- **Współbieżność:** reguła kolizji (sprawdzenie -> zapis) i nadawanie kolejnego `id` nie są chronione przed dwoma równoczesnymi żądaniami; prosty cache-aside może też zapisać do cache wartość sprzed równoległej zmiany.
- **Zmiany schematu:** `create_all` tworzy brakujące tabele, ale nie zmienia istniejących kolumn; zmiana modelu wymaga usunięcia `class.db` albo migracji.
- **Czy cache jest właściwy dla odbiorcy:** tak dla podglądu zajęć (rzadkie zmiany, akceptowalne krótkie opóźnienie). Nie dla decyzji o zapisie — Booking Service powinien sprawdzać zajęcia w momencie zapisu.
- Usługa jeszcze nie sprawdza trenera `trainer_id` w Trainer Service (LAB3).

## Dokumentacja i autorzy

| Źródło | Problem | Zastosowanie | Weryfikacja |
|---|---|---|---|
| [SQLAlchemy — Session Basics: Framing out a begin / commit / rollback block](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#framing-out-a-begin-commit-rollback-block) | odrzucona zmiana statusu lub kolidujące zajęcia nie mogą zostawić częściowej zmiany | `with self.sessions.begin() as db:` w każdej operacji zapisu `ClassRepository` — commit przy poprawnym wyjściu, rollback przy wyjątku `Conflict` / `NotFound` | `test_rejected_status_change_rolls_back_and_keeps_database_state` i testy 409 z asercją „stan bez zmian” |
| [redis-py — Connecting to Redis](https://redis.readthedocs.io/en/stable/connections.html) | niedostępny Redis nie może blokować API ani wydłużać odpowiedzi | `Redis.from_url(..., socket_connect_timeout=0.3, socket_timeout=0.3, retry=Retry(NoBackoff(), 0))` w `make_redis` i łapanie `RedisError` w `JsonCache` | `test_redis_outage_does_not_block_read_or_write`; ręcznie: przy zatrzymanym Redis GET -> 200 `BYPASS`, zapisy -> 200 |

- **Wkład każdej osoby:** Julia — Class Service: projekt domeny, model, baza, cache, reguły, testy, ręczne scenariusze z Redis i README. `app/database.py` i `app/cache.py` pochodzą z paczki pomocniczej LAB2, jak w pozostałych usługach projektu.
- **AI:** Claude (Anthropic) — propozycja endpointów, szkic testów i uzupełnienie README. Weryfikacja: `pytest -q` (`21 passed`), ręczne sprawdzenie endpointów i kodów 404/409/422 w `/docs`, scenariusze z rzeczywistym Redis z tabeli „Dowody”, przeczytanie i omówienie kodu.
- **Kolejny etap pierwszej i planowanej drugiej usługi:** Booking Service (port 8104) — zapisy członków na zajęcia i lista rezerwowa. W LAB3 rejestracja w Eurece jako `CLASS-SERVICE`; Booking Service przy zapisie odnajdzie `CLASS-SERVICE` po nazwie logicznej i pobierze zajęcia (`GET /classes/{id}`), mapując 404 -> 404, zajęcia nie `scheduled` -> 409, inne błędy HTTP -> 502, brak połączenia lub timeout -> 503.
