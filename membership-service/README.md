# Membership Service — LAB1 i LAB2

Pierwsza usługa systemu zarządzania klubem fitness. Obsługuje karnety członków klubu: ich zakładanie, odczyt oraz zawieszanie i wznawianie. Od LAB2 dane są zapisywane w bazie SQLite, a odczyt pojedynczego karnetu korzysta z cache Redis.

## Uruchomienie i testy

Wymagania: Python 3.12 lub nowszy, PowerShell, Docker Desktop (Redis). Otwórz terminal w katalogu z tym README i `requirements.txt`.

Instalacja i testy automatyczne (nie wymagają Redis — używają zamiennika `MemoryRedis` i osobnej bazy w katalogu tymczasowym):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Redis (jednorazowo `docker run`, później `docker start lab2-redis`):

```powershell
docker run --name lab2-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine
docker exec lab2-redis redis-cli ping
```

Uruchomienie usługi:

```powershell
$env:CACHE_PREFIX = 'lab2:albumNUMER:membership-service'   # własny numer albumu
$env:CACHE_TTL_SECONDS = '60'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8101
```

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | adres bazy; plik `app.db` powstaje w katalogu uruchomienia |
| `REDIS_URL` | `redis://localhost:6379/0` | adres Redis |
| `CACHE_PREFIX` | `lab2:fitness-club:membership-service` | prefiks kluczy w Redis |
| `CACHE_TTL_SECONDS` | `60` | czas życia wpisu w cache |

Schemat bazy tworzy `Base.metadata.create_all()` przy starcie aplikacji; dane początkowe (M-001, M-002) są wstawiane tylko do pustej tabeli. Reset danych: zatrzymaj serwer i usuń `app.db`. Zmienne środowiskowe obowiązują w bieżącym terminalu; po ich zmianie trzeba zatrzymać Uvicorna (`Ctrl+C`) i uruchomić go ponownie (`--reload` tego nie zapewnia).

