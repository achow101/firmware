# (c) Copyright 2020 by Coinkite Inc. This file is part of Coldcard <coldcardwallet.com>
# and is covered by GPLv3 license found in COPYING.
#
# pwsave.py - Save bip39 passphrases into encrypted file on MicroSD (if desired)
#
import sys, tcc, stash, ujson, os
from files import CardSlot, CardMissingError
from ubinascii import hexlify as b2a_hex

class PassphraseSaver:
    # Encrypts BIP39 passphrase very carefully, and appends
    # to a file on MicroSD card. Order is preserved.
    # AES-256; key=sha256(microSD serial # hash + some derived key off master)

    def filename(self, card):
        # Construct actual filename to use.
        # - some very minor obscurity, but we aren't relying on that.
        return card.get_sd_root() + '/.fseventsd.'

    def _calc_key(self, card):
        # calculate the key to be used.
        if getattr(self, 'key', 0): return

        try:
            salt = card.get_id_hash()

            with stash.SensitiveValues(bypass_pw=True) as sv:
                key = sv.encryption_key(salt)
                assert len(key) == 32

                self.key = bytearray(key)
        except:
            self.key = None

    def _read(self, card):
        # Return a list of saved passphrases, or empty list if fail.
        # Fail silently in all cases. Expect to see lots of noise here.
        decrypt = tcc.AES(tcc.AES.CTR | tcc.AES.Decrypt, self.key)

        try:
            msg = open(self.filename(card), 'rb').read()
            txt = decrypt.update(msg)
            return ujson.loads(txt)
        except:
            return []


    async def append(self, xfp, bip39pw):
        # encrypt and save; always appends.
        from ux import ux_dramatic_pause
        from main import dis
        from actions import needs_microsd

        while 1:
            dis.fullscreen('Saving...')

            try:
                with CardSlot() as card:
                    self._calc_key(card)

                    data = self._read(card) if self.key else []

                    data.append(dict(xfp=xfp, pw=bip39pw))

                    encrypt = tcc.AES(tcc.AES.CTR | tcc.AES.Encrypt, self.key)

                    msg = encrypt.update(ujson.dumps(data))

                    with open(self.filename(card), 'wb') as fd:
                        fd.write(msg)

                await ux_dramatic_pause("Saved.", 2)
                return

            except CardMissingError:
                ch = await needs_microsd()
                if ch == 'x':       # undocumented, but needs escape route
                    break

            
    def make_menu(self):
        from menu import MenuItem, MenuSystem
        from actions import goto_top_menu
        from ux import ux_show_story
        from seed import set_bip39_passphrase

        # Read file, decrypt and make a menu to show; OR return None
        # if any error hit.
        try:
            with CardSlot() as card:
                try:
                    # check file exists before doing expensive crypto steps
                    os.stat(self.filename(card))
                except:     # OSError for ENOENT
                    return None

                self._calc_key(card)
                if not self.key: return None

                data = self._read(card)

                if not data: return None

        except CardMissingError:
            # not an error: they just aren't using feature
            return None

        # We have a list of xfp+pw fields. Make a menu.

        # challenge: we need to hint at which is which, but don't want to
        # show the password on-screen.
        # - simple algo: 
        #   - show either first N or last N chars only
        #   - pick which set which is all-unique, if neither, try N+1
        #
        pws = []
        for i in data:
            p = i.get('pw') 
            if p not in pws:
                pws.append(p)

        for N in range(1, 8):
            parts = [i[0:N] + ('*'*(len(i)-N if len(i) > N else 0)) for i in pws]
            if len(set(parts)) == len(pws): break
            parts = [('*'*(len(i)-N if len(i) > N else 0)) + i[-N:] for i in pws]
            if len(set(parts)) == len(pws): break
        else:
            # give up: show it all!
            parts = pws

        async def doit(menu, idx, item):
            # apply the password immediately and drop them at top menu

            err = set_bip39_passphrase(data[idx].get('pw'))
            if err:
                # kinda very late: but if not BIP39 based key, ends up here.
                return await ux_show_story(err, title="Fail")

            from main import settings
            from utils import xfp2str
            xfp = settings.get('xfp')

            # they are big boys now, and don't need to have BIP39 explained everytime.
            if not settings.get('b39skip', False):
                settings.set('b39skip', True)

            # verification step; I don't see any way for this to go wrong
            assert xfp == data[idx].get('xfp')

            # feedback that it worked
            await ux_show_story("Passphrase restored.", title="[%s]" % xfp2str(xfp))

            goto_top_menu()


        return MenuSystem((MenuItem(label, f=doit) for label in parts))
        
# EOF
