# -*- coding: utf-8 -*-
from odoo import fields, models


class AiChatbotMessage(models.Model):
    _name = 'ai.chatbot.message'
    _description = 'AI Chatbot Message'
    _order = 'id asc'

    conversation_id = fields.Many2one(
        'ai.chatbot.conversation',
        string='Conversation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    role = fields.Selection(
        selection=[
            ('user', 'User'),
            ('assistant', 'Assistant'),
        ],
        required=True,
        default='user',
    )
    content = fields.Text(string='Content')
    create_date = fields.Datetime(string='Sent On', readonly=True)
