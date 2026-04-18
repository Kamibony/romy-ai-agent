# Modular Workflow Agent Concept

## 1. Mission Composer UI in Flutter Dashboard
The `MissionControlScreen` should evolve from a simple list into a "Workflow Builder".

### Concept
- **Drag-and-Drop or Vertical List Builder:** Implement a vertical, reorderable list of blocks (similar to Notion or simple CI/CD pipelines). For a more advanced "n8n-style" interface, a canvas using a package like `flow_graph` or `graphview` could be introduced later, but a vertical list is a robust V1.
- **Block Types Menu:** A floating action button or bottom sheet to add different types of blocks:
    - **Automation Block (SOPs):** Dropdown to select existing rules from `memoryRulesProvider`.
    - **Logic/AI Block:** A text field for natural language instructions (e.g., "Multiply value by 3").
- **Block Configuration Card:** Each block in the chain should display its type, title, and a configuration area.
    - **Data Binding:** A UI mechanism (dropdown or token input) within the block to map inputs from previous blocks' outputs. E.g., `Input Data: {{Block 1 Output}}`.

### Technical Implementation Steps for UI
1. Create a `MissionComposerScreen` extending the current view.
2. Define a Riverpod `NotifierProvider<MissionBuilderNotifier, MissionGraph>` to manage the state of the active workflow graph.
3. Use `ReorderableListView` for the initial vertical chaining.
4. Each item is a custom `MissionBlockWidget` that changes its form based on block type (SOP selector vs AI Prompt input).

---

## 2. Data Structure for Chained Missions (Backend)
The backend needs a way to represent the Directed Acyclic Graph (DAG) or linear sequence of a mission.

### Proposed Structure (JSON/Pydantic)
```json
{
  "mission_id": "m_12345",
  "name": "Invoice Processing Pipeline",
  "created_at": "2023-10-27T10:00:00Z",
  "blocks": [
    {
      "block_id": "b_001",
      "type": "AUTOMATION",
      "sop_reference_id": "rule_download_invoice",
      "inputs": {
        "url": "https://portal.example.com"
      },
      "outputs": ["downloaded_file_path", "extracted_text"]
    },
    {
      "block_id": "b_002",
      "type": "AI_LOGIC",
      "instruction": "Extract the total amount and currency from the text.",
      "inputs": {
        "raw_text": "{{b_001.extracted_text}}"
      },
      "outputs": ["total_amount", "currency"]
    }
  ],
  "execution_order": ["b_001", "b_002"]
}
```

### Backend Execution Flow
1. The new endpoint `/api/v1/mission/execute` receives the `MissionGraph`.
2. A `MissionOrchestrator` service iterates through `execution_order`.
3. For `AUTOMATION` blocks: It triggers the existing `client/agent.py` loop, passing inputs and awaiting the terminal state to harvest outputs.
4. For `AI_LOGIC` blocks: It directly calls Gemini (`ai_service.py`) using the instruction and injected variable data.
5. A context object (`dict`) holds outputs keyed by `block_id` to resolve templates like `{{b_001.extracted_text}}` before executing the next block.
