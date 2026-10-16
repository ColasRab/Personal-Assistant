# Personal Assistant MCP

FastMCP provides website editorial tools, private PDF context, LinkedIn drafts and
website import tools to your Mistral connector.
Deploy the Dockerfile as a Render Web Service. Its endpoints are `/health` and `/mcp`.

## Website integration

### Control content from the website admin

Normal editorial work can now be done in **/admin > MCP workspace**: create a draft,
review/rewrite a saved story, select private sources, upload a PDF, inspect run
history, and approve a proposal. The website runs Mistral server-side and uses the
same content services/idempotency/approval rules as MCP. It does not give the model
email tools, arbitrary network access, or approval/publication capabilities.

One-time setup:

1. Apply the website's `supabase/admin-ai.sql` after `content-management.sql` and
   `revision-requests.sql`.
2. On the **website host**, set server-only `MISTRAL_API_KEY`, optional
   `MISTRAL_MODEL` (default `mistral-medium-latest`), and `MCP_SERVER_URL` to your
   Render server's canonical HTTPS `/mcp` URL. Keep `WEBSITE_MCP_TOKEN` identical
   on the website and MCP server. Do not use `NEXT_PUBLIC_` for these secrets.
3. Redeploy both projects. The admin workflow does not need a connector ID or a
   local helper; the existing connector continues to work for external MCP clients.

`POST /admin/extract-pdf` is a fixed-purpose extractor, separate from `/mcp` auth.
PDFs up to **20 MiB** go directly from the admin browser to Render as raw bytes,
avoiding website-function payload limits and large base64 copies. The website first
validates the admin session and issues a five-minute HMAC token bound to the file's
size, SHA-256, title, page range, owner and browser origin. The shared
`WEBSITE_MCP_TOKEN` never reaches the browser. CORS preflight is public but grants no
extraction access; POST always validates the scoped token. Existing server-to-server
bearer/JSON uploads remain supported, but cannot be used as browser credentials.

The isolated parser still limits extraction to 40 pages / 60,000 characters, with
one active upload per process and bounded upload/parser times and memory. It never
invokes Mistral or saves a story. The browser returns a ten-minute signed receipt
containing extracted text to the website, which verifies its signature/owner and
stores private context using a stable upload ID. Raw PDFs are not retained. Scans
need OCR first. Redeploy **both** projects for the 20 MiB update; no SQL migration or
new secret is needed.

AI runs are one story at a time, capped at 20 per admin per hour, with durable private
history and one unfinished run per admin. Apply the website's `admin-ai-retries.sql`
after `admin-ai.sql` to enable persisted free-tier cooldowns: temporary 429s retry
the same run automatically while MCP workspace is open, with a countdown, up to
five total attempts within 20 minutes. Closing the workspace pauses retries until
it is reopened; this is not a scheduler. Retry-After is honored, known billing/quota
failures stop, and the administrator can cancel a waiting run. Older rate-limited
failures have an explicit **Retry rate-limited run** button. Only the website needs
redeployment for this retry update; the MCP server is unchanged.
**Continue saved run** reuses saved generated text without another model call.
Interrupted generations with an unknown outcome are never automatically retried; a new
run may incur another API charge. Applying a proposal or publishing remains a
separate explicit administrator action. LinkedIn imports/approvals remain in their
existing admin tab; Buffer access does not cover all native posts or mentions.

### Website content and PDF context

Apply the companion website's `supabase/content-management.sql` after its existing
schema, LinkedIn, and Buffer migrations, then apply `supabase/revision-requests.sql`.
Redeploy the website and this MCP server,
then refresh tool discovery for your existing Mistral connector.

New tools use the `website_` namespace:

- `list_posts` / `get_post`: read drafts and published stories, current version, and context references.
- `create_post`: create a website draft from user instructions or source material.
- `propose_post_update` / `redo_post`: submit rewritten copy as a proposal, never overwrite a story.
- `review_posts`: flag structural quality issues on one story or a page of stories.
- `list_revision_requests`: read the private, paginated queue marked in the website admin.
- `add_text_context` / `add_pdf_context`: save private reference text with source/page metadata.
- `list_contexts` / `read_context`: inspect evidence before writing or rewriting.
- `read_linkedin_posts`: read up to 25 sent posts available in Buffer, without importing/publishing.

