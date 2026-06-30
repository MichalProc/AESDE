# System Monitorowania Jakości Danych Pogodowych
**Autorzy:** Michał Proc 198407, Maciej Skibiński 198247  

---

## Wstęp i Cel Projektu
Raport końcowy ma na celu opis autorskiego systemu do weryfikacji i kontroli jakości danych meteorologicznych. Założeniem projektu było stworzenie niezawodnego mechanizmu, który w stałych odstępach czasu zbiera dane ze stacji meteorologicznej GDN_01 za pośrednictwem interfejsu REST API, zapisuje surowe dane, po czym ocenia ich poprawność i zapisuje błędne wyniki. 

Zaprojektowany algorytm na bieżąco oddziela poprawne obserwacje od zakłóceń sprzętowych, automatycznie sugerując optymalne techniki w przypadku zamiaru implementacji danych do dalszych systemów analitycznych. 

## Architektura Systemu
Rozwiązanie bazuje na programie napisanym w języku Python. Cały proces przetwarzania napływających informacji podzielono na następujące etapy:

### Pobieranie API i Magazynowanie Surowych Danych
Do komunikacji ze źródłem danych (REST API) użyto biblioteki `requests`. W celu zachowania pełnej historii zebranych danych, przed jakąkolwiek modyfikacją lub czyszczeniem, każdy odebrany z serwera pakiet JSON jest natychmiast dopisywany do pliku `raw_data_GDN_01.jsonl`. 

```python
# Pobieranie danych z REST API i zapis do pliku w formacie JSONL.
def fetch_api(endpoint: str, params: dict) -> dict:
    url = f"{API_BASE_URL}{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()

def save_to_jsonl(filename: str, data: dict):
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data) + "\n")

# Wywolanie wewnatrz glownej petli programu:
raw_data = fetch_api("/latest", {"station_id": STATION_ID})
save_to_jsonl(f"raw_data_{STATION_ID}.jsonl", raw_data)
```

```json
{
    "timestamp": "2026-06-14T09:13:50.173730+00:00", 
    "station_id": "GDN_01", 
    "temperature": 13.73, 
    "humidity": 83.0, 
    "pressure": 998.94, 
    "wind_speed": 0.68, 
    "wind_direction": 94, 
    "rain_mm": 0.37, 
    "cloud_cover": 33
}
```

### Silnik Walidacyjny i Ocena Jakości
Głównym elementem systemu jest klasa `DataQualityValidator`. Działa ona w oparciu o pamięć podręczną, przechowując w buforze 10 ostatnich stanów pogody, co umożliwia wykrywanie anomalii w czasie. Metoda `validate_record` na bieżąco analizuje każdy nowy odczyt pod kątem:
* **Występowania braków:** Wyszukiwanie pustych wartości typu `Null` w kluczowych polach.
* **Ograniczeń fizycznych:** Upewnienie się, że odczyty mieszczą się w dopuszczalnym przedziale (np. procentowe zachmurzenie między 0 a 100%).
* **Ciągłości i stabilności zjawisk:** Śledzenie nienaturalnych skoków wartości pomiędzy kolejnymi pomiarami.

```python
# Fragment metody walidującej parametry pogodowe w klasie DataQualityValidator.
def validate_record(self, current: WeatherRecord) -> List[str]:
    errors = []

    # 1. Wystepowanie brakow
    if self._is_empty(current.temperature): 
        errors.append("Brak danych: temperature")
    
    # 2. Ograniczenia fizyczne (zakresy)
    if not (-50 <= current.temperature <= 50): 
        errors.append(f"Temperature {current.temperature} poza zakresem")        
    if not (0 <= current.humidity <= 100): 
        errors.append(f"Humidity {current.humidity} poza zakresem")

    # 3. Ciaglosc i stabilnosc zjawisk (skoki wartosci)
    if self.history:
        prev = self.history[-1]
        
        if abs(current.temperature - prev.temperature) > 10: 
            errors.append("Skok Temp: Roznica > 10C")            
        if abs(current.humidity - prev.humidity) > 30: 
            errors.append("Skok Hum: Roznica > 30%")
            
        if self._check_stuck('temperature', 10, current.temperature): 
            errors.append("Stuck sensor: Temp (10)")

        self._update_history(current)
        return errors
```

