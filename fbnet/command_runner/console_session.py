#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import asyncio
from collections import namedtuple

from .command_session import SSHCommandSession


class ConsoleInfo(namedtuple('ConsoleInfo', 'contype, host, server, port')):
    '''
    Information about the console
    '''

    def __repr__(self):
        '''
        pretty representation of console information
        '''
        return 'host:{s.host} {s.contype}: {s.server}:{s.port}'.format(s=self)


class ConsoleCommandSession(SSHCommandSession):
    '''
    A command session that runs over a console connections.

    Currently we only support SSH connection to the console server
    '''
    _CONSOLE_PROMPTS = {
        # For login we need to ignore output like:
        #  Last login: Mon May  8 13:53:17 on ttyS0
        b'login': b'.*((?<!Last ).ogin|.sername):',
        b'passwd': b'\n.*assword:',
        b'prompt': b'\n.*[#>]',
    }

    # Certain prompts that we get during the login attemts that we will like to
    # ignore
    _CONSOLE_INGORE = {
        b' to cli \]',
        b'who is on this device.\]\r\n',
    }

    _CONSOLE_PROMPT_RE = None
    _CONSOLE_EXPECT_DELAY = 5

    def __init__(self, service, devinfo, options, loop):
        super().__init__(service, devinfo, options, loop)
        self._console = options['console']

    @classmethod
    def get_prompt_re(cls):
        '''
        The first time this is called, we will builds the prompt for the
        console. After that we will return the pre-computed regex
        '''
        if not cls._CONSOLE_PROMPT_RE:
            prompts = [b'(?P<%s>%s)' % (group, regex)
                       for group, regex in cls._CONSOLE_PROMPTS.items()]
            # Add a set of prompts that we want to ignore
            ignore_prompts = b'|'.join((b'(%s)' % p for p in cls._CONSOLE_INGORE))
            prompts.append(b'(?P<ignore>%s)' % ignore_prompts)
            prompt_re = b'|'.join(prompts)
            cls._CONSOLE_PROMPT_RE = re.compile(prompt_re + b'\s*$')
        return cls._CONSOLE_PROMPT_RE

    async def dest_info(self):
        console = await self.get_console_info()
        self.logger.info("%s", str(console))
        return (console.server, console.port)

    async def expect(self, regex, timeout=_CONSOLE_EXPECT_DELAY):
        try:
            return await asyncio.wait_for(self.wait_prompt(regex),
                                          timeout, loop=self._loop)
        except asyncio.TimeoutError as e:
            self.logger.info('Timeout waiting for: %s', regex)
            return None

    def send(self, data, end=b'\n'):
        '''
        send some data and optionally wait for some data
        '''
        if isinstance(data, str):
            data = data.encode('utf8')
        self._stream_writer.write(data + end)

    async def _try_login(self, username=None, passwd=None):
        '''
        A helper function that tries to login into the device
        '''
        # A small delay to avoid having to match extraneous input
        await asyncio.sleep(0.1)
        res = await self.expect(self.get_prompt_re())
        if res:
            if res.match.group('ignore'):
                # If we match anything in the ignore prompts, set a \r\n
                self.send(b'\r', end=b'')
                await asyncio.sleep(0.2)  # Let the console catch up
                # Now again try to login.
                return await self._try_login(username=username, passwd=passwd)

            elif res.match.group('login'):
                # The device is requesting login information
                # If we don't have a username, then likely we already sent a
                # username. The consoles are slow, we may have send extra
                # carriage returns, resulting in multiple login prompts. We will
                # simply ignore the subsequent login prompts.
                if username is not None:
                    self.send(self._username)
                # if we don't have username, we are likely waiting for password
                return await self._try_login(passwd=passwd)

            elif res.match.group('passwd'):
                if passwd is None:
                    # passwd information not available
                    # Likely we have alreay sent the password. Bail out instead
                    # of getting stuck in a loop.
                    raise RuntimeError('Failed to login: Password not expected')
                self.send(self._password)
                return await self._try_login()

            elif res.match.group('prompt'):
                # Finally we matched a prompt. we are done
                return self.send(b'\r')

            else:
                raise RuntimeError("Matched no group: %s" % (res.groupdict()))
        else:
            raise RuntimeError("Login failed")

    async def _setup_connection(self):
        await self._try_login(self._username, self._password)
        # Now send the setup commands
        await super()._setup_connection()

    async def get_console_info(self):
        '''
        By default we assume a console is directly specified by the user.
        Depending on your system, you may want to get this information from
        your local database. In such case you can override this method
        according to your needs
        '''
        con_srv, con_port = self._console.split(':')

        return ConsoleInfo("CON", self.hostname, con_srv, con_port)
