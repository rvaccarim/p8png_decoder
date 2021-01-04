import png
from enum import Enum

# https://pico-8.fandom.com/wiki/P8PNGFileFormat

stream_str = ""
stream_pos = 0


class FORMAT(Enum):
    PLAINTEXT_FORMAT = 1
    OLD_COMPRESSED_FORMAT = 2
    NEW_COMPRESSED_FORMAT = 3


def unsteganize_png(width, height, rows, info):
    # Each PICO-8 byte is stored as the two least significant bits of each of the four color channels, ordered ARGB
    # (E.g: the A channel stores the 2 most significant bits in the bytes). The image is 160 pixels wide and 205 pixels
    # high, for a possible storage of 32,800 bytes. Of these, only the first 32,773 bytes are used.

    # https://stackoverflow.com/questions/32629337/pypng-what-does-plane-mean
    # The "planes" are sort of "channels". The number of planes correspond to the dimension of each pixel value.
    #  planes
    #    1       [G]             (gray)            monochrome
    #    1       [I]            (indexed)          palette
    #    2      [G A]         (gray, alpha)        monochrome with transparency
    #    3     [R G B]     (red, green, blue)      full colour
    #    4    [R G B A]  (red, green, blue, alpha) full colour with transp.

    hidden_data = [0] * width * height
    planes = info['planes']
    assert planes == 4

    for row, row_data in enumerate(rows):
        for col in range(width):
            # keep the last 2 bits only
            R = row_data[col * planes + 0] & int('00000011', 2)
            G = row_data[col * planes + 1] & int('00000011', 2)
            B = row_data[col * planes + 2] & int('00000011', 2)
            A = row_data[col * planes + 3] & int('00000011', 2)

            # PICO likes them in ARGB format
            pico_byte = A << 6 | R << 4 | G << 2 | B
            hidden_data[(row * width) + col] = pico_byte

    return hidden_data


def get_version(hidden_data):
    # If the first four bytes are a null (\x00) followed by pxa, then the code is stored in the new (v0.2.0+)
    # compressed format.
    # If the first four bytes are :c: followed by a null (\x00), then the code is stored in the old (pre-v0.2.0)
    # compressed format.
    # In all other cases, the code is stored as plaintext (ASCII), up to the first null byte.
    if bytes(hidden_data[0x4300:0x4304]) == b'\x00pxa':
        return FORMAT.NEW_COMPRESSED_FORMAT
    elif bytes(hidden_data[0x4300:0x4304]) == b':c:\x00':
        return FORMAT.OLD_COMPRESSED_FORMAT
    else:
        return FORMAT.PLAINTEXT_FORMAT


def get_code_plaintext(hidden_data):
    # the code is stored as plaintext (ASCII), up to the first
    # null byte
    code = []
    code_pos = 0x4300

    while code_pos < 0x8000:
        curr_byte = hidden_data[code_pos]
        if curr_byte == 0:
            break

        code.append(chr(curr_byte))
        code_pos += 1

    return "".join(code) + "\n"


def get_code_oldcompression(hidden_data):
    CHAR_TABLE = \
        ' \n 0123456789abcdefghijklmnopqrstuvwxyz!#%(){}[]<>+=/*:;.,~_'

    # bytes 0x4304-0x4305 are the length of the decompressed code,
    # stored MSB first.
    decompressed_length = (hidden_data[0x4304] << 8) | \
                          hidden_data[0x4305]

    # The next two bytes (0x4306-0x4307) are always zero.
    assert hidden_data[0x4306] == 0
    assert hidden_data[0x4307] == 0

    code = []
    code_pos = 0x4308

    while len(code) < decompressed_length:
        curr_byte = hidden_data[code_pos]

        if curr_byte == 0x00:
            # 0x00: Copy the next byte directly to the output
            # stream.
            code.append(chr(hidden_data[code_pos + 1]))
            code_pos += 2

        elif curr_byte <= 0x3b:
            # 0x01-0x3b: Emit a character from a lookup table
            code.append(CHAR_TABLE[curr_byte])
            code_pos += 1

        else:
            # 0x3c-0xff: Calculate an offset and length from this byte
            # and the next byte, then copy those bytes from what has
            # already been emitted. In other words, go back "offset"
            # characters in the output stream, copy "length" characters,
            # then paste them to the end of the output stream.
            next_byte = hidden_data[code_pos + 1]

            # this magic stuff comes from the format specification
            offset = (curr_byte - 0x3c) * 16 + (next_byte & 0xf)
            index = len(code) - offset
            length = (next_byte >> 4) + 2

            try:
                for i in range(length):
                    b = code[index + i]
                    code.append(b)
            except IndexError as e:
                return f"ERROR DECODING\noffset={offset} length={length}\n\n" \
                       + "".join(code)

            code_pos += 2

    return "".join(code)


def read_bit():
    global stream_pos
    bit = stream_str[stream_pos: stream_pos + 1]
    # print(f"stream_pos={stream_pos}, read bit, bit={bit}")
    stream_pos += 1
    return bit


def read_bits(positions):
    global stream_pos
    inv_bits = stream_str[stream_pos: stream_pos + positions][::-1]
    # print(f"stream_pos={stream_pos}, read_bits, positions={positions} inv_bits={inv_bits}")
    stream_pos += positions
    return inv_bits


