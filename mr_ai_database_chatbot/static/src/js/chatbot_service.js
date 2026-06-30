/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * Thin service exposing the AI chatbot backend endpoints to OWL components.
 */
export const aiChatbotService = {
    start() {
        return {
            status() {
                return rpc("/ai_chatbot/status");
            },
            newConversation() {
                return rpc("/ai_chatbot/conversation/new");
            },
            sendMessage(message, conversationId) {
                return rpc("/ai_chatbot/send_message", {
                    message,
                    conversation_id: conversationId || null,
                });
            },
        };
    },
};

registry.category("services").add("ai_chatbot", aiChatbotService);
