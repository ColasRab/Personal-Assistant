import os
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral

load_dotenv(Path(__file__).with_name(".env.local"))

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

connector = client.beta.connectors.create(
    request={
        "protocol": "mcp",
        "name": "personal_assistant",
        "description": "LinkedIn, email, and personal-assistant tools",
        "server": "https://personal-assistant-6xxr.onrender.com/mcp",
        "headers": {"Authorization": f"Bearer {os.environ['MCP_AUTH_TOKEN']}"}
        if os.environ.get("MCP_AUTH_TOKEN") else None,
        "visibility": "private",
    }
)

print(connector.id)

response = client.beta.conversations.start(
    model="mistral-medium-latest",
    inputs=[
        {
            "role": "user",
            "content": "Draft a LinkedIn post about MCP servers.",
        }
    ],
    tools=[
        {
            "type": "connector",
            "connector_id": "YOUR_CONNECTOR_ID",
        }
    ],
)

for output in response.outputs:
    if output.type == "message.output":
        print(output.content)