def get_code_newcompression(hidden_data):
    global stream_pos, stream_str
    code_str = ""

    # bytes 0x4304-0x4305 are the length of the decompressed code,
    # stored MSB first.
    decompressed_code_length = (hidden_data[0x4304] << 8) \
                               | hidden_data[0x4305]

    # The next two bytes (0x4306-0x4307) are the length of the
    # compressed data + 8 for this 8-byte header, stored MSB first.
    compressed_data_length = hidden_data[0x4306] << 8 \
                             | hidden_data[0x4307]

    # The decompression algorithm maintains a "move-to-front" mapping
    # of the 256 possible bytes. Initially, each of the 256 possible
    # bytes maps to itself.
    move_to_front = []
    for i in range(256):
        move_to_front.append(i)

    # The decompression algorithm processes the compressed data bit
    # by bit - going from LSB to MSB of each byte - until the data
    # length of decompressed characters has been emitted. We create
    # a string with all bytes inverted to simulate the decoding stream
    stream = []
    code_pos = 0x4308
    while code_pos < 0x8000:
        # convert to binary and reverse
        stream.append(format(hidden_data[code_pos], '08b')[::-1])
        code_pos += 1

    stream_str = "".join(stream)
    stream_pos = 0

    while len(code_str) < decompressed_code_length:
        # log: print(f"------------------------------------")
        # log: print(f"stream_pos={stream_pos}, starting loop")
        # log: print(f"next_24_bits={stream_str[stream_pos: stream_pos + 24]}")

        # Each group of bits starts with a single header bit,
        # specifying the group's type.
        header = read_bit()
        # print(f"stream_pos={stream_pos}, header={header}")

        if code_str.endswith('split"'):
            xxx = 0

        if header == "1":
            # header bit = 1 -> get a character from the index
            # these values and bit manipulations are documented in
            # the P8.PNG spec
            unary = 0
            while read_bit() == "1":
                unary += 1
            unary_mask = ((1 << unary) - 1)
            bin_str = read_bits(4 + unary)
            index = int(bin_str, 2) + (unary_mask << 4)

            try:
                # get and emit character
                c = chr(move_to_front[index])
                code_str += c
                # print(f"index={index}, emitted={c}")

            except IndexError as e:
                err_str = f"ERROR DECODING\nindex={index}\n\n"
                print(err_str)
                return err_str + code_str

            # update move_to_front data structure
            move_to_front.insert(0, move_to_front.pop(index))

        else:
            # header bit = 2 -> copy/paste a segment
            # these values and bit manipulations are documented
            # in the P8.PNG spec
            # print(f"reading control bits")
            if read_bit() == "1":
                if read_bit() == "1":
                    offset_positions = 5
                else:
                    offset_positions = 10
            else:
                offset_positions = 15

            # print(f"reading offset")
            offset_bits = read_bits(offset_positions)
            offset_backwards = int(offset_bits, 2) + 1
            # print(f"offset_backwards={offset_backwards}")

            # print(f"reading length")
            length = 3
            while True:
                part = int(read_bits(3), 2)
                length += part
                # print(f"inside length while, length:{length}")

                if part != 7:
                    break
            # print(f"length={length}")

            # Then we go back "offset" characters in the output stream,
            # and copy "length" characters to the end of the output stream.
            # "length" may be larger than "offset", in which case we
            # effectively repeat a pattern of "offset" characters.
            if offset_backwards > len(code_str):
                err_str = f"ERROR DECODING\nback_offset={offset_backwards} len code_str={len(code_str)}\n\n"
                print(err_str)
                return err_str + code_str
            else:
                if -offset_backwards + length >= 0:
                    chunk = code_str[-offset_backwards:]
                else:
                    chunk = code_str[-offset_backwards: -offset_backwards + length]

            assert len(chunk) > 0

            if length > offset_backwards:
                chunk += repeat_to_length(chunk, length - offset_backwards)

            # print(f"{chunk}")
            code_str += chunk

        # print(f"stream_pos={stream_pos}, end loop")

    return code_str


def repeat_to_length(string_to_expand, length):
    return (string_to_expand * (int(length/len(string_to_expand))+1))[:length]


def extract_code(filename):
    code = ""
    image = png.Reader(filename)
    (width, height, rows, info) = image.read()

    # The image should be 160w x 205h pixels
    if width == 160 and height == 205:
        hidden_data = unsteganize_png(width, height, rows, info)
        version = get_version(hidden_data)
        print(version.name)

        if version == FORMAT.PLAINTEXT_FORMAT:
            code = get_code_plaintext(hidden_data)
        elif version == FORMAT.OLD_COMPRESSED_FORMAT:
            code = get_code_oldcompression(hidden_data)
        else:
            code = get_code_newcompression(hidden_data)
    else:
        code = "Wrong card size"

    image.file.close()
    return code


def main():
    game_dir = "../tests/0_games/"
    game = "jostitle-6"
    with open(f"{game}.txt", mode="w", encoding="utf-8", errors='strict', buffering=1) as f:
        f.write(extract_code(filename=f"{game_dir}{game}.p8.png"))


if __name__ == "__main__":
    main()






