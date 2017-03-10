class NSFW:
    @commands.command(hidden=True, aliases=['gel'])
    async def gelbooru(self, ctx, *, tags):
        async with ctx.typing():
            entries = []
            url = 'http://gelbooru.com/index.php'
            params = {'page': 'dapi',
                      's': 'post',
                      'q': 'index',
                      'tags': tags}
            async with self.bot.session.get(url, params=params) as resp:
                root = etree.fromstring((await resp.text()).encode(),
                                        etree.HTMLParser())
            search_nodes = root.findall(".//post")
            for node in search_nodes:
                image = dict(node.items()).get('file_url', None)
                if image is not None:
                    entries.append(image)
            try:
                message = f'http:{random.choice(entries)}'
            except IndexError:
                message = 'No images found.'
        await ctx.send(message)

    @commands.command(hidden=True)
    async def massage(self, ctx):
        await ctx.invoke(self.gelbooru, 'massage')


def setup(bot):
    bot.add_cog(NSFW(bot))
