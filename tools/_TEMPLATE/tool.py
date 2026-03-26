"""
_TEMPLATE — Copy this folder, rename it, and build your tool.

QUICK START:
  1. Copy this folder:        cp -r _TEMPLATE my_new_tool
  2. Edit manifest.json:      set name, description, category, params
  3. Edit tool.py:            implement your run() function
  4. Restart the server       (or it auto-discovers on next /api/tools call)
  5. Your tool appears in the dashboard

THE CONTRACT:
  Your tool.py must define a run() function:

    def run(params: dict, context: dict) -> dict

  - params:   User-provided values matching your manifest.json params
  - context:  Framework-provided info (see below)
  - returns:  A dict with results (see below)

CONTEXT (what the framework gives you):
  {
    "run_id":           "a1b2c3d4",              # unique ID for this run
    "tool_id":          "my_new_tool",            # your folder name
    "output_dir":       "/path/to/outputs/...",   # write output files here
    "outputs_base_url": "/outputs/my_tool_a1b2",  # URL to access those files
    "base_dir":         "/path/to/toolbox",       # toolbox root directory
    "timestamp":        "2026-03-26T10:00:00",    # when the run started
  }

RETURN VALUE:
  {
    "message": "Human-readable summary of what happened",
    "log":     ["line 1", "line 2"],   # optional: shown in the output log
    "data":    { ... },                 # optional: shown as JSON in output
    "files": [                          # optional: links shown in output
      {"name": "result.png", "url": "/outputs/my_tool_a1b2/result.png"}
    ]
  }

CUSTOM UI (OPTIONAL):
  Add a ui.html file to your tool folder for a fully custom interface.
  It gets access to `window.Toolbox` with:
    - Toolbox.run(params)       call your tool's backend
    - Toolbox.toolId            your tool's ID
    - Toolbox.manifest          your manifest data
    - Toolbox.assetsUrl         URL base for loading your tool's static files
    - Toolbox.outputsUrl(runId) URL base for run output files

PARAM TYPES FOR MANIFEST:
  text / string   →  single-line text input
  number          →  numeric input (supports min, max, step)
  url             →  URL input
  textarea        →  multi-line text
  select          →  dropdown (requires "options" array)
  boolean         →  checkbox toggle
  file            →  file path input (text field for path)

ICON CATEGORIES:
  general, media, api, data, file, text, image, audio, dev, ai
"""


def run(params: dict, context: dict) -> dict:
    # Your tool logic goes here.
    # Access user inputs via params dict.
    # Write output files to context["output_dir"].

    example_text = params.get("example_text", "")
    example_number = params.get("example_number", 10)

    return {
        "message": f"Template tool ran with: {example_text}",
        "data": {
            "input": example_text,
            "count": example_number,
            "run_id": context["run_id"],
        }
    }
