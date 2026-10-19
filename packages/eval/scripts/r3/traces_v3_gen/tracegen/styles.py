# SPDX-License-Identifier: Apache-2.0
"""Plain-text renderings of a transcript. Each template uses exactly one
style (consistent within a template); styles differ across templates."""

from __future__ import annotations

from .core import F, Seg, T, esc_json, ensure_nl, lstrip_nl, merge_plain, prefix_lines, rstrip_nl
from .distract import fmt_ts
from .values import HEX, rand_str

TOOLS = ("sh", "read", "edit", "write", "grep", "glob", "fetch")


class Style:
    name = "base"
    tools: dict = {}

    def tool(self, t: str) -> str:
        return self.tools.get(t, t)

    def header(self, d) -> list:
        return []

    def footer(self, d) -> list:
        return []

    def user(self, d, body: list) -> list:
        raise NotImplementedError

    def agent(self, d, body: list) -> list:
        raise NotImplementedError

    def call(self, d, tool: str, arg: list) -> list:
        raise NotImplementedError

    def result(self, d, tool: str, body: list) -> list:
        raise NotImplementedError


def _body(frag: list) -> list:
    return rstrip_nl(lstrip_nl(frag))


class CCStyle(Style):
    """Bulleted terminal transcript with indented tool output."""
    name = "cc"
    tools = {"sh": "Bash", "read": "Read", "edit": "Update", "write": "Write", "grep": "Search", "glob": "Glob",
             "fetch": "Fetch"}

    def header(self, d):
        return F("╭───────────────────────────────────────────╮\n",
                 "│ ✻ session ", d.x.uuid(), "\n",
                 "│   cwd: ", d.cwd(), "\n",
                 "╰───────────────────────────────────────────╯\n\n")

    def user(self, d, body):
        return F(prefix_lines(_body(body), "> ", "  "), "\n\n")

    def agent(self, d, body):
        return F(prefix_lines(_body(body), "⏺ ", "  "), "\n\n")

    def call(self, d, tool, arg):
        return F("⏺ ", self.tool(tool), "(", arg, ")\n")

    def result(self, d, tool, body):
        b = _body(body)
        if not b:
            b = F("(no output)")
        return F(prefix_lines(b, "  ⎿  ", "     "), "\n\n")


class XmlStyle(Style):
    name = "xml"
    tools = {"sh": "run_shell", "read": "read_file", "edit": "edit_file", "write": "write_file", "grep": "search",
             "glob": "list_files", "fetch": "http_request"}

    def header(self, d):
        return F('<session id="', d.x.uuid(), '" started="', d.x.ts("iso_s"), '">\n')

    def footer(self, d):
        return F("</session>\n")

    def user(self, d, body):
        return F("<user>\n", _body(body), "\n</user>\n")

    def agent(self, d, body):
        return F("<assistant>\n", _body(body), "\n</assistant>\n")

    def call(self, d, tool, arg):
        key = {"sh": "command", "read": "path", "edit": "path", "write": "path", "grep": "pattern",
               "glob": "pattern", "fetch": "url"}[tool]
        return F(f'<tool_call name="{self.tool(tool)}" {key}="', arg, '"/>\n')

    def result(self, d, tool, body):
        return F(f'<tool_result name="{self.tool(tool)}">\n', _body(body), "\n</tool_result>\n")


class MdStyle(Style):
    name = "md"
    tools = {"sh": "shell", "read": "read_file", "edit": "str_replace", "write": "create_file", "grep": "grep",
             "glob": "find", "fetch": "fetch"}

    def header(self, d):
        return F("# Agent session — ", d.project, "\n\n_started ", d.x.ts("space"), "_\n\n")

    def user(self, d, body):
        return F("## User\n\n", _body(body), "\n\n")

    def agent(self, d, body):
        return F("## Assistant\n\n", _body(body), "\n\n")

    def call(self, d, tool, arg):
        return F("**Tool call** `", self.tool(tool), "` — `", arg, "`\n\n")

    def result(self, d, tool, body):
        return F("```\n", _body(body), "\n```\n\n")


