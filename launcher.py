#!/usr/bin/env python3
"""
launcher.py
===========
Point d'entrée interactif pour le pipeline Veristral.
Configure la session et lance la transcription + le fact-checking.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import List, Optional

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_input(prompt: str, options: Optional[List[str]] = None) -> str:
    while True:
        try:
            val = input(prompt).strip()
        except EOFError:
            return ""
        if not val and options:
            continue
        if options and val.upper() not in [o.upper() for o in options]:
            print(f"Option invalide. Choisissez parmi : {', '.join(options)}")
            continue
        return val

def main():
    clear_screen()
    print("==================================================")
    print("   🎙️  VERISTRAL - LIVE FACT-CHECKING PIPELINE")
    print("==================================================")
    print("Bienvenue dans l'assistant de démarrage.\n")

    # 1. Langue
    lang = get_input("Choisissez la langue de sortie [ENG/FR] : ", options=["ENG", "FR"]).upper()

    # 2. Politicien
    politician = get_input("Entrez le nom du politicien (ou RANDOM pour généraliste) : ")
    if not politician:
        politician = "RANDOM"
    
    # 3. Format & Année
    target_format = get_input("S'agit-il d'un flux LIVE ou d'une VIDEO pré-enregistrée ? [LIVE/VIDEO] : ", options=["LIVE", "VIDEO"]).upper()
    
    year = datetime.now().year
    if target_format == "VIDEO":
        year_input = get_input("Entrez l'ANNÉE de la vidéo (ex: 2022) : ")
        if year_input.isdigit():
            year = int(year_input)
        else:
            print(f"Année invalide, utilisation de l'année en cours ({year}).")

    # Sauvegarde de la configuration
    config = {
        "language": lang,
        "politician_name": politician,
        "is_live": (target_format == "LIVE"),
        "video_year": year,
        "timestamp_session": datetime.now().isoformat()
    }

    config_path = "session_config.json"
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erreur lors de la sauvegarde de la config : {e}")

    print(f"\n✅ Configuration sauvegardée dans {config_path}")
    print(f"🚀 Lancement du pipeline pour {politician} ({year})...")
    print("─" * 50)

    # Commande de lancement
    cmd = [
        "python3", "ingestion/realtime_transcript.py",
        "--personne", politician
    ]
    
    pipeline_cmd = ["python3", "ingestion/fact_check_pipeline.py"]
    
    try:
        p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        # Type checking fix: ensure p1.stdout is not None for p2
        if p1.stdout is None:
            raise RuntimeError("Échec de l'ouverture du pipe de sortie pour la transcription.")
            
        p2 = subprocess.Popen(pipeline_cmd, stdin=p1.stdout)
        
        # Autoriser p1 à recevoir un SIGPIPE si p2 s'arrête
        p1.stdout.close()
        
        # Attendre la fin de p2
        p2.wait()
    except KeyboardInterrupt:
        print("\n👋 Arrêt demandé par l'utilisateur.")
    except Exception as e:
        print(f"\n💥 Erreur lors de l'exécution : {e}")
    finally:
        # cleanup if they exist
        pass

if __name__ == "__main__":
    main()
