import asyncio
import json
from pathlib import Path

from workflows.activities_emma import analyze_debate_line


CASES_PATH = Path("test_cases_activities_emma.json")


async def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    for case in cases:
        result = await analyze_debate_line(
            case["current_json"],
            case["last_minute_json"],
        )
        print(f"\n=== {case['id']} ===")
        print(f"attendu: {case['type_attendu']}")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