class ColonStyle(Style):
    name = "colon"
    tools = {"sh": "bash", "read": "cat", "edit": "patch", "write": "write", "grep": "rg", "glob": "find",
             "fetch": "curl"}

    def user(self, d, body):
        return F(prefix_lines(_body(body), "USER: ", "      "), "\n\n")

    def agent(self, d, body):
        return F(prefix_lines(_body(body), "AGENT: ", "       "), "\n\n")

    def call(self, d, tool, arg):
        return F("CALL ", self.tool(tool), ": ", arg, "\n")

    def result(self, d, tool, body):
        return F("OUTPUT:\n", prefix_lines(_body(body), "    "), "\n\n")


class JsonlStyle(Style):
    """One JSON event per line; every string is JSON-escaped segment by segment."""
    name = "jsonl"
    tools = {"sh": "exec_command", "read": "read_file", "edit": "apply_patch", "write": "write_file",
             "grep": "grep_search", "glob": "file_search", "fetch": "web_fetch"}

    def header(self, d):
        return F('{"type":"session_meta","id":"', d.x.uuid(), '","cwd":"', esc_json(d.cwd()),
                 '","ts":"', d.x.ts("iso_z"), '"}\n')

    def user(self, d, body):
        return F('{"type":"message","role":"user","ts":"', d.x.ts("iso_z", tick=(5, 90)), '","content":"',
                 esc_json(_body(body)), '"}\n')

    def agent(self, d, body):
        return F('{"type":"message","role":"assistant","ts":"', d.x.ts("iso_z", tick=(2, 20)), '","content":"',
                 esc_json(_body(body)), '"}\n')

    def call(self, d, tool, arg):
        key = {"sh": "cmd", "read": "path", "edit": "path", "write": "path", "grep": "query", "glob": "glob",
               "fetch": "url"}[tool]
        d.state["call_id"] = "call_" + rand_str(d.rng, HEX, 12)
        return F('{"type":"function_call","call_id":"', d.state["call_id"], '","name":"', self.tool(tool),
                 '","arguments":{"', key, '":"', esc_json(arg), '"}}\n')

    def result(self, d, tool, body):
        return F('{"type":"function_call_output","call_id":"', d.state.get("call_id", "call_0"), '","output":"',
                 esc_json(_body(body)), '"}\n')


class TsLogStyle(Style):
    name = "tslog"
    tools = {"sh": "sh", "read": "view", "edit": "edit", "write": "create", "grep": "search", "glob": "glob",
             "fetch": "fetch"}

    def _ts(self, d, lo, hi):
        return F("[", d.x.ts("time", tick=(lo, hi)), "] ")

    def user(self, d, body):
        return F(self._ts(d, 10, 120), "you> ", prefix_lines(_body(body), "", "           "), "\n")

    def agent(self, d, body):
        return F(self._ts(d, 2, 15), "agent> ", prefix_lines(_body(body), "", "             "), "\n")

    def call(self, d, tool, arg):
        if tool == "sh":
            return F(self._ts(d, 1, 4), "agent ran: $ ", arg, "\n")
        return F(self._ts(d, 1, 4), "agent ", self.tool(tool), ": ", arg, "\n")

    def result(self, d, tool, body):
        return F(ensure_nl(_body(body)) if _body(body) else "", self._ts(d, 0.2, 6), "(end of ", self.tool(tool),
                 " output)\n")


class BoxStyle(Style):
    name = "box"
    tools = {"sh": "terminal", "read": "open", "edit": "modify", "write": "new file", "grep": "search",
             "glob": "glob", "fetch": "browse"}

    def user(self, d, body):
        return F("▌ You\n", prefix_lines(_body(body), "▌ "), "\n\n")

    def agent(self, d, body):
        return F(prefix_lines(_body(body), "◆ ", "  "), "\n\n")

    def call(self, d, tool, arg):
        return F("┌─ ", self.tool(tool), " ─ ", arg, "\n")

    def result(self, d, tool, body):
        return F(prefix_lines(_body(body), "│ "), "\n└─\n\n")


class HumanAIStyle(Style):
    name = "hai"
    tools = {"sh": "run", "read": "read", "edit": "edit", "write": "write", "grep": "search", "glob": "glob",
             "fetch": "fetch"}

    def user(self, d, body):
        return F("Human: ", _body(body), "\n\n")

    def agent(self, d, body):
        return F("Assistant: ", _body(body), "\n\n")

    def call(self, d, tool, arg):
        return F("[tool:", self.tool(tool), "] ", arg, "\n")

    def result(self, d, tool, body):
        return F("[output]\n", _body(body), "\n[/output]\n\n")


