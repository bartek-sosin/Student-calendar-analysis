# Wspólne terminy na seminarium magisterskie

Skrypt `znajdz_terminy.py` czyta plany zajęć (pliki `.ics`) kilku grup dziekańskich
i wypisuje piątki, soboty i niedziele, w które **żadna z grup nie ma zajęć**
w oknie co najmniej 3 godzin, czyli takie, w które zmieści się seminarium magisterskie.

Wymaga tylko Pythona 3.9+ (bez dodatkowych bibliotek).

## Użycie

Plany grup ZZZPN2-2311…2314 leżą w katalogu `kalendarze/`, więc wystarczy uruchomić:

```bash
python3 znajdz_terminy.py
```

Przydatne opcje:

| Opcja | Opis |
|---|---|
| `--tylko-zjazdy` | tylko dni, w które przynajmniej jedna grupa ma zajęcia (i tak jesteście na uczelni) |
| `--dni sob,nd` | dni tygodnia do analizy (domyślnie `pt,sob,nd`) |
| `--od 09:00 --do 19:00` | ramy godzinowe dnia (domyślnie 08:00–21:00, w piątki od 18:00) |
| `--piatek-od 16:00` | najwcześniejsza godzina dla piątków (domyślnie 18:00) |
| `--dlugosc 180` | długość seminarium w minutach (domyślnie 180) |
| `--bufor 15` | wymagana przerwa między zajęciami a seminarium (min) |
| `--data-od 2026-11-01 --data-do 2027-02-21` | zakres dat |
| `--uwzglednij-przeniesione` | traktuj wpisy „przen” (zajęcia przeniesione) jako zajęte |
| `--csv terminy.csv` | zapisz wyniki do CSV (np. do Excela) |

Można też podać własne pliki: `python3 znajdz_terminy.py grupa1.ics grupa2.ics ...`

## Uwagi

* Wpisy oznaczone `(przen …)` to zajęcia przeniesione na inny termin, więc domyślnie
  ich godziny są traktowane jako wolne. Jeśli wolisz ostrożniej, dodaj `--uwzglednij-przeniesione`.
* „Rezerwacja (lek …)” (Centrum Językowe) jest traktowana jako zajęcia.
