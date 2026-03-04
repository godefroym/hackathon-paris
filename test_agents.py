import asyncio
import json
from workflows.activities import analyze_debate_line

async def main():
    # Exemple de phrase à tester
    test_payload = {
        "affirmation": "Le chômage en France a baissé de 15% depuis l'année dernière.",
        "personne": "Un Ministre",
        "question_posee": "Quel est votre bilan sur l'emploi ?"
    }
    
    # Contexte factice pour la dernière minute
    last_minute_context = {
        "previous_phrases": ["Bonjour à tous.", "Nous allons parler d'économie."]
    }

    print(f"Test de la phrase : '{test_payload['affirmation']}'")
    print("Analyse en cours (cela peut prendre 10-20 secondes)...")
    
    try:
        result = await analyze_debate_line(test_payload, last_minute_context)
        print("\nRESULTAT DU FACT-CHECK :")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\nErreur lors du test : {e}")

if __name__ == "__main__":
    asyncio.run(main())
