import requests
import json
import time
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any

API_BASE_URL = "https://e6uw49pbah.execute-api.us-east-1.amazonaws.com/dev/weather"
STATION_ID = "GDN_01"
TOKEN = "STUDENT_TOKEN_2026"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

@dataclass
class WeatherRecord:
    timestamp: str
    station_id: str
    temperature: float
    humidity: float
    pressure: float
    wind_speed: float
    wind_direction: float
    rain_mm: float
    cloud_cover: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            timestamp=data.get("timestamp"),
            station_id=data.get("station_id"),
            temperature=data.get("temperature"),
            humidity=data.get("humidity"),
            pressure=data.get("pressure"),
            wind_speed=data.get("wind_speed"),
            wind_direction=data.get("wind_direction"),
            rain_mm=data.get("rain_mm"),
            cloud_cover=data.get("cloud_cover")
        )

class DataQualityValidator:
    def __init__(self, history_size: int = 10):
        self.history: List[WeatherRecord] = []
        self.max_history = history_size
        self.total_params_per_record = 7 

    def _is_empty(self, value) -> bool:
        return value is None or value == ""

    def _check_stuck(self, attr: str, count: int, current_val) -> bool:
        if len(self.history) >= count:
            last_vals = [getattr(r, attr) for r in self.history[-count:]]
            return all(v == current_val for v in last_vals)
        return False

    def validate_record(self, current: WeatherRecord) -> List[str]:
        errors = []

        if self.history and current.timestamp == self.history[-1].timestamp:
            errors.append("Duplikat: Ten sam timestamp co w poprzednim pomiarze")
            return errors 

        if self._is_empty(current.temperature): errors.append("Brak danych: temperature")
        if self._is_empty(current.humidity): errors.append("Brak danych: humidity")
        if self._is_empty(current.pressure): errors.append("Brak danych: pressure")
        if self._is_empty(current.wind_speed): errors.append("Brak danych: wind_speed")
        if self._is_empty(current.wind_direction): errors.append("Brak danych: wind_direction")
        if self._is_empty(current.rain_mm): errors.append("Brak danych: rain_mm")
        if self._is_empty(current.cloud_cover): errors.append("Brak danych: cloud_cover")
        
        if errors:
            self._update_history(current)
            return errors

        if not (-50 <= current.temperature <= 50): errors.append(f"Temperature {current.temperature} poza zakresem")        
        if not (0 <= current.humidity <= 100): errors.append(f"Humidity {current.humidity} poza zakresem")
        if not (980 <= current.pressure <= 1080): errors.append(f"Pressure {current.pressure} poza zakresem")
        if not (0 <= current.wind_speed <= 200): errors.append(f"Wind_speed {current.wind_speed} poza zakresem")
        if not (0 <= current.wind_direction <= 360): errors.append(f"Wind_direction {current.wind_direction} poza zakresem")
        if not (0 <= current.rain_mm <= 100): errors.append(f"Rain_mm {current.rain_mm} poza zakresem")
        if not (0 <= current.cloud_cover <= 100): errors.append(f"Cloud_cover {current.cloud_cover} poza zakresem")

        if self.history:
            prev = self.history[-1]
            
            if abs(current.temperature - prev.temperature) > 10: errors.append("Skok Temp: Roznica > 10C")            
            if abs(current.humidity - prev.humidity) > 30: errors.append("Skok Hum: Roznica > 30%")
            if abs(current.pressure - prev.pressure) > 15: errors.append("Skok Pres: Roznica > 15 hPa")

            if self._check_stuck('temperature', 10, current.temperature): errors.append("Stuck sensor: Temp (10)")
            if self._check_stuck('pressure', 10, current.pressure): errors.append("Stuck sensor: Pres (10)")
            if self._check_stuck('cloud_cover', 10, current.cloud_cover): errors.append("Stuck sensor: Cloud (10)")
            if self._check_stuck('humidity', 5, current.humidity): errors.append("Stuck sensor: Hum (5)")
            if self._check_stuck('wind_speed', 3, current.wind_speed): errors.append("Stuck sensor: Wind (3)")
            if current.rain_mm > 0 and self._check_stuck('rain_mm', 5, current.rain_mm): 
                errors.append("Stuck sensor: Rain_mm (5)")

        if current.rain_mm > 5 and current.cloud_cover <= 5: 
            errors.append("Spojnosc: Deszcz przy braku chmur")

        self._update_history(current)
        return errors

    def get_cleaning_recommendations(self, errors: List[str]) -> List[str]:
        recs = set() 
        for err in errors:
            if "Brak danych" in err:
                recs.add("Uzyj 'forward fill' (ffill) w Pandas, aby skopiowac ostatnia znana poprawna wartosc.")
            elif "poza zakresem" in err or "Skok" in err:
                recs.add("Zmien bledna wartosc na Null, a nastepnie uzyj interpolacji liniowej do wygladzenia wykresu.")
            elif "Duplikat" in err:
                recs.add("Usun rekord z bazy uzywajac metody 'drop_duplicates' na kolumnie timestamp.")
            elif "Stuck sensor" in err:
                recs.add("Odrzuc rekord. Oflaguj czujnik stacji do fizycznej inspekcji/resetu.")
            elif "Spojnosc" in err:
                recs.add("Nadpisz wartosc opadow (rain_mm) na 0, ufajac wskazaniom czujnika zachmurzenia (cloud_cover).")
        return list(recs)

    def _update_history(self, record: WeatherRecord):
        self.history.append(record)
        if len(self.history) > self.max_history:
            self.history.pop(0)

