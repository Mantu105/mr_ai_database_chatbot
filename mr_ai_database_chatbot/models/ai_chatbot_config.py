# -*- coding: utf-8 -*-
import json
import logging
import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None
    _logger.warning("The `requests` python library is required by AI Database Chatbot.")


# Default API endpoints per provider. DeepSeek and Perplexity expose an
# OpenAI-compatible Chat Completions API, so they reuse the OpenAI code path.
PROVIDER_DEFAULTS = {
    'openai': {
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-4o-mini',
    },
    'anthropic': {
        'base_url': 'https://api.anthropic.com/v1',
        'model': 'claude-sonnet-4-5',
    },
    'gemini': {
        'base_url': 'https://generativelanguage.googleapis.com/v1beta',
        'model': 'gemini-1.5-flash',
    },
    'deepseek': {
        'base_url': 'https://api.deepseek.com/v1',
        'model': 'deepseek-chat',
    },
    'perplexity': {
        'base_url': 'https://api.perplexity.ai',
        'model': 'sonar',
    },
}

# Maximum number of tool-call round trips per user question. Prevents runaway loops.
MAX_TOOL_ITERATIONS = 6

DEFAULT_SYSTEM_PROMPT = """You are an AI assistant embedded inside an Odoo ERP system.
Your job is to answer the user's business questions by reading data from the Odoo
database using the tools provided. Follow these rules:

1. Always use the tools to look up real data. Never invent record values.
2. Use `list_models` to discover which models you are allowed to read, and
   `describe_model` to learn a model's fields before querying it.
3. Use `search_records` for raw records and `read_group` for aggregated figures
   (counts, sums, averages grouped by a field).
4. Odoo domains are lists of triplets, e.g. [["state", "=", "sale"]]. Combine
   conditions with explicit "&" / "|" operators when needed.
5. If a query fails because of access rights, tell the user they don't have
   permission rather than guessing.
6. FORMATTING RULES (strictly follow these):
   - When returning a list of records (orders, invoices, products, customers, etc.),
     ALWAYS format them as a markdown table with | column | headers | and rows.
   - Choose clear, short column headers (e.g. #, Name, Date, Customer, Status, Total).
   - Never use bullet points or numbered lists for record data — always use a table.
   - For single-value answers (counts, totals, averages), answer in one short sentence.
   - For grouped/aggregated results, use a table with group and value columns.
   - Keep currency values formatted as numbers (e.g. 1,234.50).
Today's date and the user's permissions are already applied by the system."""


