def bytesToHexString(bytes: bytes):
        return "\\x" + bytes.hex()
    
def hexStringToBytes(hex_str: str) -> bytes:
    if hex_str is None:
        return b""
    if isinstance(hex_str, (bytes, bytearray)):
        return bytes(hex_str)
    s = str(hex_str)
    # remove common prefixes: Postgres bytea '\\x...' or '0x...'
    if s.startswith("\\x"):
        s = s[2:]
    elif s.startswith("0x"):
        s = s[2:]
    s = s.strip()
    if s == "":
        return b""
    return bytes.fromhex(s)