# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Database Agent: get data from database (BigQuery) using NL2SQL."""

import os
from google.genai import types

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import ToolContext
from google.adk.tools.toolbox_toolset import ToolboxToolset

from .prompts import return_instructions_dq
from . import tools
from dq_framework.sub_agents.bigquery.tools import (
    get_database_settings as get_bq_database_settings,
)
from .chase_sql import chase_db_tools
from dq_framework.sub_agents.bigquery.agent import bigquery_agent as bq_db_agent

NL2SQL_METHOD = os.getenv("NL2SQL_METHOD", "BASELINE")

def setup_before_agent_call(callback_context: CallbackContext):
    """Setup the agent."""

    # setting up database settings in session.state
    if "database_settings" not in callback_context.state:
        db_settings = dict()
        db_settings["use_database"] = "BigQuery"
        callback_context.state["all_db_settings"] = db_settings

    # setting up schema in instruction
    if callback_context.state["all_db_settings"]["use_database"] == "BigQuery":
        callback_context.state["database_settings"] = get_bq_database_settings()
        schema = callback_context.state["database_settings"]["bq_ddl_schema"]

        callback_context._invocation_context.agent.instruction = (
            return_instructions_dq()
            + f"""
   </BQML Reference for this query>
    
    <The BigQuery schema of the relevant data with a few sample rows>
    {schema}
    </The BigQuery schema of the relevant data with a few sample rows>
    """
        )
async def call_db_agent(
    question: str,
    tool_context: ToolContext,
):
    """Tool to call database (nl2sql) agent."""
    print(
        "\n call_db_agent.use_database:"
        f' {tool_context.state["all_db_settings"]["use_database"]}'
    )
    database_agent = (
        bq_db_agent
        if tool_context.state["all_db_settings"]["use_database"] == "BigQuery"
        # else pg_db_agent
        else None
    )
    agent_tool = AgentTool(agent=database_agent)
    db_agent_output = await agent_tool.run_async(
        args={"request": question}, tool_context=tool_context
    )
    tool_context.state["db_agent_output"] = db_agent_output
    return db_agent_output

root_agent = Agent(
    model=os.getenv("BIGQUERY_AGENT_MODEL"),
    name="dataquality_agent",
    instruction=return_instructions_dq(),
    tools=[
        (
            chase_db_tools.initial_bq_nl2sql
            if NL2SQL_METHOD == "CHASE"
            else tools.initial_bq_nl2sql
        ),
        tools.run_bigquery_validation,
        ToolboxToolset(
            server_url="http://127.0.0.1:5000", toolset_name="dq_toolset"

        ),
        call_db_agent
    ],
    before_agent_callback=setup_before_agent_call,
    generate_content_config=types.GenerateContentConfig(temperature=0.01),
)