class IrcStyle(Style):
    name = "irc"
    tools = {"sh": "exec", "read": "read", "edit": "edit", "write": "write", "grep": "grep", "glob": "glob",
             "fetch": "wget"}

    def _nick(self, d):
        return d.dev_user()

    def user(self, d, body):
        return F("<", self._nick(d), "> ", prefix_lines(_body(body), "", "    "), "\n")

    def agent(self, d, body):
        return F("<agent> ", prefix_lines(_body(body), "", "        "), "\n")

    def call(self, d, tool, arg):
        return F("<agent> ⚙ ", self.tool(tool), " ", arg, "\n")

    def result(self, d, tool, body):
        return F(prefix_lines(_body(body), "   | "), "\n")


class ReactStyle(Style):
    name = "react"
    tools = {"sh": "Shell", "read": "ReadFile", "edit": "EditFile", "write": "WriteFile", "grep": "Search",
             "glob": "ListDir", "fetch": "HttpGet"}

    def user(self, d, body):
        first = not d.state.get("task_seen")
        d.state["task_seen"] = True
        return F("Task: " if first else "User: ", _body(body), "\n")

    def agent(self, d, body):
        return F("Thought: ", _body(body), "\n")

    def call(self, d, tool, arg):
        return F("Action: ", self.tool(tool), "\nAction Input: ", arg, "\n")

    def result(self, d, tool, body):
        return F("Observation:\n", _body(body), "\n")


class StepsStyle(Style):
    name = "steps"
    tools = {"sh": "shell", "read": "file.read", "edit": "file.edit", "write": "file.write", "grep": "code.search",
             "glob": "fs.glob", "fetch": "net.fetch"}

    def _step(self, d):
        d.state["step"] = d.state.get("step", 0) + 1
        return F("--- step ", str(d.state["step"]), " ---\n")

    def user(self, d, body):
        return F(self._step(d), "[user]\n", _body(body), "\n\n")

    def agent(self, d, body):
        return F(self._step(d), "[assistant]\n", _body(body), "\n\n")

    def call(self, d, tool, arg):
        return F(self._step(d), "[tool:", self.tool(tool), "] ", arg, "\n")

    def result(self, d, tool, body):
        return F(prefix_lines(_body(body), "  "), "\n\n")


class AiderStyle(Style):
    name = "aider"
    tools = {"sh": "/run", "read": "/read-only", "edit": "/edit", "write": "/add", "grep": "/run rg", "glob": "/ls",
             "fetch": "/web"}

    def header(self, d):
        return F("aider session · model ", d.x.ent(d.rng.choice(["Claude", "GPT-4o", "Gemini", "DeepSeek"])),
                 " · repo ", d.project, "\n\n")

    def user(self, d, body):
        return F(prefix_lines(_body(body), "#### "), "\n\n")

    def agent(self, d, body):
        return F(_body(body), "\n\n")

    def call(self, d, tool, arg):
        return F("> ", self.tool(tool), " ", arg, "\n")

    def result(self, d, tool, body):
        return F(prefix_lines(_body(body), "  "), "\n\n")


class PlainChatStyle(Style):
    """Minimal: role on its own line, tool output fenced by a rule."""
    name = "plain"
    tools = {"sh": "$", "read": "read", "edit": "edit", "write": "write", "grep": "grep", "glob": "glob",
             "fetch": "GET"}

    def user(self, d, body):
        return F("user\n", _body(body), "\n\n")

    def agent(self, d, body):
        return F("agent\n", _body(body), "\n\n")

    def call(self, d, tool, arg):
        if tool == "sh":
            return F("$ ", arg, "\n")
        return F("· ", self.tool(tool), " ", arg, "\n")

    def result(self, d, tool, body):
        return F(_body(body), "\n────────\n\n")


STYLES = {s.name: s for s in (CCStyle(), XmlStyle(), MdStyle(), ColonStyle(), JsonlStyle(), TsLogStyle(),
                               BoxStyle(), HumanAIStyle(), IrcStyle(), ReactStyle(), StepsStyle(), AiderStyle(),
                               PlainChatStyle())}
