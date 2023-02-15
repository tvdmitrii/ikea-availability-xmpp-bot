#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    Slixmpp OMEMO plugin
    Copyright (C) 2010  Nathanael C. Fritz
    Copyright (C) 2019 Maxime “pep” Buquet <pep@bouah.net>
    This file is part of slixmpp-omemo.

    See the file LICENSE for copying permission.
"""
import os
import re
import sys
import asyncio
import logging
import threading

from slixmpp import ClientXMPP, JID
from slixmpp.exceptions import IqTimeout, IqError
from slixmpp.stanza import Message
import slixmpp_omemo
from slixmpp_omemo import PluginCouldNotLoad, MissingOwnKey, EncryptionPrepareException
from slixmpp_omemo import UndecidedException, UntrustedException, NoAvailableSession
from omemo.exceptions import MissingBundleException

log = logging.getLogger(__name__)

# Used by the EchoBot
LEVEL_DEBUG = 0
LEVEL_ERROR = 1


class MessageIn:
    def __init__(self, mfrom: JID = None, mtype: str = "", body=""):
        self.mfrom = mfrom
        self.mtype = mtype
        self.body = body
        self.error = False

    def __str__(self):
        return "mfrom: " + str(self.mfrom) + ", mtype: " + self.mtype + ", body: " + str(self.body) + ", error: " + str(
            self.error)


class MessageOut:
    def __init__(self, mto: JID = None, mtype: str = "", body=""):
        self.mto = mto
        self.mtype = mtype
        self.body = body
        self.error = False

    def __str__(self):
        return "mto: " + str(self.mto) + ", mtype: " + self.mtype + ", body: " + str(self.body) + ", error: " + str(
            self.error)


def start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


class EchoBot(ClientXMPP):
    """
    A simple Slixmpp bot that will echo encrypted messages it receives, along
    with a short thank you message.

    For details on how to build a client with slixmpp, look at examples in the
    slixmpp repository.
    """

    eme_ns = 'eu.siacs.conversations.axolotl'
    debug_level: int = LEVEL_DEBUG  # or LEVEL_ERROR

    def __init__(self, jid, password):
        self.loop = asyncio.new_event_loop()
        t = threading.Thread(target=start_background_loop, args=(self.loop,), daemon=True)
        t.start()

        ClientXMPP.__init__(self, jid, password)
        self.onMessageReceived = None
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.receive_message)

    def start(self, _event) -> None:
        """
        Process the session_start event.

        Typical actions for the session_start event are
        requesting the roster and broadcasting an initial
        presence stanza.

        Arguments:
            event -- An empty dictionary. The session_start
                     event does not provide any additional
                     data.
        """
        self.send_presence()
        self.get_roster()

    async def _decrypt_message(self, msg: Message, allow_untrusted: bool = False) -> None:
        """
        Process incoming message stanzas. Be aware that this also
        includes MUC messages and error messages. It is usually
        a good idea to check the messages's type before processing
        or sending replies.

        Arguments:
            msg -- The received message stanza. See the documentation
                   for stanza objects and the Message stanza to see
                   how it may be used.
        """
        mfrom = msg['from']
        mtype = msg['type']

        msg_received = MessageIn()
        msg_received.mfrom = mfrom
        msg_received.mtype = mtype

        msg_received.body = ""
        msg_received.error = True

        if not self['xep_0384'].is_encrypted(msg):
            return None

        try:
            encrypted = msg['omemo_encrypted']
            body = self['xep_0384'].decrypt_message(encrypted, mfrom, allow_untrusted)
            msg_received.body = body.decode('utf8')
            msg_received.error = False
            self.onMessageReceived(msg_received)
        except (MissingOwnKey,) as exn:
            # The message is missing our own key, it was not encrypted for
            # us, and we can't decrypt it.
            log.error('Decryption Error. Message not encrypted for me: ' + str(exn))
        except (NoAvailableSession,) as exn:
            # We received a message from that contained a session that we
            # don't know about (deleted session storage, etc.). We can't
            # decrypt the message, and it's going to be lost.
            # Here, as we need to initiate a new encrypted session, it is
            # best if we send an encrypted message directly. XXX: Is it
            # where we talk about self-healing messages?
            log.error('Decryption Error. Message uses an encrypted '
                      'session I don\'t know about:'  + str(exn))
        except (UndecidedException, UntrustedException) as exn:
            # We received a message from an untrusted device. We can
            # choose to decrypt the message nonetheless, with the
            # `allow_untrusted` flag on the `decrypt_message` call, which
            # we will do here. This is only possible for decryption,
            # encryption will require us to decide if we trust the device
            # or not. Clients _should_ indicate that the message was not
            # trusted, or in undecided state, if they decide to decrypt it
            # anyway.
            log.warning("Decryption Error. Your device is not in my trusted devices:" + str(exn))
            await self._decrypt_message(msg, True)
        except (EncryptionPrepareException,) as exn:
            # Slixmpp tried its best, but there were errors it couldn't
            # resolve. At this point you should have seen other exceptions
            # and given a chance to resolve them already.
            log.error("Decryption Error. I was not able to decrypt the message:" + str(exn))
        except (Exception,) as exn:
            log.error("Decryption Error. Exception occured while attempting decryption." + str(exn))

    def receive_message(self, msg: Message):
        asyncio.run_coroutine_threadsafe(self._decrypt_message(msg), self.loop)
        # asyncio.ensure_future(self._decrypt_message(msg))

    def send_message(self, msg: MessageOut):
        asyncio.run_coroutine_threadsafe(self._send_encrypted_message(JID(msg.mto), msg.mtype, msg.body), self.loop)
        # asyncio.ensure_future(
        #    self._send_encrypted_message(JID(msg.mto), msg.mtype, msg.body))

    async def _send_encrypted_message(self, mto: JID, mtype: str, body):
        """Helper to reply with encrypted messages"""

        msg = self.make_message(mto=mto, mtype=mtype)
        msg['eme']['namespace'] = self.eme_ns
        msg['eme']['name'] = self['xep_0380'].mechanisms[self.eme_ns]

        expect_problems = {}  # type: Optional[Dict[JID, List[int]]]

        while True:
            try:
                # `encrypt_message` excepts the plaintext to be sent, a list of
                # bare JIDs to encrypt to, and optionally a dict of problems to
                # expect per bare JID.
                #
                # Note that this function returns an `<encrypted/>` object,
                # and not a full Message stanza. This combined with the
                # `recipients` parameter that requires for a list of JIDs,
                # allows you to encrypt for 1:1 as well as groupchats (MUC).
                #
                # `expect_problems`: See EncryptionPrepareException handling.
                recipients = [mto]
                encrypt = await self['xep_0384'].encrypt_message(body, recipients, expect_problems)
                msg.append(encrypt)
                return msg.send()
            except UndecidedException as exn:
                # The library prevents us from sending a message to an
                # untrusted/undecided barejid, so we need to make a decision here.
                # This is where you prompt your user to ask what to do. In
                # this bot we will automatically trust undecided recipients.
                log.warning("Adding new trusted device: " + str(exn))
                self['xep_0384'].trust(exn.bare_jid, exn.device, exn.ik)
            # TODO: catch NoEligibleDevicesException
            except EncryptionPrepareException as exn:
                # This exception is being raised when the library has tried
                # all it could and doesn't know what to do anymore. It
                # contains a list of exceptions that the user must resolve, or
                # explicitely ignore via `expect_problems`.
                # TODO: We might need to bail out here if errors are the same?
                for error in exn.errors:
                    if isinstance(error, MissingBundleException):
                        # We choose to ignore MissingBundleException. It seems
                        # to be somewhat accepted that it's better not to
                        # encrypt for a device if it has problems and encrypt
                        # for the rest, rather than error out. The "faulty"
                        # device won't be able to decrypt and should display a
                        # generic message. The receiving end-user at this
                        # point can bring up the issue if it happens.
                        log.warning('Could not find keys for device  of recipient . Skipping.' + str(error))
                        jid = JID(error.bare_jid)
                        device_list = expect_problems.setdefault(jid, [])
                        device_list.append(error.device)
            except (IqError, IqTimeout) as exn:
                log.error('An error occurred while fetching information on a recipient.\n%r' % exn)
                return None
            except Exception as exn:
                log.error('An error occurred while attempting to encrypt.\n%r' % exn)
                raise

        return None

    def setMessageReceivedCallback(self, callback):
        self.onMessageReceived = callback

    def initialize(self):
        # Data dir for omemo plugin
        data_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'omemo',
        )

        # Setup logging.
        logging.basicConfig(level=logging.INFO,
                            format='%(levelname)-8s %(message)s',
                            filename='xmppBot.log', filemode='w')

        # Ensure OMEMO data dir is created
        os.makedirs(data_dir, exist_ok=True)
        self.register_plugin('xep_0030')  # Service Discovery
        self.register_plugin('xep_0199')  # XMPP Ping
        self.register_plugin('xep_0380')  # Explicit Message Encryption

        try:
            self.register_plugin(
                'xep_0384',
                {
                    'data_dir': data_dir,
                },
                module=slixmpp_omemo,
            )  # OMEMO
        except (PluginCouldNotLoad,):
            log.exception('And error occured when loading the omemo plugin.')
            sys.exit(1)
