from discord import TextChannel, Thread, VoiceChannel

GuildMessageable = TextChannel | VoiceChannel | Thread
