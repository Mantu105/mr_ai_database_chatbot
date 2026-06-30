# -*- coding: utf-8 -*-
{
    'name': 'AI Database Chatbot',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Discuss',
    'summary': 'Query your Odoo database in natural language with a multi-provider '
               'AI assistant that respects user access rights.',
    'description': """
AI Database Chatbot
===================

An intelligent, AI-powered chatbot that interacts directly with your Odoo
database and returns instant answers across all modules using natural language.

Key features
------------
* Natural language queries against live Odoo data.
* Multi-provider support (Bring Your Own Key): OpenAI, Anthropic, Google
  Gemini, DeepSeek and Perplexity.
* Strict access control: the assistant reads data **as the current user**, so
  Odoo record rules and access rights are always enforced.
* Optional whitelist restricting which models the assistant may read.
* Floating chat widget available across the backend.
* Persisted conversation history.

This is an original, clean-room implementation under LGPL-3.
""",
    'author': 'Mantu Raj',
    'website': 'https://www.linkedin.com/in/mantu105/',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/ai_chatbot_security.xml',
        'security/ir.model.access.csv',
        'data/ai_chatbot_data.xml',
        'views/ai_chatbot_config_views.xml',
        'views/ai_chatbot_conversation_views.xml',
        'views/ai_chatbot_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mr_ai_database_chatbot/static/src/scss/chatbot_widget.scss',
            'mr_ai_database_chatbot/static/src/js/chatbot_service.js',
            'mr_ai_database_chatbot/static/src/js/chatbot_widget.js',
            'mr_ai_database_chatbot/static/src/xml/chatbot_widget.xml',
        ],
    },
    'images': ['static/description/banner.png'],
    'price': 95.0,
    'currency': 'USD',
    'installable': True,
    'application': True,
    'auto_install': False,
}
