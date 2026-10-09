#!/usr/bin/env python3
"""
Szuka wspólnych wolnych terminów na seminarium magisterskie dla kilku grup
dziekańskich na podstawie ich planów zajęć w formacie iCalendar (.ics).

Domyślnie:
  * analizowane są piątki i soboty,
  * seminarium trwa 3 godziny,
  * bierzemy pod uwagę okno dnia 08:00-21:00, a w piątki dopiero od 18:00,
  * zajęcia oznaczone jako "przen" (przeniesione) są pomijane, bo w tym
    terminie faktycznie się nie odbywają,
  * pomijane są polskie święta ustawowo wolne od pracy,
  * analizowany zakres dat to od pierwszych do ostatnich zajęć w planach.

Przykłady:
  python3 znajdz_terminy.py                          # pliki z katalogu kalendarze/
  python3 znajdz_terminy.py a.ics b.ics c.ics d.ics
  python3 znajdz_terminy.py --dni sob,nd --od 09:00 --do 19:00
  python3 znajdz_terminy.py --tylko-zjazdy           # tylko dni, w które ktoś ma zajęcia
  python3 znajdz_terminy.py --csv terminy.csv

Skrypt korzysta wyłącznie z biblioteki standardowej Pythona (3.9+).
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

STREFA = ZoneInfo("Europe/Warsaw")

DNI_TYGODNIA = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
NAZWY_DNI = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
ALIASY_DNI = {
    "pn": 0, "pon": 0, "poniedzialek": 0, "poniedziałek": 0,
    "wt": 1, "wto": 1, "wtorek": 1,
    "sr": 2, "śr": 2, "sro": 2, "środa": 2, "sroda": 2,
    "cz": 3, "czw": 3, "czwartek": 3,
    "pt": 4, "pia": 4, "pią": 4, "piatek": 4, "piątek": 4,
    "sb": 5, "sob": 5, "sobota": 5,
    "nd": 6, "nie": 6, "ndz": 6, "niedziela": 6,
}

# "Badania operacyjne (przen 1/1)" -> zajęcia przeniesione na inny termin
WZORZEC_PRZENIESIONE = re.compile(r"\(\s*przen\b", re.IGNORECASE)


@dataclass
class Zajecia:
    poczatek: datetime
    koniec: datetime
    nazwa: str
    grupa: str


# --------------------------------------------------------------------------- #
# Parsowanie plików ICS
# --------------------------------------------------------------------------- #

def _rozwin_linie(tekst: str) -> list[str]:
    """Scala linie zawinięte zgodnie z RFC 5545 (kontynuacja zaczyna się spacją/tabem)."""
    linie: list[str] = []
    for linia in tekst.splitlines():
        if linia[:1] in (" ", "\t") and linie:
            linie[-1] += linia[1:]
        else:
            linie.append(linia)
    return linie


def _parsuj_date(wartosc: str, parametry: dict[str, str]) -> datetime:
    """Zamienia wartość DTSTART/DTEND na datetime w strefie Europe/Warsaw (bez tzinfo)."""
    wartosc = wartosc.strip()
    if parametry.get("VALUE") == "DATE" or len(wartosc) == 8:
        # wydarzenie całodniowe
        return datetime.strptime(wartosc[:8], "%Y%m%d")
    if wartosc.endswith("Z"):
        dt = datetime.strptime(wartosc[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(STREFA).replace(tzinfo=None)
    dt = datetime.strptime(wartosc, "%Y%m%dT%H%M%S")
    tzid = parametry.get("TZID")
    if tzid and tzid != "Europe/Warsaw":
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tzid)).astimezone(STREFA).replace(tzinfo=None)
        except Exception:
            pass  # nieznana strefa - traktujemy jako czas lokalny
    return dt


def wczytaj_ics(sciezka: str, grupa: str) -> list[Zajecia]:
    with open(sciezka, encoding="utf-8-sig") as f:
        linie = _rozwin_linie(f.read())

    wynik: list[Zajecia] = []
    w_wydarzeniu = False
    biezace: dict[str, tuple[str, dict[str, str]]] = {}

    for linia in linie:
        if linia == "BEGIN:VEVENT":
            w_wydarzeniu, biezace = True, {}
            continue
        if linia == "END:VEVENT":
            w_wydarzeniu = False
            if "DTSTART" not in biezace:
                continue
            start = _parsuj_date(*biezace["DTSTART"])
            if "DTEND" in biezace:
                koniec = _parsuj_date(*biezace["DTEND"])
            else:
                koniec = start + (timedelta(days=1) if start.time() == time(0) else timedelta(0))
            nazwa = biezace.get("SUMMARY", ("(bez nazwy)", {}))[0].replace("\\,", ",")
            wynik.append(Zajecia(start, koniec, nazwa, grupa))
            continue
        if not w_wydarzeniu or ":" not in linia:
            continue
        klucz_z_parametrami, wartosc = linia.split(":", 1)
        czesci = klucz_z_parametrami.split(";")
        parametry = {}
        for p in czesci[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                parametry[k.upper()] = v
        biezace[czesci[0].upper()] = (wartosc, parametry)

    return wynik


def nazwa_grupy(sciezka: str) -> str:
    """plan_zajec_ZZZPN2-2311_do_2027-02-21.ics -> ZZZPN2-2311"""
    baza = os.path.splitext(os.path.basename(sciezka))[0]
    m = re.search(r"[A-Z]{2,}\d*-\d+", baza)
    return m.group(0) if m else baza


# --------------------------------------------------------------------------- #
# Święta
# --------------------------------------------------------------------------- #

def wielkanoc(rok: int) -> date:
    """Data Wielkanocy (algorytm Meeusa/Jonesa/Butchera)."""
    a, b, c = rok % 19, rok // 100, rok % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    miesiac = (h + l - 7 * m + 114) // 31
    dzien = (h + l - 7 * m + 114) % 31 + 1
    return date(rok, miesiac, dzien)


def swieta_w_polsce(rok: int) -> dict[date, str]:
    """Dni ustawowo wolne od pracy w Polsce."""
    w = wielkanoc(rok)
    swieta = {
        date(rok, 1, 1): "Nowy Rok",
        date(rok, 1, 6): "Trzech Króli",
        w: "Wielkanoc",
        w + timedelta(days=1): "Poniedziałek Wielkanocny",
        date(rok, 5, 1): "Święto Pracy",
        date(rok, 5, 3): "Święto Konstytucji 3 Maja",
        w + timedelta(days=49): "Zielone Świątki",
        w + timedelta(days=60): "Boże Ciało",
        date(rok, 8, 15): "Wniebowzięcie NMP",
        date(rok, 11, 1): "Wszystkich Świętych",
        date(rok, 11, 11): "Święto Niepodległości",
        date(rok, 12, 25): "Boże Narodzenie",
        date(rok, 12, 26): "Boże Narodzenie (2. dzień)",
    }
    if rok >= 2025:
        swieta[date(rok, 12, 24)] = "Wigilia"
    return swieta


# --------------------------------------------------------------------------- #
# Wyszukiwanie wolnych okien
# --------------------------------------------------------------------------- #

def scal_przedzialy(przedzialy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    scalone: list[tuple[datetime, datetime]] = []
    for p, k in sorted(przedzialy):
        if scalone and p <= scalone[-1][1]:
            scalone[-1] = (scalone[-1][0], max(scalone[-1][1], k))
        else:
            scalone.append((p, k))
    return scalone


def wolne_okna(dzien: date, zajete: list[tuple[datetime, datetime]],
               od: time, do: time, bufor: timedelta) -> list[tuple[datetime, datetime]]:
    """Zwraca wolne przedziały w oknie [od, do] danego dnia."""
    poczatek_dnia = datetime.combine(dzien, od)
    koniec_dnia = datetime.combine(dzien, do)
    zajete = scal_przedzialy([(p - bufor, k + bufor) for p, k in zajete])

    okna = []
    kursor = poczatek_dnia
    for p, k in zajete:
        if k <= poczatek_dnia or p >= koniec_dnia:
            continue
        if p > kursor:
            okna.append((kursor, min(p, koniec_dnia)))
        kursor = max(kursor, k)
    if kursor < koniec_dnia:
        okna.append((kursor, koniec_dnia))
    return okna


def parsuj_dni(tekst: str) -> set[int]:
    dni = set()
    for t in tekst.split(","):
        t = t.strip().lower()
        if not t:
            continue
        if t not in ALIASY_DNI:
            raise argparse.ArgumentTypeError(f"Nieznany dzień tygodnia: {t!r}")
        dni.add(ALIASY_DNI[t])
    return dni


def parsuj_godzine(tekst: str) -> time:
    try:
        return datetime.strptime(tekst, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Niepoprawna godzina {tekst!r} (format HH:MM)")


def parsuj_dzien(tekst: str) -> date:
    try:
        return datetime.strptime(tekst, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Niepoprawna data {tekst!r} (format RRRR-MM-DD)")


def fmt(t: datetime) -> str:
    return t.strftime("%H:%M")


def fmt_czas(td: timedelta) -> str:
    minuty = int(td.total_seconds() // 60)
    return f"{minuty // 60}h{minuty % 60:02d}" if minuty % 60 else f"{minuty // 60}h"


def main(argv: list[str] | None = None) -> int:
    katalog_skryptu = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(
        description="Znajduje weekendowe terminy, w których żadna z grup nie ma zajęć "
                    "i mieści się seminarium o zadanej długości.")
    parser.add_argument("pliki", nargs="*",
                        help="pliki .ics (domyślnie wszystkie z katalogu kalendarze/)")
    parser.add_argument("--dni", type=parsuj_dni, default=parsuj_dni("pt,sob"),
                        help="dni tygodnia do analizy (domyślnie pt,sob; np. pt,sob,nd)")
    parser.add_argument("--dlugosc", type=int, default=180,
                        help="długość seminarium w minutach (domyślnie 180)")
    parser.add_argument("--od", type=parsuj_godzine, default=time(8, 0),
                        help="najwcześniejsza godzina rozpoczęcia (domyślnie 08:00)")
    parser.add_argument("--do", type=parsuj_godzine, default=time(21, 0),
                        help="najpóźniejsza godzina zakończenia (domyślnie 21:00)")
    parser.add_argument("--piatek-od", type=parsuj_godzine, default=time(18, 0),
                        help="osobna najwcześniejsza godzina dla piątków "
                             "(domyślnie 18:00, bo w piątki ludzie pracują)")
    parser.add_argument("--bufor", type=int, default=0,
                        help="minimalna przerwa (w min) między zajęciami a seminarium (domyślnie 0)")
    parser.add_argument("--data-od", type=parsuj_dzien, default=None,
                        help="początek zakresu dat RRRR-MM-DD (domyślnie pierwsze zajęcia)")
    parser.add_argument("--data-do", type=parsuj_dzien, default=None,
                        help="koniec zakresu dat RRRR-MM-DD (domyślnie ostatnie zajęcia)")
    parser.add_argument("--uwzglednij-przeniesione", action="store_true",
                        help="traktuj zajęcia oznaczone 'przen' jako zajęte "
                             "(domyślnie są pomijane, bo zostały przeniesione)")
    parser.add_argument("--uwzglednij-swieta", action="store_true",
                        help="nie pomijaj świąt ustawowo wolnych od pracy")
    parser.add_argument("--tylko-zjazdy", action="store_true",
                        help="pokazuj tylko dni, w które przynajmniej jedna grupa ma zajęcia "
                             "(czyli i tak jest się na uczelni)")
    parser.add_argument("--csv", metavar="PLIK", help="zapisz wyniki również do pliku CSV")
    args = parser.parse_args(argv)

    pliki = args.pliki or sorted(glob.glob(os.path.join(katalog_skryptu, "kalendarze", "*.ics")))
    if not pliki:
        parser.error("Nie podano plików .ics i katalog kalendarze/ jest pusty.")

    dlugosc = timedelta(minutes=args.dlugosc)
    bufor = timedelta(minutes=args.bufor)

    # --- wczytanie planów ---
    wszystkie: list[Zajecia] = []
    grupy: list[str] = []
    pominiete = 0
    for sciezka in pliki:
        grupa = nazwa_grupy(sciezka)
        grupy.append(grupa)
        for z in wczytaj_ics(sciezka, grupa):
            if not args.uwzglednij_przeniesione and WZORZEC_PRZENIESIONE.search(z.nazwa):
                pominiete += 1
                continue
            wszystkie.append(z)

    if not wszystkie:
        print("Brak zajęć w podanych plikach.")
        return 1

    data_od = args.data_od or min(z.poczatek.date() for z in wszystkie)
    data_do = args.data_do or max(z.koniec.date() for z in wszystkie)

    zajete_wg_dnia: dict[date, list[Zajecia]] = {}
    for z in wszystkie:
        d = z.poczatek.date()
        while d <= z.koniec.date():
            zajete_wg_dnia.setdefault(d, []).append(z)
            d += timedelta(days=1)

    print(f"Grupy ({len(grupy)}): {', '.join(grupy)}")
    swieta: dict[date, str] = {}
    if not args.uwzglednij_swieta:
        for rok in range(data_od.year, data_do.year + 1):
            swieta.update(swieta_w_polsce(rok))

    print(f"Zakres dat: {data_od} – {data_do}")
    print(f"Dni: {', '.join(NAZWY_DNI[d] for d in sorted(args.dni))}")
    okno_txt = f"{args.od:%H:%M}–{args.do:%H:%M}"
    if args.piatek_od:
        okno_txt += f" (piątki od {args.piatek_od:%H:%M})"
    print(f"Okno dnia: {okno_txt}, długość seminarium: {fmt_czas(dlugosc)}"
          + (f", bufor: {args.bufor} min" if args.bufor else ""))
    if swieta:
        print("Pomijane są święta ustawowo wolne od pracy.")
    if pominiete:
        print(f"Pominięto {pominiete} wpisów oznaczonych jako przeniesione ('przen').")
    print()

    wiersze_csv = []
    liczba_dni = 0
    dzien = data_od
    while dzien <= data_do:
        if dzien.weekday() not in args.dni:
            dzien += timedelta(days=1)
            continue
        if dzien in swieta:
            dzien += timedelta(days=1)
            continue
        zajecia_dnia = zajete_wg_dnia.get(dzien, [])
        if args.tylko_zjazdy and not zajecia_dnia:
            dzien += timedelta(days=1)
            continue

        od = args.piatek_od if (args.piatek_od and dzien.weekday() == 4) else args.od
        przedzialy = [(z.poczatek, z.koniec) for z in zajecia_dnia]
        okna = [(p, k) for p, k in wolne_okna(dzien, przedzialy, od, args.do, bufor)
                if k - p >= dlugosc]

        if okna:
            liczba_dni += 1
            naglowek = f"{dzien:%Y-%m-%d} ({NAZWY_DNI[dzien.weekday()]})"
            if not zajecia_dnia:
                print(f"{naglowek} – żadna grupa nie ma zajęć, cały dzień wolny")
            else:
                grupy_z_zajeciami = sorted({z.grupa for z in zajecia_dnia})
                print(f"{naglowek} – zajęcia mają: {', '.join(grupy_z_zajeciami)}")
            for p, k in okna:
                ostatni_start = k - dlugosc
                if ostatni_start == p:
                    start_txt = f"start dokładnie o {fmt(p)}"
                else:
                    start_txt = f"start między {fmt(p)} a {fmt(ostatni_start)}"
                print(f"    wolne {fmt(p)}–{fmt(k)} ({fmt_czas(k - p)}) → {start_txt}")
                wiersze_csv.append({
                    "data": dzien.isoformat(),
                    "dzien_tygodnia": NAZWY_DNI[dzien.weekday()],
                    "wolne_od": fmt(p),
                    "wolne_do": fmt(k),
                    "dlugosc_okna": fmt_czas(k - p),
                    "najpozniejszy_start": fmt(ostatni_start),
                    "dzien_bez_zajec": "tak" if not zajecia_dnia else "nie",
                })
        dzien += timedelta(days=1)

    print()
    if liczba_dni:
        print(f"Znaleziono {liczba_dni} dni z wolnym oknem ≥ {fmt_czas(dlugosc)} wspólnym dla wszystkich grup.")
    else:
        print("Nie znaleziono żadnego wspólnego terminu – spróbuj zmienić parametry.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            pola = ["data", "dzien_tygodnia", "wolne_od", "wolne_do", "dlugosc_okna",
                    "najpozniejszy_start", "dzien_bez_zajec"]
            w = csv.DictWriter(f, fieldnames=pola)
            w.writeheader()
            w.writerows(wiersze_csv)
        print(f"Zapisano CSV: {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
