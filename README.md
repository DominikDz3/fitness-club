# Membership Service — LAB1

Pierwsza usługa systemu zarządzania klubem fitness. Obsługuje karnety członków klubu: ich zakładanie, odczyt oraz zawieszanie i wznawianie.
## Uruchomienie i testy

Wymagania: Python 3.12 lub nowszy, PowerShell. Otwórz terminal w katalogu z tym README i `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8101
```

W drugim terminalu: `Invoke-RestMethod http://localhost:8101/health`. Dokumentacja: [Swagger UI](http://localhost:8101/docs). Zatrzymanie serwera: `Ctrl+C`. Nie trzeba aktywować środowiska.

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


Dane są przechowywane w pamięci procesu - restart (także wywołany przez `--reload`) usuwa zmiany i przywraca dane początkowe. Dwie instancje uruchomione na różnych portach mają osobne magazyny i nie współdzielą stanu. Inne ograniczenia:
- usługa nie sprawdza, czy `member_id` należy do istniejącego członka - dane członków należą do innej usługi, a komunikacja nie jest implementowana na LAB1,
- status `expired` nie jest ustawiany automatycznie po minięciu `valid_to`,
- karnet nie wraca sam do `active` po minięciu `suspended_until`; wznowienie jest ręczne (`/resume`),
- magazyn nie jest zabezpieczony przed równoczesnymi zapisami,
- pytest wyświetla `DeprecationWarning` z biblioteki Starlette, niezwiązany z kodem usługi.

- Autorzy i wkład każdej osoby:
  - Dominik — Membership Service: model, endpointy, reguła zawieszenia, testy, sekcja 1 README.
  - Julia — ujednolicenie komunikatów błędów z kontraktem API i testami (naprawa 2 testów), uzupełnienie README, ręczna weryfikacja endpointów w `/docs`, eksperyment z restartem.
- AI: Claude (Anthropic) —  fragmenty kodu usługi, testów i README. Weryfikacja: uruchomienie testów (`pytest -q` — `9 passed`), ręczne sprawdzenie endpointów i kodów 404/409/422 w `/docs`, eksperyment z restartem, przeczytanie i zrozumienie każdego fragmentu kodu.
