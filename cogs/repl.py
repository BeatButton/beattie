import asyncio
from contextlib import redirect_stdout
import inspect
import io
import os
import sys
import textwrap
import traceback
import discord
from discord.ext import commands


# imports for REPL env
import math  # noqa: F401
import objgraph  # noqa: F401


class REPL(commands.Cog):
    def __init__(self):
        self._last_result = None
        self.sessions = set()

    async def cog_check(self, ctx):
        return await ctx.bot.is_owner(ctx.author)

    def cleanup_code(self, content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])

        # remove `foo`
        return content.strip("` \n").lstrip("<")

    def get_syntax_error(self, e):
        return f'```py\n{e.text}{"^":>{e.offset}}\n{type(e).__name__}: {e}```'

    @commands.command(hidden=True, name="eval")
    async def eval_(self, ctx, *, body: str):
        env = {
            "author": ctx.author,
            "bot": ctx.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "guild": ctx.guild,
            "message": ctx.message,
            "_": self._last_result,
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(self.get_syntax_error(e))

        func = env["func"]
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send(f"```py\n{value}{traceback.format_exc()}\n```")
        else:
            value = stdout.getvalue()

            if ret is None:
                if value:
                    await ctx.send(f"```py\n{value}\n```")
            else:
                self._last_result = ret
                await ctx.send(f"```py\n{value}{ret}\n```")

    @commands.command(hidden=True)
    async def peval(self, ctx, *, body: str):
        body = self.cleanup_code(body)
        await ctx.invoke(self.eval_, body=f"print({body})")

    @commands.command(hidden=True)
    async def repl(self, ctx):
        env = {
            "author": ctx.author,
            "bot": ctx.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "guild": ctx.guild,
            "message": ctx.message,
            "_": None,
        }

        env.update(globals())

        if ctx.channel.id in self.sessions:
            await ctx.send(
                "Already running a REPL session in this channel. "
                "Exit it with `quit`."
            )
            return

        self.sessions.add(ctx.channel.id)
        await ctx.send(
            "Enter code to execute or evaluate. " "`exit()` or `quit` to exit."
        )
        while True:
            response = await (
                ctx.bot.wait_for(
                    "message",
                    check=lambda m: m.content.startswith("<")
                    and (m.author, m.channel) == (ctx.author, ctx.channel),
                )
            )

            cleaned = self.cleanup_code(response.content)

            if cleaned in ("quit", "exit", "exit()"):
                await ctx.send("Exiting.")
                self.sessions.remove(ctx.channel.id)
                return

            executor = exec
            if cleaned.count("\n") == 0:
                # single statement, potentially 'eval'
                try:
                    code = compile(cleaned, "<repl session>", "eval")
                except SyntaxError:
                    pass
                else:
                    executor = eval

            if executor is exec:
                try:
                    code = compile(cleaned, "<repl session>", "exec")
                except SyntaxError as e:
                    await ctx.send(self.get_syntax_error(e))
                    continue

            env["message"] = response

            fmt = None
            stdout = io.StringIO()

            try:
                with redirect_stdout(stdout):
                    result = executor(code, env)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception as e:
                value = stdout.getvalue()
                fmt = f"```py\n{value}{traceback.format_exc()}\n```"
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = f"```py\n{value}{result}\n```"
                    env["_"] = result
                elif value:
                    fmt = f"```py\n{value}\n```"

            try:
                if fmt is not None:
                    if len(fmt) > 2000:
                        await ctx.send("Content too big to be printed.")
                    else:
                        await ctx.send(fmt)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await ctx.send(f"Unexpected error: `{e}`")

    @commands.command()
    async def run(self, ctx, *, command):
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/usr/bin/fish",
        )
        stdout, stderr = (text.decode() for text in await proc.communicate())
        res = ""
        if stdout:
            res = f"Output:```\n{stdout}```"
        if stderr:
            res += f"Error:```\n{stderr}```"
        if not res:
            res = "No result."
        await ctx.send(res)

    @commands.command()
    async def restart(self, ctx):
        await ctx.invoke(self.run, command="sudo systemctl restart beattie.service")

    @commands.command()
    async def reload(self, ctx, *, cog):
        cog = f"cogs.{cog.lower()}"
        ctx.bot.reload_extension(cog)
        await ctx.send("Reload successful.")


def setup(bot):
    bot.add_cog(REPL())