class AiChatbotConfig(models.Model):
    _name = 'ai.chatbot.config'
    _description = 'AI Chatbot Configuration'
    _order = 'is_default desc, sequence, id'

    name = fields.Char(required=True, default='Default AI Configuration')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string='Default',
        help="Configuration used by the chatbot widget. Only one may be default.",
    )
    provider = fields.Selection(
        selection=[
            ('openai', 'OpenAI (ChatGPT)'),
            ('anthropic', 'Anthropic (Claude)'),
            ('gemini', 'Google Gemini'),
            ('deepseek', 'DeepSeek'),
            ('perplexity', 'Perplexity'),
        ],
        required=True,
        default='openai',
    )
    api_key = fields.Char(string='API Key')
    base_url = fields.Char(
        string='Base URL',
        help="API endpoint. Defaults are filled automatically per provider; "
             "override only for proxies or self-hosted gateways.",
    )
    model = fields.Char(
        string='Model',
        required=True,
        help="Model identifier, e.g. gpt-4o-mini, claude-sonnet-4-5, gemini-1.5-flash.",
    )
    temperature = fields.Float(default=0.2)
    max_tokens = fields.Integer(string='Max Tokens', default=1024)
    system_prompt = fields.Text(default=DEFAULT_SYSTEM_PROMPT)

    restrict_models = fields.Boolean(
        string='Restrict Models',
        help="If enabled, the assistant may only read the models listed below. "
             "Standard Odoo access rights still apply on top of this whitelist.",
    )
    allowed_model_ids = fields.Many2many(
        'ir.model',
        'ai_chatbot_config_allowed_model_rel',
        'config_id', 'model_id',
        string='Allowed Models',
    )

    # --------------------------------------------------------------------- #
    # Onchange / constraints
    # --------------------------------------------------------------------- #
    @api.onchange('provider')
    def _onchange_provider(self):
        defaults = PROVIDER_DEFAULTS.get(self.provider, {})
        self.base_url = defaults.get('base_url')
        if not self.model:
            self.model = defaults.get('model')

    @api.constrains('is_default')
    def _check_single_default(self):
        # Skip during module installation (no id yet means called from data load)
        for config in self.filtered(lambda c: c.is_default and c.id):
            others = self.search([
                ('is_default', '=', True),
                ('id', '!=', config.id),
            ])
            if others:
                raise UserError(_("Only one configuration can be the default. "
                                  "Please unset the others first."))

    @api.model
    def get_active_config(self):
        """Return the configuration the widget should use for the current user."""
        config = self.search([('is_default', '=', True)], limit=1)
        if not config:
            config = self.search([], limit=1)
        return config

    def _effective_base_url(self):
        self.ensure_one()
        return (self.base_url or PROVIDER_DEFAULTS.get(self.provider, {}).get('base_url') or '').rstrip('/')

    # --------------------------------------------------------------------- #
    # Connection test
    # --------------------------------------------------------------------- #
    def action_test_connection(self):
        self.ensure_one()
        try:
            answer = self._run_completion(
                messages=[{'role': 'user', 'content': "Reply with the single word: OK"}],
                tools=None,
                user_env=self.env,
            )
            text = (answer.get('content') or '').strip()
            message = _("Connection successful. Model replied: %s") % (text or '(empty)')
            level = 'success'
        except Exception as exc:  # noqa: BLE001
            message = _("Connection failed: %s") % exc
            level = 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("AI Chatbot"),
                'message': message,
                'type': level,
                'sticky': False,
            },
        }

    # --------------------------------------------------------------------- #
    # Public entry point used by the controller
    # --------------------------------------------------------------------- #
    def process_query(self, conversation, user_env=None):
        """Run the full tool-calling loop for a conversation and return the
        assistant's final natural-language answer (a string).

        `conversation` is an ai.chatbot.conversation record. `user_env` is the
        environment used for **all data reads** so that Odoo record rules and
        access rights are enforced for the requesting user. The config record
        itself (which holds the API key) may be loaded with elevated rights;
        only the credentials are taken from it, never the data.
        """
        self.ensure_one()
        if requests is None:
            raise UserError(_("The python `requests` library is not installed on the server."))

        user_env = user_env or self.env  # requesting user's env (no sudo for data)
        messages = self._build_message_history(conversation)
        tools = self._tool_specifications()

        final_text = ''
        for _iteration in range(MAX_TOOL_ITERATIONS):
            result = self._run_completion(messages, tools, user_env)
            tool_calls = result.get('tool_calls') or []

            if not tool_calls:
                final_text = result.get('content') or ''
                break

            # Record the assistant turn that requested tools, then execute them.
            # Tool results are batched: OpenAI expects one 'tool' message per
            # call, while Anthropic/Gemini require a single grouped user turn.
            messages.append(self._assistant_tool_message(result))
            tool_outputs = []
            for call in tool_calls:
                output = self._execute_tool(call, user_env)
                tool_outputs.append((call, output))
            messages.extend(self._tool_result_messages(tool_outputs))
        else:
            final_text = result.get('content') or _(
                "I reached the maximum number of lookups without a final answer. "
                "Please try a more specific question."
            )

        return final_text

    # --------------------------------------------------------------------- #
    # Message history assembly
    # --------------------------------------------------------------------- #
    def _build_message_history(self, conversation):
        """Convert stored conversation messages into a normalized list."""
        messages = []
        history = conversation.message_ids.filtered(
            lambda m: m.role in ('user', 'assistant') and m.content
        ).sorted('id')
        for msg in history:
            messages.append({'role': msg.role, 'content': msg.content})
        return messages

    # --------------------------------------------------------------------- #
    # Tool specifications (provider-agnostic schema)
    # --------------------------------------------------------------------- #
    def _tool_specifications(self):
        return [
            {
                'name': 'list_models',
                'description': "List the Odoo models the user is allowed to read, "
                               "with their technical name and label.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'search': {
                            'type': 'string',
                            'description': "Optional case-insensitive filter on model name or label.",
                        },
                    },
                },
            },
            {
                'name': 'describe_model',
                'description': "Return the readable fields of a model: technical name, "
                               "label, type and relation target.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string', 'description': "Technical model name, e.g. sale.order."},
                    },
                    'required': ['model'],
                },
            },
            {
                'name': 'search_records',
                'description': "Search and read records of a model. Returns a list of records.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string'},
                        'domain': {
                            'type': 'array',
                            'description': "Odoo search domain, list of triplets. Default [].",
                            'items': {},
                        },
                        'fields': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': "Fields to return. Keep it minimal.",
                        },
                        'limit': {'type': 'integer', 'description': "Max records (default 20, hard cap 200)."},
                        'order': {'type': 'string', 'description': "Sort clause, e.g. 'date_order desc'."},
                    },
                    'required': ['model'],
                },
            },
            {
                'name': 'read_group',
                'description': "Aggregate records grouped by one or more fields. Use for counts, "
                               "sums and averages.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'model': {'type': 'string'},
                        'domain': {'type': 'array', 'items': {}},
                        'fields': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': "Aggregated fields, e.g. ['amount_total:sum'].",
                        },
                        'groupby': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': "Fields to group by, e.g. ['state'].",
                        },
                    },
                    'required': ['model', 'groupby'],
                },
            },
        ]

    # --------------------------------------------------------------------- #
    # Tool execution (SECURE: runs as requesting user, read-only)
    # --------------------------------------------------------------------- #
    def _is_model_allowed(self, model_name):
        if not self.restrict_models:
            return True
        return model_name in self.allowed_model_ids.mapped('model')

    def _execute_tool(self, call, user_env):
        """Execute a single tool call and return a JSON-serializable dict.

        Only read operations are exposed. The call runs with `user_env` (the
        requesting user) so Odoo access rights and record rules are enforced
        automatically. No `sudo()` is used anywhere here.
        """
        name = call.get('name')
        args = call.get('arguments') or {}
        try:
            if name == 'list_models':
                return self._tool_list_models(args, user_env)
            if name == 'describe_model':
                return self._tool_describe_model(args, user_env)
            if name == 'search_records':
                return self._tool_search_records(args, user_env)
            if name == 'read_group':
                return self._tool_read_group(args, user_env)
            return {'error': "Unknown tool: %s" % name}
        except AccessError as exc:
            return {'error': "Access denied: %s" % exc}
        except UserError as exc:
            return {'error': str(exc)}
        except Exception as exc:  # noqa: BLE001
            _logger.exception("AI chatbot tool '%s' failed", name)
            return {'error': "Tool execution error: %s" % exc}

    def _tool_list_models(self, args, user_env):
        term = (args.get('search') or '').lower()
        domain = [('transient', '=', False)]
        models_rs = user_env['ir.model'].search(domain)
        out = []
        for m in models_rs:
            if self.restrict_models and m.model not in self.allowed_model_ids.mapped('model'):
                continue
            if term and term not in m.model.lower() and term not in (m.name or '').lower():
                continue
            # Only advertise models the user can actually read.
            if not user_env[m.model].has_access('read'):
                continue
            out.append({'model': m.model, 'label': m.name})
            if len(out) >= 100:
                break
        return {'models': out}

    def _tool_describe_model(self, args, user_env):
        model_name = args.get('model')
        if not self._is_model_allowed(model_name):
            return {'error': "Model '%s' is not in the allowed list." % model_name}
        if model_name not in user_env:
            return {'error': "Unknown model: %s" % model_name}
        Model = user_env[model_name]
        Model.check_access('read')
        fields_info = Model.fields_get(
            attributes=['string', 'type', 'relation', 'help', 'selection'],
        )
        out = []
        for fname, info in fields_info.items():
            entry = {
                'name': fname,
                'label': info.get('string'),
                'type': info.get('type'),
            }
            if info.get('relation'):
                entry['relation'] = info['relation']
            if info.get('selection'):
                entry['selection'] = [s[0] for s in info['selection'] if isinstance(s, (list, tuple))]
            out.append(entry)
        return {'model': model_name, 'fields': out}

    def _tool_search_records(self, args, user_env):
        model_name = args.get('model')
        if not self._is_model_allowed(model_name):
            return {'error': "Model '%s' is not in the allowed list." % model_name}
        if model_name not in user_env:
            return {'error': "Unknown model: %s" % model_name}
        Model = user_env[model_name]
        domain = args.get('domain') or []
        fields_list = args.get('fields') or []
        limit = min(int(args.get('limit') or 20), 200)
        order = args.get('order') or None
        records = Model.search_read(
            domain=domain,
            fields=fields_list or None,
            limit=limit,
            order=order,
        )
        records = [self._sanitize_for_json(r) for r in records]
        return {'count': len(records), 'records': records}

    def _tool_read_group(self, args, user_env):
        model_name = args.get('model')
        if not self._is_model_allowed(model_name):
            return {'error': "Model '%s' is not in the allowed list." % model_name}
        if model_name not in user_env:
            return {'error': "Unknown model: %s" % model_name}
        Model = user_env[model_name]
        domain = args.get('domain') or []
        fields_list = args.get('fields') or []
        groupby = args.get('groupby') or []
        result = Model.read_group(
            domain=domain,
            fields=fields_list,
            groupby=groupby,
            lazy=False,
        )
        result = [self._sanitize_for_json(g) for g in result]
        return {'groups': result}

    # --------------------------------------------------------------------- #
    # Provider dispatch
    # --------------------------------------------------------------------- #
    def _effective_system_prompt(self):
        """Return the stored system prompt with mandatory formatting rules appended.

        This ensures table formatting is enforced at runtime even when the
        database record was created before the formatting rules were added.
        """
        base = (self.system_prompt or DEFAULT_SYSTEM_PROMPT).rstrip()
        formatting = """

MANDATORY RESPONSE FORMAT — follow this exactly, no exceptions:
- When the answer contains multiple records (orders, invoices, products, customers, purchases, etc.), you MUST present them as a markdown table using | Col | Col | syntax with a |---|---| separator row on the second line.
- Choose short, clear column headers relevant to the data (e.g. #, Name, Date, Customer, Status, Total).
- NEVER use bullet points, numbered lists, or prose sentences to list records.
- For a single scalar answer (a count, a total, an average), reply in exactly one short sentence.
- For grouped or aggregated results, use a table with Group and Value columns.
- Always include a brief one-sentence summary above the table (e.g. "Here are your 10 most recent sale orders:").
"""
        return base + formatting

    def _run_completion(self, messages, tools, user_env):
        """Send one request to the provider and normalize the response into:
        {'content': str, 'tool_calls': [{'id', 'name', 'arguments'}, ...], 'raw': ...}
        """
        self.ensure_one()
        if self.provider in ('openai', 'deepseek', 'perplexity'):
            return self._completion_openai_compatible(messages, tools)
        if self.provider == 'anthropic':
            return self._completion_anthropic(messages, tools)
        if self.provider == 'gemini':
            return self._completion_gemini(messages, tools)
        raise UserError(_("Unsupported provider: %s") % self.provider)

    def _sanitize_for_json(self, val):
        """Recursively convert Odoo ORM values that are not JSON-serializable."""
        if isinstance(val, (datetime.datetime, datetime.date)):
            return val.isoformat()
        if isinstance(val, dict):
            return {k: self._sanitize_for_json(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [self._sanitize_for_json(v) for v in val]
        return val

    def _http_post(self, url, headers, payload):
        resp = requests.post(url, headers=headers, data=json.dumps(payload, default=str), timeout=120)
        if resp.status_code >= 400:
            raise UserError(_("AI provider error %(code)s: %(body)s") % {
                'code': resp.status_code,
                'body': resp.text[:1000],
            })
        return resp.json()

    # ---- OpenAI / DeepSeek / Perplexity (Chat Completions + tools) -------- #
    def _completion_openai_compatible(self, messages, tools):
        url = "%s/chat/completions" % self._effective_base_url()
        headers = {
            'Authorization': 'Bearer %s' % self.api_key,
            'Content-Type': 'application/json',
        }
        payload_messages = [{'role': 'system', 'content': self._effective_system_prompt()}]
        payload_messages += messages
        payload = {
            'model': self.model,
            'messages': payload_messages,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
        }
        if tools:
            payload['tools'] = [
                {'type': 'function', 'function': t} for t in tools
            ]
            payload['tool_choice'] = 'auto'
        data = self._http_post(url, headers, payload)
        choice = (data.get('choices') or [{}])[0]
        msg = choice.get('message') or {}
        tool_calls = []
        for tc in (msg.get('tool_calls') or []):
            fn = tc.get('function') or {}
            try:
                arguments = json.loads(fn.get('arguments') or '{}')
            except (ValueError, TypeError):
                arguments = {}
            tool_calls.append({
                'id': tc.get('id'),
                'name': fn.get('name'),
                'arguments': arguments,
            })
        return {'content': msg.get('content') or '', 'tool_calls': tool_calls, 'raw': msg}

    def _assistant_tool_message_openai(self, result):
        raw = result.get('raw') or {}
        return {
            'role': 'assistant',
            'content': raw.get('content') or '',
            'tool_calls': raw.get('tool_calls') or [],
        }

    # ---- Anthropic (Messages API + tools) --------------------------------- #
    def _completion_anthropic(self, messages, tools):
        url = "%s/messages" % self._effective_base_url()
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': self.model,
            'system': self._effective_system_prompt(),
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'messages': self._to_anthropic_messages(messages),
        }
        if tools:
            payload['tools'] = [
                {
                    'name': t['name'],
                    'description': t.get('description', ''),
                    'input_schema': t.get('parameters', {'type': 'object', 'properties': {}}),
                }
                for t in tools
            ]
        data = self._http_post(url, headers, payload)
        content_blocks = data.get('content') or []
        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if block.get('type') == 'text':
                text_parts.append(block.get('text') or '')
            elif block.get('type') == 'tool_use':
                tool_calls.append({
                    'id': block.get('id'),
                    'name': block.get('name'),
                    'arguments': block.get('input') or {},
                })
        return {
            'content': '\n'.join(text_parts),
            'tool_calls': tool_calls,
            'raw': content_blocks,
        }

    def _to_anthropic_messages(self, messages):
        """Map our internal message list to Anthropic's format. Plain history
        turns are {role, content:str}; turns appended during the tool loop are
        already native (content is a list of tool_use / tool_result blocks) and
        must be passed through unchanged."""
        out = []
        for m in messages:
            role = m.get('role')
            if role == 'system':
                continue
            content = m.get('content')
            if isinstance(content, list):
                out.append({'role': role, 'content': content})
            elif role in ('user', 'assistant'):
                out.append({'role': role, 'content': content or ''})
        return out

    def _assistant_tool_message_anthropic(self, result):
        # Reconstruct the assistant turn (text + tool_use blocks) for the next call.
        return {'role': 'assistant', 'content': result.get('raw') or []}

    # ---- Gemini ----------------------------------------------------------- #
    def _completion_gemini(self, messages, tools):
        url = "%s/models/%s:generateContent?key=%s" % (
            self._effective_base_url(), self.model, self.api_key)
        headers = {'Content-Type': 'application/json'}
        payload = {
            'systemInstruction': {
                'parts': [{'text': self._effective_system_prompt()}],
            },
            'contents': self._to_gemini_contents(messages),
            'generationConfig': {
                'temperature': self.temperature,
                'maxOutputTokens': self.max_tokens,
            },
        }
        if tools:
            payload['tools'] = [{
                'functionDeclarations': [
                    {
                        'name': t['name'],
                        'description': t.get('description', ''),
                        'parameters': t.get('parameters', {'type': 'object', 'properties': {}}),
                    }
                    for t in tools
                ],
            }]
        data = self._http_post(url, headers, payload)
        candidates = data.get('candidates') or [{}]
        parts = (((candidates[0] or {}).get('content') or {}).get('parts')) or []
        text_parts = []
        tool_calls = []
        for part in parts:
            if 'text' in part:
                text_parts.append(part['text'])
            elif 'functionCall' in part:
                fc = part['functionCall']
                tool_calls.append({
                    'id': fc.get('name'),  # Gemini matches by function name
                    'name': fc.get('name'),
                    'arguments': fc.get('args') or {},
                })
        return {
            'content': '\n'.join(text_parts),
            'tool_calls': tool_calls,
            'raw': parts,
        }

    def _to_gemini_contents(self, messages):
        out = []
        for m in messages:
            role = m.get('role')
            if role == 'system':
                continue
            if 'parts' in m:
                # Already native (functionCall / functionResponse parts).
                out.append({'role': m.get('role'), 'parts': m['parts']})
                continue
            gemini_role = 'model' if role == 'assistant' else 'user'
            out.append({'role': gemini_role, 'parts': [{'text': m.get('content') or ''}]})
        return out

    def _assistant_tool_message_gemini(self, result):
        return {'role': 'model', 'parts': result.get('raw') or []}

    # ---- Dispatch helpers for history rebuilding -------------------------- #
    def _assistant_tool_message(self, result):
        if self.provider == 'anthropic':
            return self._assistant_tool_message_anthropic(result)
        if self.provider == 'gemini':
            return self._assistant_tool_message_gemini(result)
        return self._assistant_tool_message_openai(result)

    def _tool_result_messages(self, tool_outputs):
        """Build the message(s) carrying tool results back to the model.

        `tool_outputs` is a list of (call, output) tuples. OpenAI-compatible
        APIs want one 'tool' message per call; Anthropic and Gemini want all
        results from the turn grouped into a single user message.
        """
        if self.provider == 'anthropic':
            blocks = [{
                'type': 'tool_result',
                'tool_use_id': call.get('id'),
                'content': json.dumps(output, default=str),
            } for call, output in tool_outputs]
            return [{'role': 'user', 'content': blocks}]
        if self.provider == 'gemini':
            parts = [{
                'functionResponse': {
                    'name': call.get('name'),
                    'response': {'result': output},
                },
            } for call, output in tool_outputs]
            return [{'role': 'user', 'parts': parts}]
        # OpenAI / DeepSeek / Perplexity
        return [{
            'role': 'tool',
            'tool_call_id': call.get('id'),
            'content': json.dumps(output, default=str),
        } for call, output in tool_outputs]
