# AI Database Chatbot (Odoo 18)

An intelligent, AI-powered chatbot that interacts with your Odoo database and
answers business questions in natural language. Original clean-room
implementation, LGPL-3.

## Highlights
- Multi-provider (BYOK): OpenAI, Anthropic, Google Gemini, DeepSeek, Perplexity.
- Secure: all data reads run as the requesting user, so Odoo access rights and
  record rules are enforced. Tools are read-only (search_read, read_group,
  fields_get, model listing). No write/create/unlink is ever exposed to the AI.
- Optional model whitelist for stricter control.
- Floating chat widget across the backend (OWL component).
- Conversation history persisted per user.

## How it works
The backend runs a function-calling loop. The AI is given read-only tools to
discover models, inspect fields, search records and aggregate data. It calls
those tools, the server executes them with the current user's permissions, and
the AI composes a natural-language answer.

## Install
1. Copy `mr_ai_database_chatbot` into your addons path.
2. Ensure the Python `requests` library is installed on the server.
3. Update the Apps list and install **AI Database Chatbot**.
4. Open **AI Assistant > Configuration > AI Configuration**, choose a provider,
   paste your API key, pick a model, and click **Test Connection**.
5. Click the floating chat icon (bottom-right) and start asking questions.

## Example questions
- "How many sale orders are confirmed this month?"
- "List my 5 most recent leads."
- "What is the total invoiced amount per customer this quarter?"

## Notes
- Default models per provider are pre-filled but editable (e.g. for proxies).
- The API key is only readable by the *AI Chatbot Administrator* group.
