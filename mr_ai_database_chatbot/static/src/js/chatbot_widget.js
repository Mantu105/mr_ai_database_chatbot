/** @odoo-module **/

import { Component, useState, useRef, onMounted, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AiChatbotWidget extends Component {
    static template = "mr_ai_database_chatbot.AiChatbotWidget";
    static props = {};

    setup() {
        this.chatbot = useService("ai_chatbot");
        this.scrollRef = useRef("scroll");
        this.inputRef = useRef("input");
        this.state = useState({
            open: false,
            configured: true,
            loading: false,
            input: "",
            conversationId: null,
            messages: [],
        });

        onMounted(async () => {
            try {
                const status = await this.chatbot.status();
                this.state.configured = !!status.configured;
            } catch {
                this.state.configured = false;
            }
        });
    }

    // Returns "HH:MM" from a timestamp
    getTime(timestamp) {
        if (!timestamp) return "";
        return new Date(timestamp).toLocaleTimeString([], {
            hour: "2-digit", minute: "2-digit", hour12: false,
        });
    }

    // Returns "Today", "Yesterday", or "DD MMM YYYY"
    getDateLabel(timestamp) {
        if (!timestamp) return "";
        const d = new Date(timestamp);
        const today = new Date();
        const yesterday = new Date();
        yesterday.setDate(today.getDate() - 1);
        const same = (a, b) =>
            a.getFullYear() === b.getFullYear() &&
            a.getMonth() === b.getMonth() &&
            a.getDate() === b.getDate();
        if (same(d, today)) return "Today";
        if (same(d, yesterday)) return "Yesterday";
        return d.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" });
    }

    // Markdown → safe HTML markup
    renderMarkdown(text) {
        if (!text) return markup("");

        let html = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // Tables
        const lines = html.split("\n");
        const result = [];
        let i = 0;
        while (i < lines.length) {
            const line = lines[i];
            if (/^\|.+\|$/.test(line.trim())) {
                const tableLines = [];
                while (i < lines.length && /^\|.+\|$/.test(lines[i].trim())) {
                    tableLines.push(lines[i].trim());
                    i++;
                }
                let tableHtml = '<table class="o_ai_table"><thead>';
                let headerDone = false;
                for (const tl of tableLines) {
                    if (/^\|[\s\-:|]+\|$/.test(tl)) {
                        if (!headerDone) { tableHtml += "</thead><tbody>"; headerDone = true; }
                        continue;
                    }
                    const cells = tl.split("|").slice(1, -1);
                    const tag = !headerDone ? "th" : "td";
                    tableHtml += "<tr>" + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join("") + "</tr>";
                }
                if (!headerDone) tableHtml += "</thead><tbody>";
                tableHtml += "</tbody></table>";
                result.push('<div class="o_ai_table_wrap">' + tableHtml + "</div>");
            } else {
                result.push(line);
                i++;
            }
        }
        html = result.join("\n");

        html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>");
        html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
        html = html.replace(/^[\*\-] (.+)$/gm, "<li>$1</li>");
        html = html.replace(/(<li>[\s\S]*?<\/li>)(\n<li>[\s\S]*?<\/li>)*/g, (m) => `<ul>${m}</ul>`);
        html = html.replace(/\n/g, "<br>");

        return markup(html);
    }

    toggle() {
        this.state.open = !this.state.open;
        if (this.state.open) this._scrollToBottom();
    }

    newChat() {
        this.state.messages = [];
        this.state.conversationId = null;
        this.state.input = "";
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    async send() {
        const text = (this.state.input || "").trim();
        if (!text || this.state.loading) return;

        this.state.messages.push({ role: "user", content: text, timestamp: Date.now() });
        this.state.input = "";
        this.state.loading = true;
        this._scrollToBottom();

        try {
            const res = await this.chatbot.sendMessage(text, this.state.conversationId);
            if (res && res.conversation_id) this.state.conversationId = res.conversation_id;
            this.state.messages.push({
                role: "assistant",
                content: res && res.error ? res.error : (res && res.answer) || "(no answer)",
                timestamp: Date.now(),
            });
        } catch {
            this.state.messages.push({
                role: "assistant",
                content: "Something went wrong while contacting the assistant. Please try again.",
                timestamp: Date.now(),
            });
        } finally {
            this.state.loading = false;
            this._scrollToBottom();
        }
    }

    _scrollToBottom() {
        requestAnimationFrame(() => {
            const el = this.scrollRef.el;
            if (el) el.scrollTop = el.scrollHeight;
        });
    }
}

registry.category("main_components").add("AiChatbotWidget", {
    Component: AiChatbotWidget,
});
