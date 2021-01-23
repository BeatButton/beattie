from discord.ext.commands import Cog, Command, MinimalHelpCommand


class BHelp(MinimalHelpCommand):
    async def send_bot_help(self, mapping: dict[Cog, list[Command]]):
        await super().send_bot_help(mapping)
        await self.context.send(
            "Join the support server for more help: discord.gg/a3kHCRs9Q8"
        )

    def add_subcommand_formatting(self, command: Command) -> None:
        fmt = "{0} \N{EN DASH} {1}" if command.short_doc else "{0}"
        self.paginator.add_line(
            fmt.format(
                self.get_command_signature(command),
                command.short_doc,
            )
        )
