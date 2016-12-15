from Utils import *


class PaddingOracle(object):
    def __init__(self, block_size=16):
        if block_size % 8 != 0:
            log.critical_error("Incorrect block length: {}".format(block_size))
        self.block_size = block_size

    def oracle(self, payload, iv, previous_resp, *args, **kwargs):
        """Function implementing padding oracle

        Args:
            payload(string): ciphertext to check
            iv(string): initialization vector (most often: append it at beginning of payload)
            previous_resp(user_specified): something returned by previous call to oracle method
            args, kwargs

        Returns:
            tuple: (True/False, response)
                True if padding is correct, False otherwise
                response will be send as previous_response to next call
        """
        raise NotImplementedError

    def decrypt(self, ciphertext, iv=None, is_correct=True, amount=0, known_plaintext=None, async=False, *args, **kwargs):
        """Decrypt ciphertext using padding oracle

        Args:
            ciphertext(string): to decrypt
            iv(string): if not specified, first block of ciphertext is treated as iv
            is_correct(bool): set if ciphertext will decrypt to something with correct padding
            amount(int): how much blocks decrypt (counting from last), zero (default) means all
            known_plaintext(string): with padding, from end
            async(bool): make asynchronous calls to oracle (not implemented yet)
            args, kwargs: push forward to oracle function

        Returns:
            plaintext(string)
        """

        log.info("Start decrypt")
        log.debug(print_chunks(chunks(ciphertext, self.block_size)))

        if len(ciphertext) % self.block_size != 0:
            log.critical_error("Incorrect ciphertext length: {}".format(len(ciphertext)))

        # prepare blocks
        blocks = chunks(ciphertext, self.block_size)
        resp = None
        if iv:
            if len(iv) % self.block_size != 0:
                log.critical_error("Incorrect iv length: {}".format(len(iv)))
            log.info("Set iv")
            blocks.insert(0, iv)

        if amount != 0:
            amount = len(blocks) - amount - 1
        if amount < 0 or amount >= len(blocks):
            log.critical_error("Incorrect amount of blocks to decrypt: {} (have to be in [0,{}]".format(amount, len(blocks)-1))
        log.info("Will decrypt {} block(s)".format(len(blocks)-1-amount))

        # add known plaintext
        plaintext = ''
        position_known = 0
        if known_plaintext:
            is_correct = False
            plaintext = known_plaintext
            blocks_decoded = len(plaintext) // self.block_size
            chars_decoded = len(plaintext) % self.block_size

            if blocks_decoded == len(blocks):
                log.debug("Nothing decrypted, known plaintext long enough")
                return plaintext
            if blocks_decoded > len(blocks)-1:
                log.critical_error("Too long known plaintext ({} blocks)".format(blocks_decoded))

            if blocks_decoded != 0:
                blocks = blocks[:-blocks_decoded]
            if chars_decoded != 0:
                blocks[-2] = blocks[-2][:-chars_decoded] + xor(plaintext[:chars_decoded], blocks[-2][-chars_decoded:], chr(chars_decoded+1))
            position_known = chars_decoded
            log.info("Have known plaintext, skip {} block(s) and {} bytes".format(blocks_decoded, chars_decoded))

        for count_block in xrange(len(blocks)-1, amount, -1):
            """ Blocks from the last to the second (all except iv)"""
            log.info("Block no. {}".format(count_block))

            payload_prefix = ''.join(blocks[:count_block-1])
            payload_modify = blocks[count_block-1]
            payload_decrypt = blocks[count_block]

            position = self.block_size - 1 - position_known
            position_known = 0
            while position >= 0:
                """ Every position in block, from the end"""
                log.debug("Position: {}".format(position))

                found_correct_char = False
                for guess_char in xrange(256):
                    modified = payload_modify[:position] + chr(guess_char) + payload_modify[position+1:]
                    payload = ''.join([payload_prefix, modified, payload_decrypt])

                    iv = payload[:self.block_size]
                    payload = payload[self.block_size:]
                    log.debug(print_chunks(chunks(iv + payload, self.block_size)))

                    correct, resp = self.oracle(payload=payload, iv=iv, previous_resp=resp, *args, **kwargs)
                    if correct:
                        """ oracle returns True """
                        padding = self.block_size - position  # sent ciphertext decoded to that padding
                        decrypted_char = chr(ord(payload_modify[position]) ^ guess_char ^ padding)

                        if is_correct:
                            """ If we didn't send original ciphertext, then we have found original padding value.
                                Otherwise keep searching and if won't find any other correct char - padding is \x01
                            """
                            if guess_char == ord(blocks[-2][-1]):
                                log.debug("Skip this guess char ({})".format(guess_char))
                                continue

                            dc = ord(decrypted_char)
                            log.info("Found padding value for correct ciphertext: {}".format(dc))
                            if dc == 0 or dc > self.block_size:
                                log.critical_error("Found bad padding value (given ciphertext may not be correct)")

                            plaintext = decrypted_char * dc
                            payload_modify = payload_modify[:-dc] + xor(payload_modify[-dc:], decrypted_char, chr(dc+1))
                            position = position - dc + 1
                            is_correct = False
                        else:
                            """ abcd efgh ijkl o|guess_char|xy  || 1234 5678 9tre qwer - ciphertext
                                what ever itma ybex             || xyzw rtua lopo k|\x03|\x03\x03 - plaintext
                                abcd efgh ijkl |guess_char|wxy  || 1234 5678 9tre qwer - next round ciphertext
                                some thin gels eheh             || xyzw rtua lopo guessing|\x04\x04\x04 - next round plaintext
                            """
                            if position == self.block_size - 1:
                                """ if we decrypt first byte, check if we didn't hit other padding than \x01 """
                                payload = iv + payload
                                payload = payload[:-self.block_size - 2] + 'A' + payload[-self.block_size - 1:]
                                iv = payload[:self.block_size]
                                payload = payload[self.block_size:]
                                correct, resp = self.oracle(payload=payload, iv=iv, previous_resp=resp, *args, **kwargs)
                                if not correct:
                                    log.debug("Hit false positive, guess char({})".format(guess_char))
                                    continue

                            payload_modify = payload_modify[:position] + xor(chr(guess_char)+payload_modify[position+1:], chr(padding), chr(padding+1))
                            plaintext = decrypted_char + plaintext

                        found_correct_char = True
                        log.debug("Guessed char(\\x{:02x}), decrypted char(\\x{:02x})".format(guess_char, ord(decrypted_char)))
                        log.debug("Plaintext: {}".format(plaintext))
                        log.info("Plaintext(hex): {}".format(plaintext.encode('hex')))
                        break
                position -= 1
                if found_correct_char is False:
                    if is_correct:
                        padding = 0x01
                        payload_modify = payload_modify[:position+1] + xor(payload_modify[position+1:], chr(padding), chr(padding + 1))
                        plaintext = "\x01"
                        is_correct = False
                    else:
                        log.critical_error("Can't find correct padding (oracle function return False 256 times)")
        log.success("Decrypted(hex): {}".format(plaintext.encode('hex')))
        return plaintext

    def fake_ciphertext(self, new_plaintext, original_ciphertext=None, iv=None, original_plaintext=None, *args, **kwargs):
        """Make ciphertext so it will decrypt to given plaintext

        Args:
            new_plaintext(string): with padding
            original_ciphertext(string): have to be correct, len(new_plaintext) == len(original_ciphertext)+len(iv)-len(block_size)
            iv(string): if not specified, first block of ciphertext is treated as iv
            original_plaintext(string): corresponding to original_ciphertext, with padding, only last len(block_size) bytes will be used
            args, kwargs: push forward to oracle function

        Returns:
            fake_ciphertext(string): fake ciphertext that will decrypt to new_plaintext
        """

        log.info("Start fake ciphertext")

        if original_ciphertext is None:
            if original_plaintext:
                log.critical_error("Original plaintext given without original ciphertext")
            if iv:
                log.critical_error("iv given without original ciphertext")
            ciphertext = 'A'*(len(new_plaintext) + self.block_size)
        else:
            ciphertext = original_ciphertext

        if original_ciphertext and len(original_ciphertext) % self.block_size != 0:
            log.critical_error("Incorrect original ciphertext length: {}".format(len(original_ciphertext)))
        if len(new_plaintext) % self.block_size != 0:
            log.critical_error("Incorrect new plaintext length: {}".format(len(new_plaintext)))

        # prepare blocks
        blocks = chunks(ciphertext, self.block_size)
        new_pl_blocks = chunks(new_plaintext, self.block_size)
        if iv:
            log.info("Set iv")
            blocks.insert(0, iv)
        if len(new_pl_blocks) != len(blocks)-1:
            log.critical_error("Wrong new plaintext length({}), should be {}".format(len(new_plaintext), self.block_size * (len(blocks)-1)))
        new_ct_blocks = list(blocks)

        # add known plaintext
        if original_plaintext:
            if original_plaintext > self.block_size:
                log.info("Cut original plaintext from {} to last {} bytes".format(len(original_plaintext), self.block_size))
                original_plaintext = original_plaintext[-self.block_size:]

        for count_block in xrange(len(blocks)-1, 0, -1):
            """ Every block, modify block[count_block-1] to set block[count_block] """
            log.info("Block no. {}".format(count_block))

            if original_plaintext is None and original_ciphertext is None:
                original_plaintext = self.decrypt(''.join(new_ct_blocks[:count_block+1]), amount=1,
                                                  is_correct=False, *args, **kwargs)
            elif original_plaintext and original_ciphertext:
                original_plaintext = self.decrypt(''.join(new_ct_blocks[:count_block+1]), amount=1,
                                                  is_correct=True, known_plaintext=original_plaintext, *args, **kwargs)
            else:
                original_plaintext = self.decrypt(''.join(new_ct_blocks[:count_block + 1]), amount=1,
                                                  is_correct=True, *args, **kwargs)

            log.info("Set block no. {}".format(count_block))
            new_ct_blocks[count_block-1] = xor(blocks[count_block-1], original_plaintext, new_pl_blocks[count_block-1])
            original_plaintext = None
            original_ciphertext = None

        fake_ciphertext = ''.join(new_ct_blocks)
        log.success("Fake ciphertext(hex): {}".format(fake_ciphertext.encode('hex')))
        return fake_ciphertext