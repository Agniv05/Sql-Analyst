"""
agent.py — Agentic loop for the SQL Data Analyst.

Orchestrates a multi-turn Claude tool-use loop:
  1. Send user message + conversation history to Claude
  2. If Claude returns tool_use blocks, dispatch to the right tool
  3. Feed tool results back as tool_result messages
  4. Repeat until Claude returns a final text answer

Tools registered here:
  - get_schema       → tools/schema.py
  - run_sql          → tools/executor.py
  - render_chart     → tools/charter.py
"""

import json
import anthropic
from typing import Any

from tools.schema import get_schema
from tools.executor import run_sql
from tools.charter import render_chart

# ---------------------------------------------------------------------------
# Tool definitions (sent to Claude on every request)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "get_schema",
        "description": (
            "Inspect the database and return all table names with their column "
            "names and types. Always call this first if you are unsure which "
            "tables or columns exist."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Execute a read-only SQL SELECT query against the sales database "
            "and return the results as a list of row dicts. "
            "Never use INSERT, UPDATE, DELETE, or DROP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A valid SQLite SELECT statement.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "render_chart",
        "description": (
            "Generate a chart from query result data and return it as a "
            "base64-encoded PNG string. Use this after run_sql when the user "
            "asks for a visualisation, chart, or graph."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter"],
                    "description": "Type of chart to render.",
                },
                "title": {
                    "type": "string",
                    "description": "Chart title displayed above the plot.",
                },
                "x_label": {
                    "type": "string",
                    "description": "Label for the x-axis (or pie slice labels).",
                },
                "y_label": {
                    "type": "string",
                    "description": "Label for the y-axis (omit for pie charts).",
                },
                "data": {
                    "type": "object",
                    "description": (
                        "Mapping of series name → list of values. "
                        "For a single series use {'values': [...]}. "
                        "The x_values key holds the x-axis labels / categories."
                    ),
                    "properties": {
                        "x_values": {
                            "type": "array",
                            "items": {},
                            "description": "X-axis labels or categories.",
                        }
                    },
                    "required": ["x_values"],
                },
            },
            "required": ["chart_type", "title", "x_label", "data"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert SQL data analyst assistant.
You have access to a sales database containing tables for orders, products,
customers, and regions.

Your workflow for every user question:
1. If you don't yet know the schema, call get_schema first.
2. Construct a precise SQL SELECT query and call run_sql.
3. Analyse the results and formulate a clear, concise answer.
4. If the user asked for a chart or visualisation — or if one would add
   meaningful insight — call render_chart with the query results.
5. Return your final answer in plain language, including the SQL you used
   (in a markdown code block) and a summary of the findings.

Rules:
- Only issue SELECT queries. Never modify the database.
- If a query returns no rows, say so clearly and suggest why.
- Keep answers focused and avoid unnecessary verbosity.
- When referencing numbers, include units (e.g. "$", "units", "%").
"""

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _dispatch_tool(name: str, tool_input: dict) -> Any:
    """Call the matching tool function and return a JSON-serialisable result."""
    if name == "get_schema":
        return get_schema()
    elif name == "run_sql":
        return run_sql(tool_input["query"])
    elif name == "render_chart":
        return render_chart(
            chart_type=tool_input["chart_type"],
            title=tool_input["title"],
            x_label=tool_input["x_label"],
            y_label=tool_input.get("y_label", ""),
            data=tool_input["data"],
        )
    else:
        return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Agent response dataclass
# ---------------------------------------------------------------------------

class AgentResponse:
    """Structured response returned to the FastAPI layer."""

    def __init__(
        self,
        text: str,
        chart_b64: str | None = None,
        sql_used: str | None = None,
        tool_calls: list[dict] | None = None,
    ):
        self.text = text
        self.chart_b64 = chart_b64          # base64 PNG, ready for <img src="data:...">
        self.sql_used = sql_used            # last SQL query executed (for display)
        self.tool_calls = tool_calls or []  # audit trail of every tool call

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "chart_b64": self.chart_b64,
            "sql_used": self.sql_used,
            "tool_calls": self.tool_calls,
        }


# ---------------------------------------------------------------------------
# Core agentic loop
# ---------------------------------------------------------------------------

def run_agent(
    user_message: str,
    conversation_history: list[dict],
    max_iterations: int = 10,
) -> AgentResponse:
    """
    Run the agentic loop for a single user turn.

    Args:
        user_message:          The latest message from the user.
        conversation_history:  Full prior message history (mutated in-place).
        max_iterations:        Safety cap — stop after this many Claude calls.

    Returns:
        AgentResponse with the final text answer, optional chart, and audit log.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    # Append the new user message to history
    conversation_history.append({"role": "user", "content": user_message})

    # State we collect across iterations
    chart_b64: str | None = None
    sql_used: str | None = None
    tool_call_log: list[dict] = []

    for iteration in range(max_iterations):

        # ----------------------------------------------------------------
        # Call Claude
        # ----------------------------------------------------------------
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=conversation_history,
        )

        # ----------------------------------------------------------------
        # Handle stop_reason
        # ----------------------------------------------------------------
        if response.stop_reason == "end_turn":
            # Claude is done — extract the final text answer
            final_text = _extract_text(response.content)

            # Append assistant message to history for future turns
            conversation_history.append(
                {"role": "assistant", "content": response.content}
            )

            return AgentResponse(
                text=final_text,
                chart_b64=chart_b64,
                sql_used=sql_used,
                tool_calls=tool_call_log,
            )

        elif response.stop_reason == "tool_use":
            # Claude wants to call one or more tools
            # First, record the assistant message (with tool_use blocks)
            conversation_history.append(
                {"role": "assistant", "content": response.content}
            )

            # Build tool_result blocks for every tool_use in this response
            tool_result_blocks: list[dict] = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input

                # Log the call
                tool_call_log.append({"tool": tool_name, "input": tool_input})

                # Dispatch
                try:
                    result = _dispatch_tool(tool_name, tool_input)
                except Exception as exc:
                    result = {"error": str(exc)}

                # Capture side-effects for the final response
                if tool_name == "run_sql":
                    sql_used = tool_input.get("query")
                elif tool_name == "render_chart":
                    if isinstance(result, dict) and "chart_b64" in result:
                        chart_b64 = result["chart_b64"]

                # Serialise result to string for the tool_result message
                result_str = (
                    result if isinstance(result, str) else json.dumps(result, default=str)
                )

                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    }
                )

            # Feed all tool results back in a single user message
            conversation_history.append(
                {"role": "user", "content": tool_result_blocks}
            )

        else:
            # Unexpected stop reason — surface what we have
            break

    # ----------------------------------------------------------------
    # Fell through the iteration cap — return whatever text we have
    # ----------------------------------------------------------------
    last_text = _extract_text(response.content) if response else "Agent loop exceeded iteration limit."
    return AgentResponse(
        text=last_text or "Reached maximum iterations without a final answer.",
        chart_b64=chart_b64,
        sql_used=sql_used,
        tool_calls=tool_call_log,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(content_blocks) -> str:
    """Concatenate all text blocks from a Claude response content list."""
    parts = []
    for block in content_blocks:
        if hasattr(block, "type") and block.type == "text":
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts).strip()