W drugim terminalu: `Invoke-RestMethod http://localhost:8101/health` albo `curl.exe -i http://localhost:8101/memberships/M-001` (nagłówek `x-cache`). Dokumentacja: [Swagger UI](http://localhost:8101/docs). Zatrzymanie serwera: `Ctrl+C`. Nie trzeba aktywować środowiska.


## 1. Problem i granice

### 1.1. Problem: 
Klub fitness prowadzi zajęcia grupowe z limitem miejsc. Bez jednego źródła prawdy o karnetach na zajęcia zapisują się osoby z nieważnym lub zawieszonym karnetem, a recepcja nie ma jak szybko sprawdzić uprawnień członka.

### 1.2. Użytkownicy:
Członek klubu (sprawdza karnet, zawiesza go), recepcja (zakłada, zawiesza i wznawia karnety), inne usługi systemu (Booking Service sprawdza ważność karnetu przy zapisie na zajęcia).

### 1.3. Usługa odpowiada za:
- przechowywanie karnetów członków i ich okresu ważności
- typy karnetów (open, morning, gym_only)
- zawieszanie i wznawianie karnetu

### 1.4. Usługa nie odpowiada za:
- dane osobowe członków (przechowuje tylko member_id)
- płatności za karnety
- trenerów, zajęcia i zapisy na zajęcia

### 1.5. Pojęcia domenowe:
- **Członek** - osoba z kontem w klubie, identyfikowana przez member_id (np. U-100). Jej dane należą do innej usługi.
- **Karnet** - uprawnienie członka do korzystania z klubu w okresie od - do
- **Typ karnetu** - wariant oferty: open (bez ograniczeń), morning (tylko rano), gym_only (bez zajęć grupowych)
- **Zawieszenie** - czasowe wstrzymanie karnetu na 1–30 dni. Przesuwa valid_to o liczbę dni zawieszenia
- **Aktualny karnet** - karnet w statusie active lub suspended; członek może mieć tylko jeden

| Planowana usługa                   | Odpowiedzialność | Własne dane | Operacje | Potrzebne informacje od innej usługi     |
|------------------------------------|---|---|---|------------------------------------------|
| Pierwsza — implementowana teraz - Membership Service (port 8101) | karnety członków i ich ważność | karnety: member_id, typ, okres ważności, status, data końca zawieszenia| lista, szczegóły, założenie karnetu, zawieszenie, wznowienie| czy członek o danym ```member_id``` istnieje |
|Druga — implementowana później: **Trainer Service** | trenerzy i ich dostępność | trenerzy, specjalizacje, bloki dostępności | dodanie trenera, dodanie i usunięcie bloku dostępności, odczyt grafiku trenera | brak — jest źródłem danych dla Class Service |

### 1.6. Granice i właściciele danych
Karnety zapisuje wyłącznie Membership Service (zmiany zleca recepcja, zawieszenie także członek). Dostępność trenera zapisuje wyłącznie Trainer Service (zmienia ją trener). Pozostałe usługi systemu realizuje druga osoba w parze: Class Service (zajęcia, limity miejsc) i Booking Service (zapisy, lista rezerwowa). Podział wynika z odpowiedzialności biznesowej, a nie z tabel. Membership odpowiada na pytanie czy członek ma prawo korzystać z klubu, a Booking czy ma miejsce na konkretnych zajęciach. To różne reguły, zmieniane przez różne osoby i z różną częstotliwością.

### Przyszłe wywołanie HTTP
- Nadawca: Booking Service, odbiorca: Membership Service,
- metoda i ścieżka: ``GET /memberships?member_id=U-100`` (filtr do dodania w kolejnych etapach)
- żądanie: brak body, parametr ``member_id``w adresie,
- odpowiedź 200: <br>
``  [{"id": "M-001", "member_id": "U-100", "type": "open", "valid_from": "2026-10-01", "valid_to": "2026-12-31", "status": "active", "suspended_until": null}]``
- karnet active i typ inny niż gym_only -> Booking tworzy zapis <br> pusta lista, inny status lub gym_only -> Booking odrzuca zapis kodem 409,
- niedostępność odbiorcy (timeout 2 s lub błąd połączenia) -> Booking zwraca 503 i nie tworzy zapisu.

## 2. Model i reguła biznesowa

Model `Membership`:
- `id` - `str`, nadaje serwer w formacie `M-001`, `M-002`, ... (klient nie może utworzyć duplikatu ani nadpisać karnetu),
- `member_id` - `str`, wymagane, 1–50 znaków,
- `type` - wymagane, jedna z wartości `open`, `morning`, `gym_only`,
- `valid_from`, `valid_to` — daty `RRRR-MM-DD`, wymagane, `valid_to` musi być późniejsze niż `valid_from`,
- `status` - nadaje serwer: `active`, `suspended` albo `expired`; nowy karnet ma `active`,
- `suspended_until` - data końca zawieszenia albo `null`.

Dane początkowe (tworzone przy każdym starcie):
- `M-001` - członek `U-100`, `open`, 2026-10-01 – 2026-12-31, `active`,
- `M-002` - członek `U-200`, `morning`, 2026-09-01 – 2026-11-30, `suspended` do 2026-10-25.

**Reguła biznesowa:** zawiesić można tylko karnet w statusie `active`, na 1 do 30 dni. Zawieszenie przesuwa `valid_to` o liczbę dni zawieszenia, żeby członek nie tracił opłaconego okresu.
- dozwolone: `PATCH /memberships/M-001/suspend` z `{"days": 14}` → 200, status `suspended`, `valid_to` 2026-12-31 → 2027-01-14,
- niedozwolone: `PATCH /memberships/M-001/suspend` z `{"days": 45}` → 422, karnet bez zmian,
- niedozwolone: `PATCH /memberships/M-002/suspend` z `{"days": 5}` (karnet już `suspended`) → 409, karnet bez zmian.

Dodatkowo: członek może mieć tylko jeden aktualny karnet (drugi POST dla tego samego `member_id` → 409), a wznowić można tylko karnet `suspended` (inaczej 409). Wszystkie warunki odrzucenia są sprawdzane przed zapisem do magazynu.


## 3. Kontrakt API


| Metoda | Ścieżka | Znaczenie | Sukces | Błędy |
|---|---|---|---|---|
| GET | `/health` | Status i nazwa usługi | 200 | — |
| GET | `/memberships` | Lista karnetów | 200 | — (pusta lista to 200 i `[]`) |
| GET | `/memberships/{membership_id}` | Szczegóły karnetu | 200 | 404 |
| POST | `/memberships` | Utworzenie karnetu | 201 | 409, 422 |
| PATCH | `/memberships/{membership_id}/suspend` | Zawieszenie karnetu | 200 | 404, 409, 422 |
| PATCH | `/memberships/{membership_id}/resume` | Wznowienie karnetu | 200 | 404, 409 |

Pola żądań:
- `POST /memberships` — body: `member_id` (`str`, 1–50 znaków), `type` (`open` | `morning` | `gym_only`), `valid_from` (data), `valid_to` (data, późniejsza niż `valid_from`); wszystkie wymagane.
- `PATCH /memberships/{membership_id}/suspend` — body: `days` (`int`, 1–30), wymagane.
- `PATCH /memberships/{membership_id}/resume` — bez body.

Odpowiedź sukcesu każdego endpointu domenowego to obiekt `Membership` (lub lista takich obiektów) z polami opisanymi w sekcji 2.

`GET /health` → 200
```json
{"status": "ok", "service": "membership-service"}
```

`GET /memberships/M-001` → 200
```json
{"id": "M-001", "member_id": "U-100", "type": "open", "valid_from": "2026-10-01", "valid_to": "2026-12-31", "status": "active", "suspended_until": null}
```

`POST /memberships` z body:
```json
{"member_id": "U-300", "type": "gym_only", "valid_from": "2026-11-01", "valid_to": "2027-01-31"}
```
→ 201
```json
{"id": "M-003", "member_id": "U-300", "type": "gym_only", "valid_from": "2026-11-01", "valid_to": "2027-01-31", "status": "active", "suspended_until": null}
```

`PATCH /memberships/M-001/suspend` z body `{"days": 14}` → 200, w odpowiedzi `"status": "suspended"`, `"valid_to": "2027-01-14"`, `"suspended_until"` = dzisiejsza data + 14 dni.

`GET /memberships/M-999` → 404
```json
{"detail": "Membership not found"}
```

`POST /memberships` z `"member_id": "U-100"` (ma już aktywny karnet) → 409
```json
{"detail": "Member already has a current membership"}
```

`PATCH /memberships/M-002/suspend` z `{"days": 5}` → 409
```json
{"detail": "Cannot suspend membership with status 'suspended'"}
```

`PATCH /memberships/M-001/resume` (karnet `active`) → 409
```json
{"detail": "Cannot resume membership with status 'active'"}
```

`PATCH /memberships/M-001/suspend` z `{"days": 45}` → 422
```json
{"detail": [{"type": "less_than_equal", "loc": ["body", "days"], "msg": "Input should be less than or equal to 30", "input": 45, "ctx": {"le": 30}}]}
```

`POST /memberships` z `"valid_from": "2026-12-01"` i `"valid_to": "2026-11-01"` → 422
```json
{"detail": [{"type": "value_error", "loc": ["body"], "msg": "Value error, valid_to must be after valid_from", "input": {"member_id": "U-300", "type": "open", "valid_from": "2026-12-01", "valid_to": "2026-11-01"}, "ctx": {"error": {}}}]}
```

**Format `detail`:** błędy zgłaszane przez `HTTPException` (404, 409) mają w `detail` tekst. Błędy walidacji FastAPI/Pydantic (422) mają w `detail` listę obiektów z polami `type`, `loc` (miejsce błędu), `msg` (opis) i `input` (odrzucona wartość).

**Dobór kodów:** 201 — POST tworzy nowy zasób z nowym `id`; 200 — odczyt lub zmiana istniejącego zasobu; 404 — zasób o podanym `id` nie istnieje; 422 — dane same w sobie są niepoprawne (zły typ, nieznany typ karnetu, daty w złej kolejności, zawieszenie spoza 1–30 dni), niezależnie od stanu magazynu; 409 — dane są poprawne, ale kolidują z aktualnym stanem (członek ma już karnet, karnet już zawieszony lub niezawieszony przy wznowieniu).


## 4. Testy i stan danych


Testy: `tests/test_memberships.py` (8 testów domenowych) i `tests/test_health.py` (test startowy). Fixture `client` tworzy dla każdego testu nową aplikację przez `create_app()`, więc każdy test zaczyna od danych początkowych M-001 i M-002 i nie zależy od kolejności uruchomienia.

| Scenariusz | Stan początkowy i dokładne żądanie | Oczekiwany status, treść i stan | Wynik rzeczywisty | Reset danych |
|---|---|---|---|---|
| Health | świeża aplikacja; `GET /health` | 200, `{"status": "ok", "service": "membership-service"}` | zgodny — `test_health` | nowa aplikacja z fixture |
| Lista i szczegóły | dane początkowe; `GET /memberships`, `GET /memberships/M-001` | 200; lista ma 2 karnety; M-001 ma `member_id` `U-100` i status `active` | zgodny — `test_list_and_details` | nowa aplikacja z fixture |
| Zapis → odczyt | dane początkowe; `POST /memberships` `{"member_id": "U-300", "type": "gym_only", "valid_from": "2026-11-01", "valid_to": "2027-01-31"}`, potem `GET /memberships/{id}` | 201, status `active`; GET zwraca 200 i karnet `U-300` | zgodny — `test_create_then_read` | nowa aplikacja z fixture |
| Brak zasobu | dane początkowe; `GET /memberships/M-999` | 404, `{"detail": "Membership not found"}` | zgodny — `test_unknown_membership_returns_404` | nowa aplikacja z fixture |
| Błędne dane | dane początkowe; `POST /memberships` z `valid_from` 2026-12-01 i `valid_to` 2026-11-01 | 422; lista nadal ma 2 karnety | zgodny — `test_invalid_dates_return_422_and_do_not_change_store` | nowa aplikacja z fixture |
| Konflikt | dane początkowe; `POST /memberships` z `"member_id": "U-100"` | 409, `detail` zawiera „current membership”; lista nadal ma 2 karnety | zgodny — `test_duplicate_current_membership_returns_409` | nowa aplikacja z fixture |
| Reguła biznesowa: dozwolona i niedozwolona operacja | M-001 `active`, M-002 `suspended`; `PATCH /memberships/M-001/suspend` `{"days": 14}`; `PATCH /memberships/M-001/suspend` `{"days": 45}`; `PATCH /memberships/M-002/suspend` `{"days": 5}` | 14 dni → 200, M-001 `suspended`, `valid_to` 2027-01-14; 45 dni → 422, M-001 bez zmian; M-002 → 409, M-002 bez zmian | zgodny — `test_suspend_active_membership_extends_validity`, `test_suspend_too_long_returns_422_and_keeps_state`, `test_suspend_already_suspended_returns_409_and_keeps_state` | nowa aplikacja z fixture |
| Restart | Uvicorn na porcie 8101 bez `--reload`; `POST /memberships` dla `U-300`, `GET /memberships`, `Ctrl+C`, ponowny start, `GET /memberships` | przed restartem 3 karnety (M-001, M-002, M-003); po restarcie 2 (M-001, M-002) | zgodny — sprawdzony ręcznie: przed restartem M-001, M-002, M-003; po restarcie M-001, M-002 | restart procesu |

Wynik testów (`.\.venv\Scripts\python.exe -m pytest -q`): `9 passed`.

**Eksperyment z restartem:** uruchomiono `.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8101` (bez `--reload`). W drugim terminalu wykonano `Invoke-RestMethod -Method Post -Uri http://localhost:8101/memberships -ContentType 'application/json' -Body $body` z `{"member_id": "U-300", "type": "open", "valid_from": "2026-11-01", "valid_to": "2027-01-31"}` — utworzony karnet M-003 ze statusem `active`. `GET /memberships` zwrócił 3 karnety (M-001, M-002, M-003). Po `Ctrl+C` i ponownym uruchomieniu tym samym poleceniem `GET /memberships` zwrócił 2 karnety (M-001, M-002) — M-003 zniknął.

Dane przetrwały między żądaniami, bo magazyn to słownik Pythona tworzony raz w `create_app()` i trzymany w pamięci działającego procesu Uvicorna. Po zatrzymaniu procesu pamięć jest zwalniana, a przy nowym starcie `create_app()` tworzy magazyn od nowa z danych początkowych.


## 5. Porównanie architektur

Monolit:
```
Klient
  |
  v
+------------------------------------------+
| Aplikacja klubu (1 proces)               |
|  karnety, trenerzy, zajęcia, zapisy      |
|  wymieszane, wywołania w kodzie          |
+------------------------------------------+
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
|  [Membership] [Trainer] [Class] [Booking]     |
|      ^                             |          |
|      +---- wywołanie w kodzie -----+          |
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
  +--> Membership Service (8101) --> dane: karnety
  +--> Trainer Service    (8102) --> dane: trenerzy, dostępność
  +--> Class Service      (8103) --> dane: zajęcia, limity
  +--> Booking Service    (8104) --> dane: zapisy, lista rezerwowa
            |
            +-- HTTP: GET /memberships?member_id=... --> Membership Service
            +-- HTTP: GET /classes/{id} --------------> Class Service
```

1. **Dlaczego twoja usługa może być mikrousługą i czym różni się od klasy/modułu?** Ma spójną odpowiedzialność biznesową (prawo do korzystania z klubu), własne dane (karnety), działa jako osobny proces na własnym porcie i udostępnia API HTTP. Klasa lub moduł działałyby w tym samym procesie co reszta i byłyby wywoływane funkcją; Membership Service można uruchomić, zrestartować i wdrożyć niezależnie od zajęć i zapisów.
2. **Jak wyglądałby system jako monolit?** Jedna aplikacja z jedną bazą; przy zapisie na zajęcia kod zapisów wywoływałby bezpośrednio funkcję sprawdzającą karnet, np. `membership.is_active(member_id)`.
3. **Co zmieni podział na usługi, w tym koszty sieci i wpływ awarii zależności?** Każda usługa ma własne dane i może być rozwijana przez inną osobę. Kosztem są opóźnienia sieci, timeouty, obsługa niedostępności innych usług, brak jednej transakcji obejmującej kilka usług i trudniejsze testowanie całego przepływu. Awaria Membership Service nie wyłącza grafiku zajęć, ale blokuje nowe zapisy w Booking Service.
4. **Którą architekturę wybrałbyś dla obecnej skali problemu i dlaczego?** Dla jednego klubu wystarczyłby modularny monolit — mniej infrastruktury i brak problemów sieciowych. Mikrousługi byłyby uzasadnione przy sieci wielu klubów, osobnych zespołach i różnym obciążeniu (masowe zapisy na popularne zajęcia vs rzadkie zmiany karnetów). W projekcie stosujemy mikrousługi, bo jest to cel przedmiotu.


## 6. Dokumentacja wykorzystana podczas pracy

| Odnośnik do fragmentu | Rozwiązywany problem | Co zastosowano w kodzie | Jak sprawdzono działanie |
|---|---|---|---|
| [Body - Fields](https://fastapi.tiangolo.com/tutorial/body-fields/) | walidacja zakresu i długości danych wejściowych bez ręcznego sprawdzania | `Field(min_length=1, max_length=50)` dla `member_id`, `Field(ge=1, le=30)` dla `days` w modelach Pydantic | `test_suspend_too_long_returns_422_and_keeps_state`; ręcznie w `/docs`: `{"days": 45}` → 422 |
| [Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/) | zwracanie 404 i 409 z opisem zamiast błędu serwera | `HTTPException(status_code=404, detail=...)` w `get_or_404` oraz 409 w POST, suspend i resume | `test_unknown_membership_returns_404`, `test_duplicate_current_membership_returns_409`; ręcznie w `/docs`: `GET /memberships/M-999` → 404 |


## 7. Ograniczenia, autorzy i AI


Dane są przechowywane w pamięci procesu **(stan LAB1 — od LAB2 dane są w SQLite, patrz sekcja 8)** - restart (także wywołany przez `--reload`) usuwa zmiany i przywraca dane początkowe. Dwie instancje uruchomione na różnych portach mają osobne magazyny i nie współdzielą stanu. Inne ograniczenia:
- usługa nie sprawdza, czy `member_id` należy do istniejącego członka - dane członków należą do innej usługi, a komunikacja nie jest implementowana na LAB1,
- status `expired` nie jest ustawiany automatycznie po minięciu `valid_to`,
- karnet nie wraca sam do `active` po minięciu `suspended_until`; wznowienie jest ręczne (`/resume`),
- magazyn nie jest zabezpieczony przed równoczesnymi zapisami,
- pytest wyświetla `DeprecationWarning` z biblioteki Starlette, niezwiązany z kodem usługi.

- Autorzy i wkład każdej osoby:
  - Dominik — Membership Service: model, endpointy, reguła zawieszenia, testy, sekcja 1 README.
  - Julia — ujednolicenie komunikatów błędów z kontraktem API i testami (naprawa 2 testów), uzupełnienie README, ręczna weryfikacja endpointów w `/docs`, eksperyment z restartem.
- AI: Claude (Anthropic) —  fragmenty kodu usługi, testów i README. Weryfikacja: uruchomienie testów (`pytest -q` — `9 passed`), ręczne sprawdzenie endpointów i kodów 404/409/422 w `/docs`, eksperyment z restartem, przeczytanie i zrozumienie każdego fragmentu kodu.


## 8. LAB2 — trwałe dane i cache

### 8.1. Zmiany i decyzje

- **Co zachowano z LAB1:** domenę, granice usługi, model JSON, identyfikatory `M-001`…, wszystkie endpointy, kody 200/201/404/409/422, treść komunikatów błędów, regułę zawieszenia oraz fabrykę `create_app()`. Klient API nie widzi żadnej zmiany poza dodatkowym nagłówkiem `X-Cache` w `GET /memberships/{membership_id}`.
- **Co zmieniono i dlaczego:** słownik w pamięci zastąpiono bazą SQLite (SQLAlchemy 2.0), bo karnety muszą przetrwać restart procesu. Kod podzielono na moduły:
  - `app/models.py` — modele Pydantic (kontrakt API, przeniesione z `main.py`),
  - `app/db_models.py` — model ORM `MembershipRow` (tabela),
  - `app/database.py` — silnik i fabryka sesji (z paczki LAB2),
  - `app/repository.py` — operacje na bazie i reguła biznesowa,
  - `app/cache.py` — adapter Redis `JsonCache` (z paczki LAB2),
  - `app/main.py` — `create_app(database_url=None, redis_client=None)` z `lifespan` oraz endpointy.
- **Właściciel danych i granice drugiej usługi:** tabelę `memberships` zapisuje wyłącznie Membership Service. Nie przechowujemy danych osobowych członków, trenerów, zajęć ani zapisów — należą do innych usług (Trainer, Class, Booking) i te usługi nie powinny pisać do tej tabeli; o karnet pytają przez HTTP (kontrakt z sekcji 1.7).
- **Model tabeli `memberships`:**

  | Kolumna | Typ | Ograniczenia |
  |---|---|---|
  | `id` | `VARCHAR(16)` | klucz główny (unikalność id) |
  | `member_id` | `VARCHAR(50)` | indeks (wyszukiwanie aktualnego karnetu członka) |
  | `type` | `VARCHAR(20)` | `CHECK type IN ('open','morning','gym_only')` |
  | `valid_from`, `valid_to` | `DATE` | `CHECK valid_to > valid_from` |
  | `status` | `VARCHAR(20)` | `CHECK status IN ('active','suspended','expired')` |
  | `suspended_until` | `DATE` | może być `NULL` |

  Jedna tabela, bez powiązań — usługa ma jeden agregat (karnet). Ograniczenia `CHECK` są drugą linią obrony; walidację wejścia nadal robi Pydantic (SQLite nie egzekwuje długości `String(n)`).
- **Co chroni baza, a co reguła biznesowa:** baza chroni unikalność `id` i podstawową poprawność wartości (`CHECK`). Reguła „zawieszenie tylko dla `active`, na 1–30 dni”, „jeden aktualny karnet na członka” i „wznowienie tylko `suspended`” są sprawdzane w `MembershipRepository` w ramach transakcji: odczyt stanu → sprawdzenie reguły → zmiana → commit. Wyjątek w bloku `with sessions.begin()` powoduje rollback, więc odrzucona operacja nie zostawia częściowej zmiany.
- **Zachowana reguła biznesowa:** `PATCH /memberships/M-001/suspend` z `{"days": 14}` → 200 (`suspended`, `valid_to` +14 dni); `{"days": 45}` → 422; ponowne zawieszenie `M-002` (już `suspended`) → 409, bez zmiany w bazie.
- **Nowe id:** największy numer w bazie + 1 (zamiast licznika w pamięci, który po restarcie zaczynałby od nowa).
- **Odczyt objęty cache:** `GET /memberships/{membership_id}` — najczęstszy odczyt (sprawdzenie karnetu przez recepcję i w przyszłości przez Booking Service). Lista nie jest cache’owana (wymagałaby unieważniania przy każdej zmianie dowolnego karnetu).
- **Dopuszczalna nieaktualność:** przy poprawnym unieważnieniu — brak (wpis jest usuwany po każdej zmianie). Przy nieudanym unieważnieniu stara wartość może być zwracana maksymalnie przez TTL (60 s). Dla podglądu karnetu to akceptowalne; decyzja o zapisie na zajęcia w Booking Service nie powinna jednak opierać się wyłącznie na kopii z cache.
- **Prefiks, klucz, TTL, unieważnianie:** klucz `{CACHE_PREFIX}:membership:{id}`, np. `lab2:albumNUMER:membership-service:membership:M-001`; TTL 60 s (`CACHE_TTL_SECONDS`); po udanym `suspend` i `resume` — najpierw commit w bazie, potem `DEL` klucza. `POST` nie unieważnia cache, bo tworzy nowe `id`, a odpowiedzi 404 nie są cache’owane.
- **Awarie Redis:** `JsonCache` ma timeout 0,3 s i brak ponowień. Błąd `GET` → odczyt z bazy (`X-Cache: BYPASS`); błąd `SET` → odpowiedź z bazy oznaczona `BYPASS`; błąd `DEL` → zmiana w bazie pozostaje zatwierdzona, w logu pojawia się ostrzeżenie `Invalidation failed; old value may survive until TTL`.

### 8.2. Testy automatyczne

Wynik: `.\.venv\Scripts\python.exe -m pytest -q` → `15 passed`.

`tests/conftest.py` zawiera zamiennik `MemoryRedis` (z paczki LAB2) i fixture `client`: każdy test dostaje nową bazę w `tmp_path`, pusty `MemoryRedis` i aplikację uruchomioną przez `with TestClient(create_app(...))` (wykonuje `lifespan`). Testy nie zależą od kolejności i nie wymagają Redis ani pliku `app.db`.

- Zachowane testy LAB1 (bez zmian w asercjach): `tests/test_health.py`, `tests/test_memberships.py` (8 testów) — teraz działają na bazie.
- Nowe testy LAB2 (`tests/test_persistence_and_cache.py`):

| Test | Co wykazuje |
|---|---|
| `test_changes_survive_new_app_instance` | **trwałość:** POST (M-003) i zawieszenie M-001 w pierwszej instancji; druga instancja z tym samym plikiem bazy i pustym cache zwraca M-003 i zawieszony M-001 z `X-Cache: MISS`; `seed()` nie nadpisuje zmian |
| `test_miss_then_hit_reads_database_once` | **HIT/MISS:** pierwszy GET `MISS`, drugi `HIT`, ta sama treść; licznik wywołań `repository.get` = 1; TTL wpisu = 60 |
| `test_suspend_invalidates_cache` | **unieważnienie:** po HIT i `PATCH suspend` klucz znika z Redis, następny GET → `MISS` z nowym statusem i `valid_to` |
| `test_redis_outage_does_not_block_read_or_write` | **awaria cache:** przy niedostępnym Redis GET → 200 `BYPASS`, PATCH → 200, POST → 201; po powrocie Redis dane z bazy są aktualne |
| `test_failed_invalidation_can_leave_stale_value` | **ograniczenie:** po nieudanym `DEL` cache zwraca starą wartość (`HIT`, `active`), choć w bazie jest `suspended` |
| `test_rejected_suspend_rolls_back_and_keeps_database_state` | **rollback:** 409 przy zawieszeniu M-002, stan w bazie (odczyt z repozytorium z pominięciem cache) bez zmian |

`MemoryRedis` nie symuluje upływu TTL — wygaśnięcie sprawdzono ręcznie z prawdziwym Redis (8.3).

### 8.3. Dowody — ręczne scenariusze z rzeczywistym Redis

Środowisko: Redis 7 w Dockerze (`lab2-redis`), Uvicorn na porcie 8101 bez `--reload`, `$key = "${env:CACHE_PREFIX}:membership:M-001"`. Stan początkowy: usunięty `app.db` (świeże dane M-001, M-002) i usunięty klucz `$key`. GET przez `curl.exe -i`, PATCH przez Swagger UI.

| Scenariusz | Stan początkowy i żądanie | Oczekiwany wynik | Wynik rzeczywisty | Reset |
|---|---|---|---|---|
| MISS → HIT | pusty cache, TTL 60; 2× `GET /memberships/M-001`, `redis-cli TTL $key` | MISS, potem HIT, ta sama treść; TTL ≤ 60 | MISS, HIT (`active`); TTL = 42 | `redis-cli DEL $key` |
| Wygaśnięcie TTL | wpis w cache; odczekanie > 60 s; `TTL $key`, GET | TTL = -2, GET → MISS | TTL = -2; GET → MISS; nowy TTL = 43 | samoczynnie po TTL |
| Reguła: sukces i odrzucenie bez zmiany | M-001 `active` (w cache, HIT); `PATCH M-001/suspend {"days": 45}`; `{"days": 14}`; `PATCH M-002/suspend {"days": 5}`; GET M-002 | 422; 200 `suspended`, `valid_to` 2027-01-14; 409; M-002 bez zmian | 422; 200 `suspended`, `valid_to` 2027-01-14, `suspended_until` 2026-11-09; 409; M-002 `suspended`, `valid_to` 2026-11-30 | usunięcie `app.db` |
| Zmiana i unieważnienie | M-001 w cache (HIT); `PATCH M-001/suspend {"days": 14}`; `redis-cli EXISTS $key`; GET | EXISTS = 0; GET → MISS z nowym stanem | EXISTS = 0; GET → MISS, `suspended`, `valid_to` 2027-01-14 | — |
| Zapis i odczyt po restarcie bez cache | M-001 zawieszony; `Ctrl+C`, ponowny start Uvicorna; `redis-cli DEL $key`; GET | MISS, nadal `suspended`, `valid_to` 2027-01-14 | MISS, `suspended`, `valid_to` 2027-01-14 — zmiana przetrwała restart, dane z bazy | usunięcie `app.db` |
| Awaria GET i DELETE cache | `redis-cli DEL $key`; `docker stop lab2-redis`; GET; `PATCH M-001/resume`; `docker start lab2-redis`; GET | GET → 200 BYPASS; resume → 200 mimo nieudanego `DEL`; po starcie Redis GET → MISS, `active` | GET → 200 `BYPASS`; log `Cache unavailable; reading database`; resume → 200 `active`, log `Invalidation failed; old value may survive until TTL`; po `docker start` GET → MISS, `active` | `docker start lab2-redis` |
| Przywrócenie Redis, możliwa stara wartość | TTL 300; GET → MISS (`suspended` w cache, TTL 296); restart Uvicorna z `REDIS_URL=redis://127.0.0.1:9999/0`; GET; `PATCH M-001/resume`; restart z poprawnym adresem; GET; `TTL $key`; `DEL $key`; GET | BYPASS; resume 200 (`active` w bazie); po przywróceniu: HIT ze starym `suspended`; po `DEL` → MISS z `active` | BYPASS; resume → 200 `active`; po przywróceniu GET → **HIT, `suspended`** (stara wartość), TTL = 239; `DEL` = 1; GET → MISS, `active` | `redis-cli DEL $key`, przywrócenie `CACHE_TTL_SECONDS=60` |

Wnioski z eksperymentów:
- Dane przetrwały restart Uvicorna, bo są w pliku `app.db`, a nie w pamięci procesu; `seed()` wstawia dane początkowe tylko do pustej tabeli.
- HIT pokazuje, że odpowiedź pochodzi z cache i repozytorium nie zostało wywołane (potwierdza to licznik w teście). Nie dowodzi, że odczyt jest szybszy — dla jednego rekordu lokalny SQLite może być równie szybki jak Redis.
- Przy pierwszej próbie ostatniego scenariusza (TTL 60 s) wpis w cache wygasł przed powrotem Redis i stara wartość się nie pojawiła — TTL ogranicza czas, przez jaki może być zwracana nieaktualna odpowiedź.

### 8.4. Porównanie i ograniczenia

| Cecha | Pamięć procesu (LAB1) | SQLite (LAB2) | Redis jako cache (LAB2) |
|---|---|---|---|
| Rola | stan procesu | trwałe źródło prawdy | odtwarzalna kopia `GET /memberships/{id}` |
| Restart Uvicorna | zmiany znikają | plik `app.db` pozostaje | osobny proces, wpis może przetrwać do końca TTL |
| Brak danych | stan utracony | brak rekordu → 404 | MISS — normalna sytuacja |
| Trudność | utrata zmian | schemat, transakcje, błędy | aktualność, TTL, awarie |

1. **Co zmieniło się dla klienta API, a co wewnątrz usługi?** Dla klienta nic poza nagłówkiem `X-Cache` i tym, że zmiany przetrwają restart. Wewnątrz: magazyn (SQLite + SQLAlchemy), repozytorium z transakcjami, cache-aside w Redis, `lifespan` przygotowujący bazę i klienta Redis.
2. **Dlaczego baza i cache nie zmieniają automatycznie aplikacji w system mikroserwisowy?** To nadal jeden proces z jedną odpowiedzialnością. O mikrousługach decyduje podział odpowiedzialności, własność danych, niezależne wdrażanie i komunikacja przez sieć między usługami — baza i cache to tylko magazyny tej jednej usługi.
3. **Czy druga usługa powinna pisać do tych samych tabel?** Nie. Właścicielem tabeli `memberships` jest Membership Service. Booking Service pyta o karnet przez HTTP; wspólne tabele związałyby usługi schematem i pozwoliły obejść regułę zawieszenia.
4. **Skutki awarii:** awaria procesu aplikacji — usługa niedostępna, dane bezpieczne w `app.db`; awaria Redis — usługa działa wolniej/bez cache (`BYPASS`), ryzyko starej wartości po nieudanym unieważnieniu do końca TTL; awaria bazy — odczyty niebędące HIT i wszystkie zapisy kończą się błędem, a HIT może zwracać ostatnią kopię.
5. **Jakie opóźnienie aktualizacji dopuszcza odbiorca?** Recepcja przeglądająca karnet — do 60 s w razie awarii Redis. Booking Service przy zapisie na zajęcia — nie powinien polegać na cache; docelowo Membership powinna mu udostępnić odczyt z bazy (np. przez filtr `?member_id=` bez cache).
6. **Co wymaga sprawdzenia przy zmianie SQLite na PostgreSQL?** Sterownik (np. `psycopg`), `DATABASE_URL` i sekrety poza repozytorium, schemat (typy dat, ograniczenia `CHECK`, długości `VARCHAR` egzekwowane przez bazę), migracje (np. Alembic zamiast `create_all`), poziom izolacji transakcji i współbieżne zapisy oraz ponowne uruchomienie wszystkich testów.

Ograniczenia:
- usunięcie klucza z Redis i commit w bazie nie są jedną transakcją — po nieudanym unieważnieniu stara wartość może być zwracana do końca TTL (scenariusz z 8.3 i test `test_failed_invalidation_can_leave_stale_value`),
- prosty cache-aside nie zapewnia ścisłej spójności przy równoległych zapisach i odczytach (odczyt może zapisać do cache wartość sprzed równoległej zmiany),
- warunek „jeden aktualny karnet na członka” i nadawanie kolejnego `id` nie są chronione przed równoczesnymi żądaniami (brak blokad / unikalnego indeksu częściowego); dwa równoległe POST mogą skończyć się 409 z błędu unikalności `id`,
- `create_all` tworzy brakujące tabele, ale nie zmienia istniejących kolumn — zmiana schematu wymaga usunięcia `app.db` albo migracji,
- awaria samego `SET` jest obsłużona w kodzie (odpowiedź `BYPASS`), ale nie została osobno sprawdzona testem API ani ręcznie,
- statusy `expired` i automatyczne wznowienie po `suspended_until` nadal nie są realizowane (jak w LAB1).

### 8.5. Dokumentacja wykorzystana w LAB2

| Źródło | Problem | Zastosowanie | Weryfikacja |
|---|---|---|---|
| [SQLAlchemy — Session Basics: Framing out a begin / commit / rollback block](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#framing-out-a-begin-commit-rollback-block) | odrzucona operacja nie może zostawić częściowej zmiany | `with self.sessions.begin() as db:` w `MembershipRepository` — commit przy poprawnym wyjściu z bloku, rollback przy wyjątku; nowa sesja na każdą operację | `test_rejected_suspend_rolls_back_and_keeps_database_state`, `test_suspend_already_suspended_returns_409_and_keeps_state`; ręcznie: 409 dla M-002 i niezmieniony M-002 |
| [redis-py — Connecting to Redis](https://redis.readthedocs.io/en/stable/connections.html) | niedostępny Redis nie może blokować API | `Redis.from_url(..., socket_connect_timeout=0.3, socket_timeout=0.3, retry=Retry(NoBackoff(), 0))` w `make_redis` i łapanie `RedisError` w `JsonCache` | `test_redis_outage_does_not_block_read_or_write`; ręcznie: `docker stop lab2-redis` → GET 200 `BYPASS` |
| [FastAPI — Testing Events: lifespan and startup/shutdown](https://fastapi.tiangolo.com/advanced/testing-events/) | baza i Redis tworzone w `lifespan` muszą istnieć w testach | fixture `client` w `conftest.py` używa `with TestClient(app)`, co uruchamia `lifespan` | wszystkie 15 testów; bez `with` testy kończą się błędem braku `app.state.repository` |

### 8.6. Autorzy, AI i kolejny etap

- Wkład: Dominik — usługa i dokumentacja LAB1; Julia — LAB2: baza SQLite, cache Redis, testy, ręczne scenariusze i dokumentacja LAB2.
- AI: Claude (Anthropic) — szkic fragmentów kodu bazy, cache, testów LAB2 i README; `database.py` i `cache.py` z paczki LAB2 bez zmian. Weryfikacja: `pytest -q` (`15 passed`), ręczne scenariusze z 8.3, przeczytanie i omówienie kodu.
- Kolejny etap: rejestracja Membership Service w Eurece (LAB3). Druga usługa bez zmian w planie: Trainer Service (sekcja 1.5).