### Mechanizm Kwarantanny i Raportowania
Kiedy system natrafi na uszkodzony odczyt, działanie programu nie jest przerywane. Zamiast tego, nielogiczny rekord trafia do wyizolowanego pliku `quarantine_invalid_GDN_01.jsonl`. Równolegle, tworzony jest zapis zawierający procentową ocenę jakości danego pomiaru (tzw. *Quality Score*), informujący o tym, ile parametrów w danym odczycie było poprawnych.

```json
{
    "raw_record": {
        "timestamp": "2026-06-13T19:42:58.552233+00:00",
        "station_id": "GDN_01",
        "temperature": 19.96,
        "humidity": 45.7,
        "pressure": 1024.02,
        "wind_speed": 10.75,
        "wind_direction": 82,
        "rain_mm": 2.82,
        "cloud_cover": 25
    },
    "errors": [
        "Skok Hum: Roznica > 30%"
    ],
    "cleaning_recommendations": [
        "Zmien bledna wartosc na Null, a nastepnie uzyj interpolacji liniowej do wygladzenia wykresu."
    ],
    "quality_score_percent": 85.71428571428571
}
```

```json
{"timestamp": "2026-06-13T20:13:00.423022+00:00", "status": "rekord poprawny", "quality_score_percent": 100.0}
{"timestamp": "2026-06-13T20:28:01.555132+00:00", "status": "rekord poprawny", "quality_score_percent": 100.0}
{"timestamp": "2026-06-13T20:43:02.331571+00:00", "status": "blad", "quality_score_percent": 85.71428571428571}
{"timestamp": "2026-06-13T20:58:03.374957+00:00", "status": "blad", "quality_score_percent": 85.71428571428571}
{"timestamp": "2026-06-13T21:13:04.420223+00:00", "status": "blad", "quality_score_percent": 85.71428571428571}
{"type": "cumulative_summary", "timestamp": "2026-06-13T23:13:05.418615", "total_analyzed_from_start": 20, "total_errors_from_start": 9}
```

## Założenia Systemu

### Zdefiniowane Kryteria Poprawności
Aplikacja weryfikuje 7 kluczowych atrybutów pogodowych. Do najważniejszych reguł śledzących spójność w czasie należą:
* **Cały rekord:**
  * Brak pustych wartości (każdy wymagany parametr musi zostać przekazany).
  * Brak duplikatów (weryfikacja unikalności na podstawie znacznika czasu `timestamp`).
* **Temperatura (`temperature`):**
  * Zakres fizyczny: od -50°C do +50°C.
  * Fluktuacje: skok względem poprzedniego odczytu nie może być większy lub mniejszy niż 10°C.
  * Detekcja błędu sprzętowego: "zacięty" czujnik flagowany po 10 identycznych odczytach.
  * Weryfikacja krzyżowa (cross-check) z wilgotnością.
* **Wilgotność (`humidity`):**
  * Zakres fizyczny: od 0% do 100%.
  * Fluktuacje: skok względem poprzedniego odczytu nie może przekraczać 30%.
  * Detekcja błędu sprzętowego: "zacięty" czujnik flagowany po 5 identycznych odczytach.
  * Weryfikacja krzyżowa (cross-check) z temperaturą.
* **Ciśnienie (`pressure`):**
  * Zakres fizyczny: od 980 hPa do 1050 hPa.
  * Fluktuacje: skok względem poprzedniego odczytu nie może przekraczać 15 hPa.
  * Detekcja błędu sprzętowego: "zacięty" czujnik flagowany po 10 identycznych odczytach.
* **Prędkość wiatru (`wind_speed`):**
  * Zakres fizyczny: od 0 do 200 km/h.
  * Zjawisko może ulegać drastycznym zmianom (brak limitu fluktuacji).
  * Detekcja błędu sprzętowego: "zacięty" czujnik flagowany po 3 identycznych odczytach.
* **Kierunek wiatru (`wind_direction`):**
  * Zakres geometryczny: od 0° do 360°.
* **Opady (`rain_mm`):**
  * Zakres fizyczny: od 0 do 100 mm (z zachowaniem możliwości kalibracji dla warunków ekstremalnych).
  * Zjawisko może ulegać drastycznym zmianom.
  * Spójność logiczna: jeśli opad przekracza 5 mm, zachmurzenie (`cloud_cover`) musi być wyższe niż 5%.
  * Detekcja błędu sprzętowego: "zacięty" czujnik flagowany po 5 identycznych odczytach (weryfikowane wyłącznie dla wartości większych od zera).
