"""
Hello World — the simplest possible Toolbox tool.

Demonstrates the basic contract:
  - run(params, context) -> dict with at least a "message" key
"""

def run(params: dict, context: dict) -> dict:
    name = params.get("name", "World")
    shout = params.get("shout", False)

    greeting = f"Hello, {name}! Welcome to Toolbox."

    if shout:
        greeting = greeting.upper()

    return {
        "message": greeting,
        "data": {
            "name": name,
            "shout": shout,
            "run_id": context["run_id"],
        }
    }
