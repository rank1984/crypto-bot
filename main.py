import scanner.universe
import scanner.regime
import scanner.ranking
import storage.sqlite_db
import utils.telegram

def debug_modules():
    print("--- Debugging Available Functions/Classes ---")
    modules = {
        "scanner.universe": scanner.universe,
        "scanner.regime": scanner.regime,
        "scanner.ranking": scanner.ranking,
        "storage.sqlite_db": storage.sqlite_db,
        "utils.telegram": utils.telegram
    }
    
    for mod_name, mod in modules.items():
        print(f"\nContents of {mod_name}:")
        # מחפש אובייקטים (פונקציות או מחלקות) ולא ספריות פנימיות
        attrs = [a for a in dir(mod) if not a.startswith("__")]
        for a in attrs:
            print(f" - {a}")
    print("\n-------------------------------------")

if __name__ == "__main__":
    debug_modules()
