# Personal Assistant MCP

FastMCP provides LinkedIn draft and website import tools to your Mistral connector.
Deploy the Dockerfile as a Render Web Service. Its endpoints are `/health` and `/mcp`.

## Website integration

The companion Next.js website has a **LinkedIn review** tab under `/admin`. Apply its
`supabase/linkedin-sync.sql` and `supabase/buffer-publishing.sql` migrations and configure
its server environment first. The website publishes through Buffer to your personal
LinkedIn profile; no company Page or LinkedIn developer app of your own is needed.
Connect your personal profile inside Buffer, then put `BUFFER_API_KEY` and
`BUFFER_LINKEDIN_CHANNEL_ID` on the website host, not this MCP server. See the website
README for setup. Existing Render bridge settings stay the same.

Set these Render environment variables using `.env.example` as a reference:

- `WEBSITE_URL`: your website's canonical HTTPS origin, with no path.
- `WEBSITE_MCP_TOKEN`: the same random secret configured on the website.
- `MCP_AUTH_TOKEN_SHA256`: SHA-256 hex digest of a separate random MCP bearer token.

Generate the bearer token and its hash once on your own computer:

```powershell
python -c "import secrets,hashlib; token=secrets.token_urlsafe(32); print('MCP bearer token:',token); print('MCP_AUTH_TOKEN_SHA256:',hashlib.sha256(token.encode()).hexdigest())"
```

Store the hash on Render. Configure your Mistral connector to send
`Authorization: Bearer <original MCP bearer token>`. Keep the original token private.
For a new connector created with `mistral_client.py`, set `MCP_AUTH_TOKEN` in your local
`.env.local`; the client includes that header during connector registration. Update an
already registered connector's credentials instead of creating duplicate connectors.
Generate a different random secret for `WEBSITE_MCP_TOKEN`; never reuse your Buffer
API key or Mistral API key for this purpose.

With website integration configured, startup fails if MCP authentication is missing.
The health endpoint stays available for Render's health checks. Without any website
configuration, only the standalone draft tool works; website tools return a setup error.

Available LinkedIn tools are namespaced with `linkedin_`:

- `draft_linkedin_post`: returns supplied copy as an unposted local draft.
- `list_website_linkedin_drafts`: reads pending drafts from the website.
- `prepare_website_linkedin_draft`: queues one published website story by its UUID.
- `import_linkedin_item_to_website`: imports supplied text/mention summaries as drafts.

There is deliberately no MCP publication tool. A signed-in website administrator must
review and approve the text and website link before the website calls Buffer. This server does
not scrape LinkedIn, discover personal mentions, or keep a local queue in its ephemeral
container filesystem. Durable queue data lives in the website's Supabase database.

For MCP imports, set `WEBSITE_OWNER_USER_ID` on the website to an existing Supabase admin
user's UUID. The website integration token cannot publish imported stories.

## Local use

```powershell
python -m pip install -r requirements.txt
python server.py
```

Configure the environment variables in the process running the server. Render injects
them automatically; the server does not automatically load `.env.local`.

```powershell
python -m unittest discover -s tests -v
docker build -t personal-assistant-mcp:local .
```

The Python tests verify bearer authentication, fail-closed configuration, fixed website
destinations, and rejection of redirects that could forward integration credentials.
They do not contact Buffer or LinkedIn or publish content.