def fetch_api(endpoint: str, params: dict) -> dict:
    url = f"{API_BASE_URL}{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()

def save_to_jsonl(filename: str, data: dict):
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data) + "\n")

def init_history(validator: DataQualityValidator):
    print("Inicjalizacja: Pobieranie 10 ostatnich pomiarow...")
    data = fetch_api("/batch", {"station_id": STATION_ID, "limit": 10})
    records = data.get("records", [])
    
    cumulative_errors = 0
    
    for item in reversed(records):
        record = WeatherRecord.from_dict(item)
        errors = validator.validate_record(record)
        cumulative_errors += len(errors)
        
    print(" RAPORT KUMULATYWNY (Inicjalizacja z API - 10 odczytow) ")
    print("Przeanalizowano pomiarow historycznych: 10")
    print(f"Laczna liczba oflagowanych problemow: {cumulative_errors}")
    
    return 10, cumulative_errors

def main_loop():
    validator = DataQualityValidator(history_size=10)
    
    cumulative_records, cumulative_errors = init_history(validator)
    
    loop_count = 0

    print("Rozpoczecie monitorowania w czasie rzeczywistym (co 15 min)...")
    
    while True:
        try:
            raw_data = fetch_api("/latest", {"station_id": STATION_ID})
            save_to_jsonl(f"raw_data_{STATION_ID}.jsonl", raw_data)

            record = WeatherRecord.from_dict(raw_data)
            errors = validator.validate_record(record)
            recommendations = validator.get_cleaning_recommendations(errors)
            
            error_count = len(errors)
            total_params = validator.total_params_per_record
            quality_score = ((total_params - min(error_count, total_params)) / total_params) * 100
            
            loop_count += 1
            cumulative_records += 1
            cumulative_errors += error_count
            
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Odczyt {loop_count}/10 dla {record.timestamp}")
            print(f" -> Wynik jakosci: {quality_score:.1f}% ({error_count} bledow na {total_params} parametrow)")
            
            report_entry = {
                "timestamp": record.timestamp,
                "status": "blad" if errors else "rekord poprawny",
                "quality_score_percent": quality_score
            }
            save_to_jsonl(f"report_{STATION_ID}.jsonl", report_entry)

            if errors:
                for err in errors:
                    print(f"    * BLAD: {err}")
                for rec in recommendations:
                    print(f"    * REKOMENDACJA: {rec}")
                
                quarantine_entry = {
                    "raw_record": raw_data,
                    "errors": errors,
                    "cleaning_recommendations": recommendations,
                    "quality_score_percent": quality_score
                }
                save_to_jsonl(f"quarantine_invalid_{STATION_ID}.jsonl", quarantine_entry)
            else:
                print(" -> Status: OK (Brak bledow, rekord czysty)")

            if loop_count == 10:
                print(" RAPORT KUMULATYWNY (Ostatnie 2.5 godziny) ")
                print(f"Calkowita liczba przeanalizowanych pomiarow (od startu): {cumulative_records}")
                print(f"Laczna liczba oflagowanych problemow (od startu): {cumulative_errors}")
                
                cumulative_report_entry = {
                    "type": "cumulative_summary",
                    "timestamp": datetime.now().isoformat(),
                    "total_analyzed_from_start": cumulative_records,
                    "total_errors_from_start": cumulative_errors
                }
                save_to_jsonl(f"report_{STATION_ID}.jsonl", cumulative_report_entry)

                loop_count = 0 

            time.sleep(900)

        except Exception as e:
            print(f"Wystapil blad: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()