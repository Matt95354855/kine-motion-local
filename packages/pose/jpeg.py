"""Lire les dimensions avant décompression : pas d'allocation sur image géante."""

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def bounded_jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG requis")
    cursor = 2
    while cursor < len(data):
        if data[cursor] != 0xFF:
            raise ValueError("En-tête JPEG invalide")
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            break
        marker = data[cursor]
        cursor += 1
        if marker in (0xD9, 0xDA):
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(data):
            break
        length = int.from_bytes(data[cursor:cursor + 2], "big")
        if length < 2 or cursor + length > len(data):
            raise ValueError("Segment JPEG tronqué")
        if marker in SOF_MARKERS:
            if length < 8:
                raise ValueError("Dimensions JPEG absentes")
            height = int.from_bytes(data[cursor + 3:cursor + 5], "big")
            width = int.from_bytes(data[cursor + 5:cursor + 7], "big")
            if not (0 < width <= 1920 and 0 < height <= 1080):
                raise ValueError("Dimensions d'image hors limite")
            return width, height
        cursor += length
    raise ValueError("Dimensions JPEG absentes")
