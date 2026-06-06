import json
import csv
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

MEMORIE_FILE = "memorie_optimized.json"
CSV_FILE = "trades_log.csv"

# ═══════════════════════════════════════
# EXPORT CSV
# ═══════════════════════════════════════
def export_csv(memorie):
    tranzactii = memorie["tranzactii"]
    inchideri = [t for t in tranzactii if t["tip"].startswith("close") and t.get("profit") is not None]

    if not inchideri:
        print("❌ Nicio tranzacție închisă de exportat.")
        return

    # Asociază fiecare închidere cu intrarea corespunzătoare
    rows = []
    deschideri = {t["simbol"]: t for t in tranzactii if t["tip"].startswith("open")}

    for t in inchideri:
        simbol = t["simbol"]
        directie = t["tip"].replace("close_", "")
        deschidere = None

        # Caută ultima deschidere pentru acest simbol
        for d in reversed(tranzactii):
            if d["simbol"] == simbol and d["tip"] == f"open_{directie}":
                if d["data"] < t["data"]:
                    deschidere = d
                    break

        pret_intrare = deschidere["pret"] if deschidere else 0
        cantitate = t["cantitate"]
        pret_iesire = t["pret"]
        profit = t["profit"]
        profit_pct = (profit / (pret_intrare * cantitate) * 100) if pret_intrare > 0 else 0

        rows.append({
            "data_intrare": deschidere["data"] if deschidere else "N/A",
            "data_iesire": t["data"],
            "simbol": simbol,
            "directie": directie.upper(),
            "cantitate": cantitate,
            "pret_intrare": round(pret_intrare, 4),
            "pret_iesire": round(pret_iesire, 4),
            "profit_usd": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "motiv_exit": t.get("motiv", ""),
            "ora": t.get("ora", ""),
            "rezultat": "WIN" if profit > 0 else "LOSS"
        })

    # Scrie CSV
    campuri = [
        "data_intrare", "data_iesire", "simbol", "directie",
        "cantitate", "pret_intrare", "pret_iesire",
        "profit_usd", "profit_pct", "motiv_exit", "ora", "rezultat"
    ]

    fisier_exista = os.path.exists(CSV_FILE)

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campuri)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ {len(rows)} tranzacții exportate în {CSV_FILE}")
    return rows

# ═══════════════════════════════════════
# SUMAR CSV
# ═══════════════════════════════════════
def afiseaza_sumar(rows):
    if not rows:
        return

    wins = [r for r in rows if r["rezultat"] == "WIN"]
    losses = [r for r in rows if r["rezultat"] == "LOSS"]
    profit_total = sum(r["profit_usd"] for r in rows)
    win_rate = len(wins) / len(rows) if rows else 0

    print(f"\n📊 SUMAR CSV:")
    print(f"  Total trades:  {len(rows)}")
    print(f"  Wins:          {len(wins)}")
    print(f"  Losses:        {len(losses)}")
    print(f"  Win rate:      {win_rate:.1%}")
    print(f"  Profit total:  ${profit_total:.2f}")

    # Top 3 cele mai bune trades
    top_wins = sorted(wins, key=lambda x: x["profit_usd"], reverse=True)[:3]
    if top_wins:
        print(f"\n🏆 TOP 3 TRADES:")
        for r in top_wins:
            print(f"  🟢 {r['simbol']} {r['directie']} | ${r['profit_usd']} ({r['profit_pct']}%) | {r['motiv_exit']}")

    # Top 3 cele mai proaste
    top_losses = sorted(losses, key=lambda x: x["profit_usd"])[:3]
    if top_losses:
        print(f"\n💀 TOP 3 PIERDERI:")
        for r in top_losses:
            print(f"  🔴 {r['simbol']} {r['directie']} | ${r['profit_usd']} ({r['profit_pct']}%) | {r['motiv_exit']}")

# ═══════════════════════════════════════
# APPEND — adaugă doar trades noi
# ═══════════════════════════════════════
def append_trades_noi(memorie):
    """
    Adaugă doar tranzacțiile noi față de ultima exportare
    Util dacă rulezi zilnic
    """
    trades_existente = set()

    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades_existente.add(row["data_iesire"])

    tranzactii = memorie["tranzactii"]
    inchideri_noi = [
        t for t in tranzactii
        if t["tip"].startswith("close")
        and t.get("profit") is not None
        and t["data"] not in trades_existente
    ]

    if not inchideri_noi:
        print("✅ Nicio tranzacție nouă de adăugat.")
        return

    campuri = [
        "data_intrare", "data_iesire", "simbol", "directie",
        "cantitate", "pret_intrare", "pret_iesire",
        "profit_usd", "profit_pct", "motiv_exit", "ora", "rezultat"
    ]

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campuri)
        if not os.path.exists(CSV_FILE):
            writer.writeheader()

        for t in inchideri_noi:
            simbol = t["simbol"]
            directie = t["tip"].replace("close_", "")
            pret_intrare = 0

            for d in reversed(tranzactii):
                if d["simbol"] == simbol and d["tip"] == f"open_{directie}":
                    if d["data"] < t["data"]:
                        pret_intrare = d["pret"]
                        break

            profit = t["profit"]
            profit_pct = (profit / (pret_intrare * t["cantitate"]) * 100) if pret_intrare > 0 else 0

            writer.writerow({
                "data_intrare": "N/A",
                "data_iesire": t["data"],
                "simbol": simbol,
                "directie": directie.upper(),
                "cantitate": t["cantitate"],
                "pret_intrare": round(pret_intrare, 4),
                "pret_iesire": round(t["pret"], 4),
                "profit_usd": round(profit, 2),
                "profit_pct": round(profit_pct, 2),
                "motiv_exit": t.get("motiv", ""),
                "ora": t.get("ora", ""),
                "rezultat": "WIN" if profit > 0 else "LOSS"
            })

    print(f"✅ {len(inchideri_noi)} tranzacții noi adăugate în {CSV_FILE}")

# ═══════════════════════════════════════
# START
# ═══════════════════════════════════════
def main():
    if not os.path.exists(MEMORIE_FILE):
        print("❌ Nu există fișier de memorie. Rulează agentul mai întâi.")
        return

    with open(MEMORIE_FILE, "r") as f:
        memorie = json.load(f)

    print("📊 Export trades în CSV...\n")

    # Export complet
    rows = export_csv(memorie)

    # Afișează sumar
    if rows:
        afiseaza_sumar(rows)

    print(f"\n💾 Fișier salvat: {CSV_FILE}")
    print(f"📂 Îl poți deschide în Excel pentru analiză!")

main()
