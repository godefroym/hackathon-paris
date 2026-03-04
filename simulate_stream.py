import asyncio
from temporalio.client import Client
import sys
import os
# Add both root and workflows dir to path to satisfy all import styles
root_dir = os.getcwd()
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, 'workflows'))

from workflows.debate_workflow import DebateJsonNoopWorkflow
import uuid
from datetime import datetime

async def main():
    # Connect to Temporal
    client = await Client.connect("localhost:7233")

    # Sample data
    current_json = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "affirmation": "La France est le premier pays d'Europe en termes de croissance cette année.",
        "personne": "Un invité politique",
        "question_posee": "Que pensez-vous de la situation économique ?"
    }

    # Context (simulated last 60 seconds)
    last_minute_json = {
        "phrases": [
            "Bonjour.",
            "Nous accueillons notre invité."
        ]
    }

    print(f"🚀 Injection de la phrase dans l'architecture complète...")
    
    # Start the workflow
    handle = await client.start_workflow(
        DebateJsonNoopWorkflow.run,
        args=[
            current_json,
            last_minute_json,
            5.0, # Default video delay
            30,  # Default analysis timeout
            None # next_json
        ],
        id=f"debate-test-{uuid.uuid4().hex[:6]}",
        task_queue="debate-json-task-queue",
    )

    print(f"✅ Workflow démarré ! ID: {handle.id}")
    print(f"🔗 Vous pouvez suivre l'avancement sur : http://localhost:8080")
    print(f"📺 Le résultat apparaîtra sur l'interface OBS (http://localhost:8000) dans quelques secondes.")

    # Wait for result
    result = await handle.result()
    print("\n🏁 Analyse terminée !")

if __name__ == "__main__":
    asyncio.run(main())
