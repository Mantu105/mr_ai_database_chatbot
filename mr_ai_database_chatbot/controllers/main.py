# -*- coding: utf-8 -*-
import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiChatbotController(http.Controller):

    @http.route('/ai_chatbot/status', type='json', auth='user')
    def status(self):
        """Tell the widget whether a usable configuration exists."""
        config = request.env['ai.chatbot.config'].sudo().get_active_config()
        return {
            'configured': bool(config and config.api_key),
            'provider': config.provider if config else False,
            'model': config.model if config else False,
        }

    @http.route('/ai_chatbot/conversation/new', type='json', auth='user')
    def new_conversation(self):
        conv = request.env['ai.chatbot.conversation'].create({
            'name': 'New Conversation',
            'config_id': request.env['ai.chatbot.config'].sudo().get_active_config().id or False,
        })
        return {'conversation_id': conv.id, 'name': conv.name}

    @http.route('/ai_chatbot/conversation/history', type='json', auth='user')
    def conversation_history(self, conversation_id):
        conv = request.env['ai.chatbot.conversation'].browse(int(conversation_id))
        conv.check_access('read')
        return {
            'conversation_id': conv.id,
            'name': conv.name,
            'messages': [
                {'role': m.role, 'content': m.content}
                for m in conv.message_ids.sorted('id')
            ],
        }

    @http.route('/ai_chatbot/send_message', type='json', auth='user')
    def send_message(self, message, conversation_id=None):
        """Main entry point: store the user message, run the AI query loop as the
        current user, persist and return the assistant's answer."""
        env = request.env
        message = (message or '').strip()
        if not message:
            return {'error': _("Empty message.")}

        # Config is read with sudo (it holds the shared API key), but all data
        # queries inside process_query run as the requesting user.
        config = env['ai.chatbot.config'].sudo().get_active_config()
        if not config or not config.api_key:
            return {'error': _("The AI chatbot is not configured. Please ask an "
                               "administrator to set up an AI provider.")}

        Conversation = env['ai.chatbot.conversation']
        if conversation_id:
            conversation = Conversation.browse(int(conversation_id))
            conversation.check_access('write')
        else:
            conversation = Conversation.create({'config_id': config.id})

        # Persist the user's message.
        env['ai.chatbot.message'].create({
            'conversation_id': conversation.id,
            'role': 'user',
            'content': message,
        })
        conversation._set_title_from_first_message(message)

        try:
            # Config stays privileged (holds the API key), but every data read
            # inside process_query goes through the requesting user's env so
            # record rules and access rights are fully enforced.
            answer = config.process_query(conversation, user_env=env)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("AI chatbot failed to answer")
            return {
                'conversation_id': conversation.id,
                'error': _("The assistant could not complete your request: %s") % exc,
            }

        env['ai.chatbot.message'].create({
            'conversation_id': conversation.id,
            'role': 'assistant',
            'content': answer,
        })

        return {
            'conversation_id': conversation.id,
            'name': conversation.name,
            'answer': answer,
        }