* **Zachmurzenie (`cloud_cover`):**
  * Zakres fizyczny: od 0% do 100%.
  * Zjawisko może ulegać drastycznym zmianom.
  * Detekcja błędu sprzętowego: "zacięty" czujnik flagowany po 10 identycznych odczytach.

**Dodatkowe mechanizmy walidacyjne (weryfikacja statystyczna):** W ramach weryfikacji wartości odstających, system uwzględnia (lub pozwala na łatwą implementację) mechanizm oceny poszczególnych parametrów pod kątem odchyleń od średniej kroczącej z 5 poprzednich pomiarów. Tego typu rozwiązanie redukuje ryzyko fałszywych alarmów przy płynnych, lecz silnych zmianach frontów atmosferycznych.

### Znane Ograniczenia
Aktualna implementacja wykorzystuje pamięć operacyjną do przechowywania bufora historycznego. Oznacza to, że w przypadku awarii lub zrestartowania programu, system musi najpierw jednorazowo odpytać punkt końcowy API `/batch`, aby zrekonstruować 10 ostatnich odczytów i przywrócić kontekst niezbędny do walidacji.

## Analiza Danych 
W ramach testów uruchomiono aplikację w trybie ciągłego nasłuchu. Zgromadzono próbkę składającą się z 70 kolejnych pomiarów ze stacji GDN_01.

### Przegląd Zidentyfikowanych Anomalii
Na 70 przeanalizowanych rekordów, system oflagował problemy z jakością danych aż w 31 przypadkach. Taki wynik wzkazuje na błąd w działaniu aparatury meteorologicznej lub na zastosowanie za bardzo rygorystycznych kryteriów przy sprawdzaniu błędów.

Zdecydowanie najczęściej obserwowanym zjawiskiem były gwałtowne skoki ciśnienia (powyżej 15 hPa na kwadrans), co obniżało *Quality Score* pojedynczego pomiaru do poziomu 85,7%. Nierzadko towarzyszyły temu równie drastyczne skoki w zmierzonej wilgotności. Połączone błędy powodowały że ostateczny wynik wiarygodności takiego pomiaru wynosił 71,4%.

Ze względu na stabilność pogody w okresie testowania system nie wyłapał żadnych innych błędów, jednak podczas testowania działania programu pod względem wszystkich komunikatów za pomocą spreparowanych pomiarów stwierdzono poprawność wszystkich mechanizmów walidacji programu. 

### Zestawienie Ilościowe Zdiagnozowanych Błędów
Zebrane błędy podzielono na dwa występujące rodzaje. Znacząca liczba błędów związanych z skokami ciśnienia (18), sugeruje że czujnik ciśnień w badanej stacji meteorologcznej GDN_01 może być uszkodzony. Ilość błędów związanych ze skokiem wilgoci jest dwukrotnie mniejsza (9), co może być niewystarczające do wyciągania wniosków o czujniku pomiarowym. Zaobserwowano również 5 pomiarów w których oba zmierzone parametry zostały oflagowane jako błędne. 

| Zdiagnozowana Anomalia | Liczba Wystąpień | Procent [N=70] (%) |
| :--- | :---: | :---: |
| Skok Pres: Różnica > 15 hPa | 19 | 27,1% |
| Skok Hum: Różnica > 30% | 8 | 11,4% |
| *W tym rekordy wykazujące oba błędy naraz:* | *5* | *7,1%* |

### Dynamika Przyrostu Błędów
Aby zilustrować częstotliwość występowania błędnych odczytów, przygotowano poniższe zestawienie. Ukazuje ono skumulowaną sumę flagowanych przez system anomalii w zestawieniu z ogólną liczbą zebranych pakietów (dane z zapisów `report_GDN_01.jsonl`).

<img width="668" height="427" alt="image" src="https://github.com/user-attachments/assets/31ee2ced-e33e-4672-bf94-bfd2763ddfb0" />

## Podsumowanie
Opracowany potok danych z powodzeniem realizuje zadanie separacji wiarygodnych pomiarów od odczytów zniekształconych. Zgromadzone przez system statystyki jednoznacznie wykazują, że znaczny udział usterek sprzętowych (stanowiących niemal połowę flagowanych odczytów pod koniec nocnej sesji) potwierdza absolutną konieczność stosowania mechanizmów kwarantanny. Przekazanie nieoczyszczonych danych bezpośrednio do systemów uczenia maszynowego lub narzędzi analitycznych drastycznie obniżyłoby wiarygodność wyników końcowych, przed czym wdrożone rozwiązanie skutecznie i w pełni automatycznie chroni.
