# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiChatbotConversation(models.Model):
    _name = 'ai.chatbot.conversation'
    _description = 'AI Chatbot Conversation'
    _order = 'write_date desc, id desc'

    name = fields.Char(default='New Conversation')
    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.user,
        index=True,
        ondelete='cascade',
    )
    config_id = fields.Many2one(
        'ai.chatbot.config',
        string='AI Configuration',
    )
    message_ids = fields.One2many(
        'ai.chatbot.message',
        'conversation_id',
        string='Messages',
    )
    message_count = fields.Integer(compute='_compute_message_count', store=True)

    @api.depends('message_ids')
    def _compute_message_count(self):
        for conv in self:
            conv.message_count = len(conv.message_ids)

    def _set_title_from_first_message(self, text):
        """Use the first user message as a friendly conversation title."""
        self.ensure_one()
        if self.name and self.name != 'New Conversation':
            return
        clean = (text or '').strip().replace('\n', ' ')
        if clean:
            self.name = clean[:60] + ('…' if len(clean) > 60 else '')
