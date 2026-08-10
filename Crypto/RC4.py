STATE_LENGTH = 256

class RC4:
    def __init__(self, key: str):
        self.key = bytearray.fromhex(key)
        self.x = 0
        self.y = 0
        self.state = [0] * STATE_LENGTH
        self.reset()

    def reset(self):
        self.x = 0
        self.y = 0

        # KSA
        for i in range(STATE_LENGTH):
            self.state[i] = i

        j = 0
        for i in range(STATE_LENGTH):
            j = (j + self.state[i] + self.key[i % len(self.key)]) % STATE_LENGTH
            self.state[i], self.state[j] = self.state[j], self.state[i]

    def process(self, data):
        # Accepts bytes, bytearray, or hex string
        if isinstance(data, str):
            data = bytearray.fromhex(data)
        elif isinstance(data, bytes):
            data = bytearray(data)

        # PRGA
        for i in range(len(data)):
            self.x = (self.x + 1) & 0xFF
            self.y = (self.y + self.state[self.x]) & 0xFF
            self.state[self.x], self.state[self.y] = self.state[self.y], self.state[self.x]
            k = self.state[(self.state[self.x] + self.state[self.y]) & 0xFF]
            data[i] ^= k

        return bytes(data)