The Mistral host writes the actual copy based on your prompt and evidence. Quality flags
are heuristic suggestions, not factual verification. Stable UUID `request_id` values
are required for writes; reuse the same UUID when retrying the same operation. The
website rejects a reused UUID with a different payload. For updates, read the story
first and supply its exact `updated_at`. Omitted tags/context IDs are preserved.

In the website admin's **Stories** tab, **Mark for revision** queues a saved post with
optional editorial notes; **Mark listed posts for revision** queues up to 100 posts
matching the current filters without erasing existing notes. Marking does not run AI,
save unsaved text, or rewrite/publish anything. Choose **Prepare rewrite** in the
admin and run Mistral there, or ask an external assistant to read the queue and submit
proposals. Requests are visible in
**MCP workspace** and clear only after an eligible proposal is approved/applied (or
the administrator removes the request). An older approval cannot clear newer notes.
The public post page and admin editor also include an interactive image gallery.

Review proposals in **/admin > MCP workspace**. Only a signed-in administrator can
apply them. Applying updates a published website story immediately; draft stories
remain drafts. New MCP drafts are published manually in Stories. LinkedIn requires its
own separate review/approval. There are no MCP tools for approval, publication,
deletion, changing settings, editing site code, or fetching arbitrary URLs.

The new endpoint is `POST /api/integrations/content`. It uses the same fixed-destination
website bridge and shared token as the existing LinkedIn endpoint. All content calls
also require `WEBSITE_OWNER_USER_ID` on the website to identify an existing admin user.
Private sources and revision history are stored in Supabase, not Render's filesystem.

### Optional: use Mistral from a local helper

Install local helper dependencies and configure `.env.local` beside `manage_website.py`:

```powershell
python -m pip install -r requirements-client.txt
```

Set `MISTRAL_API_KEY`, your saved `MISTRAL_CONNECTOR_ID`, and the original
`MCP_AUTH_TOKEN` for PDF uploads. `MCP_SERVER_URL` defaults to the current Render `/mcp`
endpoint. Keep all credentials private. The helper reuses the connector; it does not
create one on each invocation.

```powershell
python manage_website.py --prompt "Review my website posts. Read the weak ones and their context, then propose specific, source-supported rewrites. Do not publish."
python manage_website.py --pdf "C:\Users\colas\Documents\project.pdf" --prompt "Read the attached context and create a website draft about my project. Cite page numbers; do not invent results."
python manage_website.py --pdf "C:\Users\colas\Documents\project.pdf" --upload-only
python manage_website.py --context "paste-the-printed-context-uuid" --prompt "Use this evidence to propose an update to my existing project story."
```

A Render server cannot open a file on your computer. The helper reads your selected
local file and sends its bytes directly to your own authenticated MCP server; base64
is not inserted into the Mistral prompt. Only extracted text is saved as private
website context. When Mistral reads the context, those excerpts are sent to Mistral.
Only upload material you are authorized and comfortable sharing with these services.

PDF limits: 20 MiB, up to 40 pages per range (20 by default), and 60,000 characters.
Use `--start-page 21 --max-pages 20` to attach a subsequent range. The helper uses a
stable request UUID for the same file/range so retries do not create duplicate context.
The server reports omitted text/pages. Text extraction is not OCR or visual review;
scanned/image-only and encrypted PDFs need a suitable authorized text copy first.
The parser uses a subprocess, bounded time, a stripped environment, and Linux CPU/
memory limits. It does not retain the original PDF. These are resource limits, not a
complete security sandbox. Source text is untrusted data, not instructions.

LinkedIn context is limited to what Buffer makes available for your configured
personal profile. For native posts or mentions not available there, supply the
original LinkedIn post link and your own excerpt/summary. No scraping or cookies.

### Existing LinkedIn draft bridge

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
