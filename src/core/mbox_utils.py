import mailbox


class RobustMbox(mailbox.mbox):
    """A subclass of mailbox.mbox that handles non-ASCII characters in 'From ' lines.

    The standard library mailbox.mbox.get_message() hardcodes .decode('ascii')
    for the from_line, which fails on Eudora and other legacy mbox files. This
    class provides a more robust implementation that falls back to latin-1
    if ascii decoding fails.
    """

    def get_message(self, key):
        """Return an mboxMessage with better encoding handling for the From line.

        Args:
            key: The key identifying the message in the mailbox.

        Returns:
            mailbox.mboxMessage: The retrieved message with safely decoded From line.
        """
        # This implementation is adapted from mailbox.py to handle encoding safely
        import mailbox as mb

        offsets = self._lookup(key)
        self._file.seek(offsets[0])

        # Read the 'From ' line and decode safely
        # We handle both \n and \r\n line endings
        from_line = self._file.readline().replace(b"\r\n", b"").replace(b"\n", b"")
        try:
            from_line_str = from_line.decode("ascii")
        except UnicodeDecodeError:
            # Fallback to latin-1 which is robust for all byte values and common in legacy mbox
            from_line_str = from_line.decode("latin-1")

        # Read the rest of the message content
        # Tell() is at the start of the headers now (just after the From line)
        msg_bytes = self._file.read(offsets[1] - self._file.tell())

        # Use the configured message factory if available (matches stdlib behavior)
        message_factory = (
            getattr(self, "_factory", None)
            or getattr(self, "_message_factory", None)
            or mb.mboxMessage
        )
        msg = message_factory(msg_bytes)

        # Strip "From " (5 chars) and set it
        if from_line_str.startswith("From "):
            msg.set_from(from_line_str[5:])
        else:
            msg.set_from(from_line_str)

        return msg
