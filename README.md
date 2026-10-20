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
| Druga — implementowana później     | ... | ... | ... | ...                                      |

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

Opisz pola, typy, wymagane wartości, statusy i sposób nadawania identyfikatorów. Zapisz jedną regułę wykraczającą poza typy, wymagane pola i unikalność identyfikatora. Podaj operację dozwoloną, niedozwoloną oraz kod błędu. Wszystkie warunki odrzucenia sprawdzaj przed zmianą stanu.

## 3. Kontrakt API

Minimum: **trzy endpointy domenowe i osobny `/health`**. Zastąp ścieżki własnymi nazwami; wybierz co najmniej jedną operację zapisu.

| Metoda | Ścieżka | Znaczenie | Sukces | Błędy |
|---|---|---|---|---|
| GET | `/health` | Status i nazwa usługi | 200 | ... |
| GET | `/...` | Lista | 200 | ... |
| GET | `/.../{id}` | Szczegóły | 200 | 404 |
| POST albo PATCH | `/...` albo `/.../{id}` | Utworzenie albo modyfikacja | 201 albo 200 | ... |

Dołącz przykładowe żądania i odpowiedzi JSON, także błędy `404`, `409` i `422`. Opisz format `detail`; standardowe błędy walidacji FastAPI mają inną treść niż `HTTPException`. Wyjaśnij dobór kodów i regułę biznesową. Przy samym `PATCH` podaj dane początkowe.

## 4. Testy i stan danych

Napisz minimum **trzy własne testy automatyczne**: zapis → odczyt, błędne dane bez zmiany stanu, konflikt bez zmiany stanu. Co najmniej jeden sprawdza regułę biznesową; jeśli żaden jej nie obejmuje, dodaj następny. Dostarczony test `/health` nie wlicza się do trzech.

Każdy test ma własną aplikację z `create_app()` i znany stan początkowy. Sprawdzaj kod odpowiedzi, istotne pola JSON i wynik ponownego odczytu. Do wspólnych fixture dla wielu plików możesz użyć `tests/conftest.py`.

| Scenariusz | Stan początkowy i dokładne żądanie | Oczekiwany status, treść i stan | Wynik rzeczywisty | Reset danych |
|---|---|---|---|---|
| Health | ... | ... | ... | ... |
| Lista i szczegóły | ... | ... | ... | ... |
| Zapis → odczyt | ... | ... | ... | ... |
| Brak zasobu | ... | ... | ... | ... |
| Błędne dane | ... | ... | ... | ... |
| Konflikt | ... | ... | ... | ... |
| Reguła biznesowa: dozwolona i niedozwolona operacja | ... | ... | ... | ... |
| Restart | ... | ... | ... | ... |

Scenariusze mogą współdzielić test, jeśli sprawdza wszystkie wskazane wymagania. Podaj wynik testów uruchomionych poleceniem ze wstępu.

Osobno uruchom Uvicorna, wykonaj zapis i odczyt przez HTTP, zatrzymaj go i uruchom ponownie. Zapisz rezultat. Wyjaśnij, dlaczego dane przetrwały między żądaniami, ale nie restart procesu. Nie zmieniaj kodu podczas eksperymentu (`--reload` restartuje aplikację).

## 5. Porównanie architektur

Narysuj małe schematy tego samego systemu: monolit, modularny monolit i mikrousługi. Zaznacz procesy, granice, dane i sposób komunikacji. Wyjaśnij:

1. Dlaczego twoja usługa może być mikrousługą i czym różni się od klasy/modułu?
2. Jak wyglądałby system jako monolit?
3. Co zmieni podział na usługi, w tym koszty sieci i wpływ awarii zależności?
4. Którą architekturę wybrałbyś dla obecnej skali problemu i dlaczego?

## 6. Dokumentacja wykorzystana podczas pracy

Wykorzystaj co najmniej dwa konkretne fragmenty oficjalnej dokumentacji. Przykładowe punkty startowe: [modele żądań](https://fastapi.tiangolo.com/tutorial/body/), [błędy](https://fastapi.tiangolo.com/tutorial/handling-errors/), [testowanie](https://fastapi.tiangolo.com/tutorial/testing/).

| Odnośnik do fragmentu | Rozwiązywany problem | Co zastosowano w kodzie | Jak sprawdzono działanie |
|---|---|---|---|
| ... | ... | ... | ... |
| ... | ... | ... | ... |

## 7. Ograniczenia, autorzy i AI

Opisz dane w pamięci, ich reset przy restarcie i brak wspólnego stanu między instancjami. Wskaż inne ograniczenia własnej implementacji.

- Autorzy i wkład każdej osoby: ...
- AI: narzędzie, zakres pomocy i sposób weryfikacji albo „nie korzystano”.

Przed oddaniem sprawdź instalację w nowym środowisku oraz kompletność README. Nie dołączaj `.venv`, cache Pythona ani sekretów. Każda osoba w parze samodzielnie wyjaśnia kod i wykonuje małą zmianę podczas odbioru. LAB1 to pierwsza usługa; wymaganie co najmniej dwóch różnych usług na osobę dotyczy całego projektu semestralnego.
